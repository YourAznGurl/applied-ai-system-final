"""The VibeFinder agent: plans, calls tools, and checks its own work."""
import csv
import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .guardrails import check_explanation, validate_request
from .llm import ask_llm, llm_available
from .rag import Retriever, energy_word, load_knowledge_chunks

# Use your ORIGINAL Module 3 recommender if it is there; otherwise a backup scorer below.
try:
    from .recommender import load_songs as _orig_load_songs
    from .recommender import recommend_songs as _orig_recommend
except ImportError:
    _orig_load_songs = None
    _orig_recommend = None

ROOT = Path(__file__).resolve().parent.parent
SONGS_PATH = ROOT / "data" / "songs.csv"
TRACE_FILE = ROOT / "ai_interactions.md"
logger = logging.getLogger("vibefinder")

# Pattern used to read the "Recommended:" line inside knowledge/mood_guide.md
HINT_RE = re.compile(
    r"Recommended:\s*genre=([^;]+);\s*mood=([^;]+);\s*energy=([0-9.]+)", re.IGNORECASE
)

DJ_SYSTEM = """You are DJ VibeFinder, a friendly radio DJ.
Rules:
- Start with exactly: DJ VibeFinder here:
- Use at most 60 words.
- Mention every song title from the list exactly as written. Never mention songs not in the list.
- End with a final line that starts with: Next up:
Example
Request: pump me up for the gym
Songs: Song A by Artist A; Song B by Artist B
Answer: DJ VibeFinder here: time to lift! Song A and Song B bring the driving beat you need.
Next up: intense"""

PLAIN_SYSTEM = "You explain music recommendations clearly in 2 or 3 sentences."


def setup_logging():
    """Send log messages to logs/app.log so every run leaves a record."""
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=str(log_dir / "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _get(item, key, default=None):
    """Read a field from a dict OR an object."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


# ---------- backup song loader and scorer (only used if the original fails) ----------
NUMBER_COLUMNS = {"energy", "tempo_bpm", "valence", "danceability", "acousticness"}


def _fallback_load_songs(path):
    songs = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for key in NUMBER_COLUMNS:
                if key in row:
                    try:
                        row[key] = float(row[key])
                    except (TypeError, ValueError):
                        pass
            songs.append(row)
    return songs


def _fallback_recommend(prefs, songs, k=5):
    scored = []
    for song in songs:
        score, reasons = 0.0, []
        if str(_get(song, "genre", "")).lower() == str(prefs.get("genre", "")).lower():
            score += 2.0
            reasons.append("genre match")
        if str(_get(song, "mood", "")).lower() == str(prefs.get("mood", "")).lower():
            score += 1.0
            reasons.append("mood match")
        try:
            gap = abs(float(_get(song, "energy", 0.5)) - float(prefs.get("energy", 0.5)))
            score += (1 - gap) * 1.5
            reasons.append(f"energy gap {gap:.2f}")
        except (TypeError, ValueError):
            pass
        scored.append((song, round(score, 2), ", ".join(reasons) or "no direct match"))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:k]


def _to_rec(item):
    """Turn whatever the recommender returns into one simple dictionary."""
    if isinstance(item, (tuple, list)):
        song = item[0]
        score = item[1] if len(item) > 1 else 0
        reason = item[2] if len(item) > 2 else ""
    else:
        song, score, reason = item, 0, ""
    try:
        score = round(float(score), 2)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "title": str(_get(song, "title", "?")),
        "artist": str(_get(song, "artist", "?")),
        "genre": str(_get(song, "genre", "?")),
        "mood": str(_get(song, "mood", "?")),
        "energy": _get(song, "energy", None),
        "score": score,
        "reason": str(reason),
    }


# ---------- preference extraction ----------
def _extract_with_llm(query, context, genres, moods):
    """Ask Gemini to turn the request into genre / mood / energy (as JSON)."""
    prompt = (
        "You turn a music request into search preferences.\n"
        f"Allowed genres: {', '.join(genres)}\n"
        f"Allowed moods: {', '.join(moods)}\n"
        f"Helpful background notes:\n{context}\n\n"
        f'Request: "{query}"\n'
        'Reply with ONLY JSON like {"genre": "lofi", "mood": "focused", "energy": 0.35}. '
        "Use null for genre or mood if the request does not make it clear. "
        "energy is a number from 0.0 (very calm) to 1.0 (very intense)."
    )
    reply = ask_llm(prompt)
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON found in reply")
    data = json.loads(reply[start:end + 1])
    return {"genre": data.get("genre"), "mood": data.get("mood"), "energy": data.get("energy")}


def _extract_with_rules(query, hits, genres, moods):
    """Offline extraction: words in the request first, then the retrieved notes."""
    q = query.lower()
    prefs = {"genre": None, "mood": None, "energy": None}
    for g in sorted(genres, key=len, reverse=True):
        if re.search(rf"\b{re.escape(g.lower())}\b", q):
            prefs["genre"] = g
            break
    for m in sorted(moods, key=len, reverse=True):
        if re.search(rf"\b{re.escape(m.lower())}\b", q):
            prefs["mood"] = m
            break
    for hit in hits:  # the retrieved notes fill in whatever is still missing
        match = HINT_RE.search(hit["text"])
        if match:
            if prefs["genre"] is None:
                prefs["genre"] = match.group(1).strip()
            if prefs["mood"] is None:
                prefs["mood"] = match.group(2).strip()
            if prefs["energy"] is None:
                prefs["energy"] = float(match.group(3))
            break
    return prefs


def _clean_prefs(prefs, genres, moods):
    """Guardrail: only keep genres/moods that really exist in the catalog."""
    issues = []
    clean = {"genre": None, "mood": None, "energy": None}
    for field, allowed in (("genre", genres), ("mood", moods)):
        value = prefs.get(field)
        if value:
            match = next((a for a in allowed if a.lower() == str(value).strip().lower()), None)
            if match:
                clean[field] = match
            else:
                issues.append(f"{field} '{value}' is not in the catalog; ignored")
    energy = prefs.get("energy")
    if energy is not None:
        try:
            clean["energy"] = min(1.0, max(0.0, float(energy)))
        except (TypeError, ValueError):
            issues.append(f"energy '{energy}' is not a number; ignored")
    return clean, issues


# ---------- explanations (two styles: plain baseline and specialized DJ) ----------
def _template_explanation(prefs, recs, style):
    """Safe explanation built from a template (no AI needed)."""
    if not recs:
        return "No songs matched your request."
    titles = [r["title"] for r in recs]
    if style == "dj":
        names = titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " and " + titles[-1]
        return (
            f"DJ VibeFinder here: spinning {names} for your {prefs['mood']} "
            f"{prefs['genre']} mood at {energy_word(prefs['energy'])}.\n"
            f"Next up: {prefs['mood']}"
        )
    picks = "; ".join(f"{r['title']} by {r['artist']}" for r in recs)
    return (
        f"Recommended: {picks}. These match genre {prefs['genre']} and mood "
        f"{prefs['mood']} with {energy_word(prefs['energy'])}."
    )


def _llm_explanation(query, prefs, recs, style):
    song_lines = "\n".join(
        f"- {r['title']} by {r['artist']} ({r['genre']}, {r['mood']}, energy {r['energy']})"
        for r in recs
    )
    prompt = (
        f'Request: "{query}"\n'
        f"Understood as genre={prefs['genre']}, mood={prefs['mood']}, energy={prefs['energy']}.\n"
        f"Songs:\n{song_lines}\n"
        "Explain why these songs fit the request. Only mention songs from the list."
    )
    return ask_llm(prompt, system=DJ_SYSTEM if style == "dj" else PLAIN_SYSTEM)


def _make_explanation(query, prefs, recs, style, use_llm, log):
    if use_llm and recs:
        try:
            text = _llm_explanation(query, prefs, recs, style)
            log("LLM explain", f"{style} style, {len(text.split())} words")
            return text
        except Exception as err:
            log("FALLBACK", f"LLM explanation failed ({err}); using template")
    return _template_explanation(prefs, recs, style)


def _label(hit):
    if hit["kind"] == "song":
        return str(_get(hit["song"], "title", "?"))
    return hit["source"] + " > " + hit["text"].splitlines()[0].lstrip("# ").strip()


# ---------- the agent ----------
class VibeAgent:
    def __init__(self, use_llm=True, use_knowledge=True, style="dj", k=5):
        self.use_llm = use_llm and llm_available()
        self.use_knowledge = use_knowledge
        self.style = style
        self.k = k
        loader = _orig_load_songs or _fallback_load_songs
        try:
            self.songs = loader(str(SONGS_PATH))
        except Exception as err:
            logger.warning("original load_songs failed (%s); using backup loader", err)
            self.songs = _fallback_load_songs(str(SONGS_PATH))
        chunks = load_knowledge_chunks() if use_knowledge else []
        self.retriever = Retriever(self.songs, chunks)
        self.titles = [str(_get(s, "title", "")) for s in self.songs]
        self.genres = sorted({str(_get(s, "genre")) for s in self.songs if _get(s, "genre")})
        self.moods = sorted({str(_get(s, "mood")) for s in self.songs if _get(s, "mood")})
        self.common_genre = Counter(str(_get(s, "genre")) for s in self.songs).most_common(1)[0][0]
        self.common_mood = Counter(str(_get(s, "mood")) for s in self.songs).most_common(1)[0][0]
        self.engine = "original recommender (src/recommender.py)" if _orig_recommend else "built-in backup scorer"

    def run(self, query, style=None):
        """Run the full agent loop for one request and return a result dictionary."""
        style = style or self.style
        trace = []

        def log(step, detail):
            trace.append({"step": step, "detail": detail})
            logger.info("%s | %s", step, detail)

        result = {
            "query": query, "style": style, "valid": False, "message": "",
            "prefs": {}, "recs": [], "explanation": "", "confidence": 0.0,
            "retrieved": [], "notes_used": [], "trace": trace,
            "llm_used": self.use_llm, "engine": "",
        }

        # Step 1: plan
        log("PLAN", "validate, retrieve notes, extract preferences, repair gaps, "
                    "recommend, explain, self-check")

        # Step 2: input guardrail
        ok, message = validate_request(query)
        if not ok:
            log("GUARDRAIL", f"input rejected: {message}")
            result["message"] = message
            return result
        query = message
        result["query"] = query
        result["valid"] = True
        log("GUARDRAIL", "input accepted")

        # Step 3: tool call - retrieve knowledge (RAG)
        hits = self.retriever.search(query, top_k=3, kind="knowledge") if self.use_knowledge else []
        song_hits = self.retriever.search(query, top_k=3, kind="song")
        result["retrieved"] = hits
        result["notes_used"] = [_label(h) for h in hits]
        log("TOOL search_knowledge", f"{len(hits)} hits: " + (", ".join(result["notes_used"]) or "none"))

        # Step 4: extract preferences (Gemini if available, otherwise rules)
        prefs = None
        if self.use_llm:
            try:
                context = "\n\n".join(h["text"] for h in hits) or "(no notes found)"
                prefs = _extract_with_llm(query, context, self.genres, self.moods)
                log("LLM extract_preferences", json.dumps(prefs))
            except Exception as err:
                log("FALLBACK", f"LLM extraction failed ({err}); using rules instead")
        if prefs is None:
            prefs = _extract_with_rules(query, hits, self.genres, self.moods)
            log("RULES extract_preferences", json.dumps(prefs))

        # Step 5: guardrail - clean preferences against the real catalog
        prefs, issues = _clean_prefs(prefs, self.genres, self.moods)
        for issue in issues:
            log("GUARDRAIL", issue)
        found = sum(1 for v in prefs.values() if v is not None)
        confidence = round(0.6 * (found / 3) + (0.4 if hits else 0.0), 2)

        # Step 6: decision - repair missing fields with a second tool call
        if prefs["genre"] is None or prefs["mood"] is None:
            if song_hits:
                top = song_hits[0]["song"]
                if prefs["genre"] is None:
                    prefs["genre"] = str(_get(top, "genre"))
                if prefs["mood"] is None:
                    prefs["mood"] = str(_get(top, "mood"))
                log("TOOL search_songs", f"filled missing fields from closest song: {_get(top, 'title')}")
            else:
                prefs["genre"] = prefs["genre"] or self.common_genre
                prefs["mood"] = prefs["mood"] or self.common_mood
                log("DECISION", "nothing matched; using the most common genre and mood (low confidence)")
        if prefs["energy"] is None:
            prefs["energy"] = 0.5
            log("DECISION", "energy not clear; using neutral 0.5")
        result["prefs"] = prefs

        # Step 7: tool call - your original Module 3 recommender
        scorer_prefs = dict(prefs)
        scorer_prefs.update({  # extra key names in case your scorer uses different ones
            "favorite_genre": prefs["genre"], "favorite_mood": prefs["mood"],
            "target_energy": prefs["energy"],
        })
        engine = self.engine
        try:
            raw = (_orig_recommend or _fallback_recommend)(scorer_prefs, self.songs, self.k)
        except Exception as err:
            log("FALLBACK", f"original recommender failed ({err}); using backup scorer")
            engine = "built-in backup scorer"
            raw = _fallback_recommend(scorer_prefs, self.songs, self.k)
        recs = [_to_rec(item) for item in raw]
        result["recs"] = recs
        result["engine"] = engine
        log("TOOL recommend_songs", f"{engine} returned {len(recs)} songs")

        # Step 8: explain
        explanation = _make_explanation(query, prefs, recs, style, self.use_llm, log)

        # Step 9: self-check, and revise if it fails
        passed, problems = check_explanation(explanation, recs, self.titles, style)
        if passed:
            log("SELF-CHECK", "passed")
        else:
            log("SELF-CHECK", "failed: " + "; ".join(problems))
            explanation = _template_explanation(prefs, recs, style)
            passed2, _ = check_explanation(explanation, recs, self.titles, style)
            log("REVISION", "replaced explanation with safe template; " + ("now passes" if passed2 else "still failing"))
            confidence = max(0.0, round(confidence - 0.1, 2))

        result["explanation"] = explanation
        result["confidence"] = confidence
        log("DONE", f"confidence {confidence}")
        return result


def save_trace_markdown(result, path=None):
    """Append this run's reasoning trace to ai_interactions.md."""
    path = Path(path) if path else TRACE_FILE
    lines = []
    if not path.exists():
        lines.append("# AI Interaction Log\n\nEach section below is one run of the VibeFinder agent, "
                     "including every step it took.\n")
    lines.append(f"\n## Run {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    lines.append(f"- **Request:** {result['query']!r}")
    lines.append(f"- **Style:** {result['style']}  |  **Gemini used:** {result['llm_used']}")
    lines.append("\n**Reasoning trace**\n")
    for i, step in enumerate(result["trace"], 1):
        lines.append(f"{i}. `{step['step']}`: {step['detail']}")
    if result["recs"]:
        lines.append("\n**Final recommendations**\n")
        for r in result["recs"]:
            lines.append(f"- {r['title']} by {r['artist']} (score {r['score']})")
        lines.append(f"\n**Explanation:** {result['explanation']}")
        lines.append(f"\n**Confidence:** {result['confidence']}")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
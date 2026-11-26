"""Retrieval (the 'R' in RAG): finds the most relevant songs and notes for a request."""
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"

# Very common words that do not help us match anything
STOPWORDS = {
    "a", "an", "and", "the", "to", "for", "of", "in", "on", "with", "i", "me", "my",
    "some", "something", "want", "need", "music", "songs", "song", "please", "that",
    "is", "it", "at", "be", "like",
}


def tokenize(text):
    """Lowercase the text and split it into useful words."""
    words = re.findall(r"[a-z0-9']+", str(text).lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def energy_word(value):
    """Turn an energy number (0 to 1) into words."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "medium energy"
    if v >= 0.7:
        return "high energy"
    if v <= 0.4:
        return "low energy"
    return "medium energy"


def _get(item, key, default=""):
    """Read a field from a dict OR an object (works with either song style)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def song_to_text(song):
    """Describe one song as a sentence so it can be searched like a document."""
    return (
        f"{_get(song, 'title')} by {_get(song, 'artist')}. "
        f"genre {_get(song, 'genre')}. mood {_get(song, 'mood')}. "
        f"{energy_word(_get(song, 'energy', 0.5))}."
    )


def load_knowledge_chunks(folder=None):
    """Split every .md file in knowledge/ into chunks, one per '## ' section."""
    folder = Path(folder) if folder else KNOWLEDGE_DIR
    chunks = []
    if not folder.exists():
        return chunks
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for part in re.split(r"\n(?=## )", text):
            part = part.strip()
            if len(part) > 20 and part.startswith("## "):
                chunks.append({"source": path.name, "kind": "knowledge", "text": part})
    return chunks


class Retriever:
    """A small search engine over songs and knowledge notes (TF-IDF style scoring)."""

    def __init__(self, songs, knowledge_chunks):
        self.docs = []
        for song in songs:
            self.docs.append({"source": "songs.csv", "kind": "song",
                              "text": song_to_text(song), "song": song})
        self.docs.extend(knowledge_chunks)
        self.counts = [Counter(tokenize(d["text"])) for d in self.docs]
        # IDF: rare words count for more than words found in every document
        total = len(self.docs)
        doc_freq = Counter()
        for c in self.counts:
            doc_freq.update(c.keys())
        self.idf = {w: math.log((total + 1) / (n + 1)) + 1 for w, n in doc_freq.items()}

    def search(self, query, top_k=3, kind=None):
        """Return the best-matching documents (optionally only 'song' or 'knowledge')."""
        words = tokenize(query)
        scored = []
        for doc, counts in zip(self.docs, self.counts):
            if kind and doc["kind"] != kind:
                continue
            score = sum(self.idf.get(w, 0) * (1 + math.log(counts[w]))
                        for w in words if w in counts)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [dict(doc, score=round(score, 3)) for score, doc in scored[:top_k]]
"""Guardrails: safety checks that run before and after the AI does its work."""

MAX_LENGTH = 300  # longest request we accept
MIN_LENGTH = 3    # shortest request we accept

# Phrases people use to try to trick an AI into ignoring its rules
BLOCKED_PHRASES = [
    "ignore previous", "ignore all previous", "ignore your instructions",
    "system prompt", "api key", "password", "jailbreak",
]


def validate_request(text):
    """Input guardrail. Returns (ok, message).
    If ok is True, message is the cleaned text; if False, it explains why."""
    if not isinstance(text, str):
        return False, "Request must be text."
    cleaned = text.strip()
    if len(cleaned) < MIN_LENGTH:
        return False, "Request is empty or too short. Describe the vibe you want."
    if len(cleaned) > MAX_LENGTH:
        return False, f"Request is too long (max {MAX_LENGTH} characters)."
    if not any(ch.isalpha() for ch in cleaned):
        return False, "Request needs some words, not just numbers or symbols."
    lowered = cleaned.lower()
    for phrase in BLOCKED_PHRASES:
        if phrase in lowered:
            return False, "That looks like an attempt to change my rules, so I skipped it."
    return True, cleaned


def check_explanation(text, recs, catalog_titles, style):
    """Output guardrail / self-check. Returns (ok, list_of_problems).
    Makes sure the explanation only talks about songs we actually recommended."""
    problems = []
    lowered = text.lower()
    rec_titles = [r["title"].lower() for r in recs]
    if not text.strip():
        problems.append("explanation is empty")
    for title in catalog_titles:
        t = title.lower()
        # a catalog song that was NOT recommended but is mentioned = hallucination
        if len(t) > 3 and t in lowered and not any(t in rt for rt in rec_titles):
            problems.append(f"mentions a song we did not recommend: {title}")
    if recs and not any(t in lowered for t in rec_titles):
        problems.append("does not mention any recommended song")
    if style == "dj":
        if not text.startswith("DJ VibeFinder"):
            problems.append("DJ style must start with 'DJ VibeFinder'")
        if "Next up:" not in text:
            problems.append("DJ style must include 'Next up:'")
    return len(problems) == 0, problems
"""
Scripted tutor for demo mode.

Serves pre-written questions, hints, Socratic redirects and summaries from
demo_content.py and grades answers against each question's key points, so
the demo behaves like a live LLM tutor without an API key.

Every question handed out is returned as a dict ("qdata") that is stored on
the chat message, so grading and hints always refer to the exact question
the learner saw.
"""

import math
import re

try:
    from demo_content import CONCEPTS, BRIDGES
except ImportError:
    CONCEPTS, BRIDGES = {}, {}


def available(note):
    return note["title"] in CONCEPTS


def pick_question(note, level, related=None, asked_count=0):
    """Return qdata for the next question at this level.

    Level 3-4 with a related concept uses the bridge question for that pair,
    so the question genuinely exercises the connection being strengthened.
    """
    title = note["title"]
    if level >= 3 and related:
        key = tuple(sorted([title, related["title"]]))
        bridge = BRIDGES.get(key, {}).get(min(level, 4))
        if bridge:
            q = dict(bridge)
            q["related_title"] = related["title"]
            # Bridge ideas refer to the alphabetically-first concept
            if key[0] != title:
                q["idea"] = None
            return q
    bank = CONCEPTS[title]["questions"].get(min(max(level, 1), 4)) or CONCEPTS[title]["questions"][1]
    return dict(bank[asked_count % len(bank)])


def question_for_idea(note, idea_id, level=2, asked_count=0):
    """A question that targets one key idea, nearest to the learner's level."""
    concept = CONCEPTS[note["title"]]
    pool = []
    for lvl, qs in concept["questions"].items():
        for q in qs:
            if q.get("idea") == idea_id:
                pool.append((abs(int(lvl) - level), int(lvl), q))
    if concept.get("explain", {}).get("idea") == idea_id:
        pool.append((1, 2, concept["explain"]))
    if not pool:
        return None, level
    pool.sort(key=lambda t: t[0])
    best = [t for t in pool if t[0] == pool[0][0]]
    _, lvl, q = best[asked_count % len(best)]
    return dict(q), lvl


def explain_prompt(note):
    return dict(CONCEPTS[note["title"]]["explain"])


def summary(note):
    return CONCEPTS.get(note["title"], {}).get("summary", "")


def redirect(note, n=0):
    options = CONCEPTS[note["title"]]["redirects"]
    return options[n % len(options)]


_IDK = re.compile(r"^\s*(i\s*don'?t\s*know|idk|no\s*idea|not\s*sure|skip|pass|\?+)\s*[.!]*\s*$", re.I)


def is_question(text):
    """A learner asking instead of answering ("what is spacing?")."""
    t = text.strip().lower()
    if not t.endswith("?") or len(t.split()) > 18:
        return False
    return bool(re.match(r"^(what|why|how|can|could|is|are|does|do|explain|tell|which|when|where|who)\b", t))


def grade(answer, qdata, overlap=None):
    """Grade an answer against the question's key points.

    Returns the same shape as llm.evaluate_response, plus `missed`.
    """
    text = (answer or "").lower()
    points = qdata.get("points", [])
    hit = [p for p in points if any(term in text for term in p["terms"])]
    missed = [p for p in points if p not in hit]
    words = len(text.split())
    need = max(1, math.ceil(len(points) / 2))

    verbatim = bool(overlap and overlap.get("is_verbatim"))
    if _IDK.match(answer or ""):
        verdict = "incorrect"
    elif verbatim:
        verdict = "verbatim"
    elif len(hit) >= need and words >= 2:
        verdict = "correct"
    elif hit:
        verdict = "partial"
    else:
        verdict = "incorrect"

    feedback = _feedback(verdict, hit, missed, qdata)
    return {
        "correct": verdict == "correct",
        "partial": verdict == "partial",
        "verbatim": verbatim,
        "verdict": verdict,
        "feedback": feedback,
        "overlap": overlap,
        "missed": [p["point"] for p in missed],
    }


def _feedback(verdict, hit, missed, qdata):
    if verdict == "correct":
        if not missed:
            return "That's it. You covered every key point, in your own words."
        return "That's right. To round it out: " + missed[0]["point"]
    if verdict == "partial":
        lead = "You're on the right track."
        gaps = " ".join(p["point"] for p in missed[:2])
        return f"{lead} What's missing: {gaps}"
    if verdict == "verbatim":
        return ("This reads very close to your notes. Try saying it the way you'd explain it to a friend; "
                "putting it in your own words is what makes it stick.")
    if missed:
        return "Not quite. The key idea here: " + missed[0]["point"]
    return "Not quite. Take another look at what the question is asking."


def hint(qdata, level):
    hints = qdata.get("hints") or []
    if level <= len(hints):
        return hints[level - 1]
    return hints[-1] if hints else "What do you already remember about this?"


def reveal(qdata):
    return qdata.get("answer", "")

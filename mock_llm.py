"""
Placeholder responses for mock mode.

These produce content-aware, varied output keyed off the note title and a
hash of the inputs, so the demo chat feels alive without an API key. The
goal is plausibility, not accuracy — the strings should never claim to be
real LLM output.
"""

import hashlib


def _pick(seed_str, options):
    h = int(hashlib.sha1(seed_str.encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]


def _topic(note):
    return note.get("title", "this topic")


def _first_tag(note):
    tags = note.get("tags") or []
    return tags[0] if tags else "this area"


# ---------------------------------------------------------------------------
# Query / chat responses
# ---------------------------------------------------------------------------

def mock_rag_response(query, chunks, mode="direct"):
    titles = [c["note_title"] for c in chunks[:2]] if chunks else []
    src = ", ".join(f"'{t}'" for t in titles) or "your notes"
    if mode == "question":
        return (
            f"[Demo mode] Before I answer, try this: based on {src}, "
            f"how would you explain the core idea behind \"{query}\" in your own words?"
        )
    if mode == "hints":
        return (
            f"[Demo mode] Hint: think about how the ideas in {src} connect to "
            f"\"{query}\". Try to recall the key term before reading further."
        )
    return (
        f"[Demo mode] Drawing on {src}, here's a placeholder response to "
        f"\"{query}\". Set ANTHROPIC_API_KEY and toggle off mock mode to get a real answer."
    )


def mock_chat_response(note, history, user_msg, chunks, mode="auto"):
    topic = _topic(note)
    seed = f"{topic}|{user_msg}|{mode}"
    openers = [
        f"[Demo mode] Good thinking on {topic}.",
        f"[Demo mode] Interesting take on {topic}.",
        f"[Demo mode] Let's stay with {topic} for a moment.",
        f"[Demo mode] You're getting somewhere on {topic}.",
    ]
    if mode == "direct":
        body = (
            f"Here's a placeholder summary of {topic}: it's the kind of idea "
            f"where retrieval practice helps you connect parts you already know."
        )
    elif mode == "retrieval":
        body = (
            f"Without peeking, can you list the two or three key ideas from "
            f"{topic} and why they matter?"
        )
    elif mode == "hints":
        body = (
            f"Hint: think about how {_first_tag(note)} shows up inside {topic}. "
            f"What's the one piece you'd start with?"
        )
    else:  # auto
        body = (
            f"Try restating the main idea of {topic} in your own words, then "
            f"give one example where it would actually matter."
        )
    return f"{_pick(seed, openers)} {body}"


# ---------------------------------------------------------------------------
# Evaluation (returns dicts)
# ---------------------------------------------------------------------------

def mock_evaluate_response(user_answer, source_chunks, question, overlap_stats=None):
    # Heuristic: longer, non-trivial answers are treated as partially correct.
    text = (user_answer or "").strip()
    is_short = len(text) < 25
    correct = (not is_short) and (len(text.split()) >= 8)
    partial = (not correct) and (not is_short)
    verbatim = bool(overlap_stats and overlap_stats.get("is_verbatim"))
    if verbatim:
        correct = False
        feedback = "Looks close to the source — try rephrasing in your own words."
    elif correct:
        feedback = "Nice — you captured the main idea."
    elif partial:
        feedback = "You're partway there. A key piece is still missing."
    else:
        feedback = "Give it another try with a bit more detail."
    return {
        "correct": correct,
        "partial": partial,
        "verbatim": verbatim,
        "feedback": f"[Demo mode] {feedback}",
        "overlap": overlap_stats,
    }


def mock_evaluate_generation(user_explanation, source_chunks, prompt_text, overlap_stats=None):
    base = mock_evaluate_response(user_explanation, source_chunks, prompt_text, overlap_stats)
    words = len((user_explanation or "").split())
    if words < 20:
        depth = "shallow"
    elif words < 60:
        depth = "moderate"
    else:
        depth = "deep"
    base["depth"] = depth
    return base


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

def mock_level1_question(note, chunks):
    topic = _topic(note)
    tag = _first_tag(note)
    options = [
        f"True or false: {topic} is most closely associated with {tag}.",
        f"Fill in the blank: A core idea of {topic} is __________.",
        f"Which of these best describes {topic}? (A) the broad area, "
        f"(B) a specific technique, (C) a historical term, (D) none of these.",
    ]
    return f"[Demo mode] {_pick(topic, options)}"


def mock_level2_question(note, chunks):
    topic = _topic(note)
    options = [
        f"In your own words, explain the main idea of {topic}.",
        f"List the two or three key components of {topic} from memory.",
        f"Why does {topic} matter? Walk through your reasoning.",
    ]
    return f"[Demo mode] {_pick(topic + '-l2', options)}"


def mock_level3_question(note, chunks, related_notes=None):
    topic = _topic(note)
    related = related_notes[0]["title"] if related_notes else "another topic you've studied"
    options = [
        f"Imagine you're applying {topic} to a real-world scenario. "
        f"Describe the scenario and how you'd use the concept.",
        f"How does {topic} interact with {related}? Give a concrete example.",
        f"A system shows unexpected behavior in {_first_tag(note)}. "
        f"How would ideas from {topic} help you diagnose it?",
    ]
    return f"[Demo mode] {_pick(topic + '-l3', options)}"


def mock_level4_question(note, chunks, related_notes=None):
    topic = _topic(note)
    related = related_notes[0]["title"] if related_notes else "a related topic"
    options = [
        f"Combine ideas from {topic} and {related} to design something new. "
        f"Describe what it would look like and why it works.",
        f"Compare strengths and weaknesses of two approaches within {topic}. "
        f"Which would you choose, and under what conditions?",
        f"Critique {topic}: what are its likely failure modes, and how could "
        f"insights from {related} help address them?",
    ]
    return f"[Demo mode] {_pick(topic + '-l4', options)}"


def mock_generation_prompt(note, chunks):
    topic = _topic(note)
    return (
        f"[Demo mode] In your own words, explain the core idea behind {topic} "
        f"as if you were teaching a friend with no background in {_first_tag(note)}. "
        f"Use an analogy or concrete example if it helps."
    )


# ---------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------

def mock_hint_question(note, question_text, chunks, level, related_notes=None):
    tag = _first_tag(note)
    related = related_notes[0]["title"] if related_notes else "a related idea"
    if level == 1:
        return f"[Demo mode] Can you think of how {tag} connects to this question?"
    if level == 2:
        return (
            f"[Demo mode] What do you remember about {related}? "
            f"How might that help you here?"
        )
    # level 3
    return (
        f"[Demo mode] You're close — if part of the answer involves {tag}, "
        f"what's the specific term or step you'd fill in?"
    )


def mock_hint_reveal(note, question_text, chunks):
    topic = _topic(note)
    return (
        f"[Demo mode] Here's a placeholder reveal for the question on {topic}. "
        f"In a real run with an API key, this would be a full grounded answer "
        f"based on your notes."
    )

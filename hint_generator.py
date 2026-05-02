"""
Progressive hint generation with scaffolding logic and Socratic questioning.

Hint Levels:
  1 — Vague nudge (Socratic question referencing parent concept)
  2 — Conceptual pointer (Socratic question narrowing to related subtopic)
  3 — Near-answer (fill-in-the-blank style Socratic question)
  4 — Direct reveal (full answer with retrieved content)

Levels 1–3 produce Socratic questions to prevent passive hint-clicking.
Level 4 is a direct reveal.

Mastery-based starting level:
  Low mastery (< 0.3)   → start at Level 2 (skip vague nudge)
  Medium mastery (0.3–0.7) → start at Level 1
  High mastery (> 0.7)  → start at Level 1 (extra vague)
"""

from llm import _get_client, _format_chunks, MODEL, MAX_TOKENS
import mock_llm


# In-memory hint state per active question: { (note_id, question_index): HintState }
_hint_sessions = {}


class HintState:
    """Tracks hint progression for a single question."""

    def __init__(self, note, question_text, chunks, mastery, related_notes=None):
        self.note = note
        self.question_text = question_text
        self.chunks = chunks
        self.mastery = mastery
        self.related_notes = related_notes or []
        self.start_level = _get_start_level(mastery)
        self.current_level = self.start_level
        self.hints_given = []  # list of {level, text}
        self.hint_responses = []  # list of {level, response, similarity}

    def is_exhausted(self):
        """True if all hint levels have been shown (including L4 reveal)."""
        return self.current_level > 4

    def advance(self):
        """Move to the next hint level."""
        self.current_level = min(self.current_level + 1, 5)


def _get_start_level(mastery):
    """Determine starting hint level based on mastery."""
    if mastery < 0.3:
        return 2  # Low mastery: skip vague nudge, start at conceptual pointer
    return 1  # Medium and high mastery: start at Level 1


def get_hint_session(note_id, question_index):
    """Retrieve an existing hint session."""
    return _hint_sessions.get((note_id, question_index))


def create_hint_session(note_id, question_index, note, question_text, chunks,
                        mastery, related_notes=None):
    """Create a new hint session for a question."""
    state = HintState(note, question_text, chunks, mastery, related_notes)
    _hint_sessions[(note_id, question_index)] = state
    return state


def clear_hint_session(note_id, question_index):
    """Remove a hint session when the question is answered or skipped."""
    _hint_sessions.pop((note_id, question_index), None)


def generate_next_hint(hint_state):
    """Generate the next hint in the progression.

    Returns:
        dict with keys: level, text, is_question, is_reveal
    """
    if hint_state.is_exhausted():
        return None

    level = hint_state.current_level

    if level == 4:
        text = _generate_reveal(hint_state)
        result = {"level": 4, "text": text, "is_question": False, "is_reveal": True}
    else:
        text = _generate_socratic_hint(hint_state, level)
        result = {"level": level, "text": text, "is_question": True, "is_reveal": False}

    hint_state.hints_given.append({"level": level, "text": text})
    hint_state.advance()
    return result


def evaluate_hint_response(hint_state, user_response, level):
    """Evaluate a user's response to a Socratic hint question.

    Uses cosine similarity (embedding-based) for lightweight comparison
    without an API call.

    Returns:
        dict with keys: similarity, above_threshold, feedback
    """
    from rag import _get_model
    import numpy as np

    source_text = " ".join(c["text"] for c in hint_state.chunks)
    model = _get_model()

    embeddings = model.encode(
        [user_response, source_text],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    similarity = float(np.dot(embeddings[0], embeddings[1]))

    threshold = 0.4
    above_threshold = similarity >= threshold

    if above_threshold:
        feedback = "Good thinking! You're on the right track."
    else:
        feedback = "Not quite, but keep thinking about it."

    record = {"level": level, "response": user_response, "similarity": similarity}
    hint_state.hint_responses.append(record)

    return {
        "similarity": round(similarity, 3),
        "above_threshold": above_threshold,
        "feedback": feedback,
    }


def _build_graph_context(hint_state):
    """Build knowledge graph context (parent/sibling info) for hint prompts."""
    note = hint_state.note
    related = hint_state.related_notes

    parts = []
    if note.get("tags"):
        parts.append(f"Parent concepts/tags: {', '.join(note['tags'])}")
    if related:
        sibling_titles = [r["title"] for r in related[:3]]
        parts.append(f"Related topics (siblings): {', '.join(sibling_titles)}")
    return "\n".join(parts) if parts else "No related topics available."


def _generate_socratic_hint(hint_state, level):
    """Generate a Socratic question hint at the given level (1–3)."""
    client = _get_client()
    if client is None:
        # --- mock-mode branch (was: _fallback_hint, kept below for reference) ---
        # return _fallback_hint(hint_state, level)
        return mock_llm.mock_hint_question(
            hint_state.note, hint_state.question_text,
            hint_state.chunks, level, hint_state.related_notes,
        )

    context = _format_chunks(hint_state.chunks)
    graph_context = _build_graph_context(hint_state)
    tag_str = ", ".join(hint_state.note.get("tags", []))
    is_high_mastery = hint_state.mastery > 0.7

    level_instructions = {
        1: (
            "Generate a VERY vague Socratic question that nudges the user toward the answer. "
            "Reference the parent concept or broad topic area, but do NOT name the specific answer. "
            "Example format: 'Can you think of how [parent concept] relates to this?' "
            + ("Make this EXTRA vague — the user nearly knows this, so just a gentle nudge is enough. "
               "Don't even mention the specific subtopic." if is_high_mastery else
               "Give a general directional hint as a question.")
        ),
        2: (
            "Generate a Socratic question that narrows the scope to a related subtopic. "
            "Reference a sibling or related concept from the knowledge graph to help the user "
            "make a connection. "
            "Example format: 'What do you know about [related subtopic]? How might that help here?' "
            "The question should narrow the conceptual area but still require genuine recall."
        ),
        3: (
            "Generate a fill-in-the-blank style Socratic question that provides most of the "
            "context but leaves the critical detail missing. Paraphrase the relevant content "
            "but omit the key piece the user needs to recall. "
            "Example format: 'If [paraphrase of most of the answer], then what would the "
            "[missing piece] be?' "
            "The user should be able to fill in the gap with one key concept or detail."
        ),
    }

    previous_hints = ""
    if hint_state.hints_given:
        prev = "\n".join(f"- Level {h['level']}: {h['text']}" for h in hint_state.hints_given)
        previous_hints = f"\n\n## Previously Given Hints (do not repeat)\n{prev}"

    prompt = f"""## Original Question
{hint_state.question_text}

## Source Material
Title: {hint_state.note['title']}
Tags: {tag_str}

{context}

## Knowledge Graph Context
{graph_context}{previous_hints}

## Task
{level_instructions[level]}

IMPORTANT: Output ONLY the Socratic question, nothing else. Do not include the answer.
Do not include labels like "Hint:" or "Level:". Just output the question."""

    system = (
        "You are a hint generator for NoteSoFast, an adaptive tutoring system. "
        "Your job is to generate Socratic questions as progressive hints that guide "
        "the user toward the answer without revealing it directly. Each hint should be "
        "phrased as a thought-provoking question, not a declarative statement."
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        return _fallback_hint(hint_state, level)


def _generate_reveal(hint_state):
    """Generate a Level 4 direct reveal with the full answer."""
    client = _get_client()
    if client is None:
        # --- mock-mode branch (was: dump retrieved source text verbatim) ---
        # source_text = " ".join(c["text"] for c in hint_state.chunks)
        # return f"Here's the answer:\n\n{source_text}"
        return mock_llm.mock_hint_reveal(
            hint_state.note, hint_state.question_text, hint_state.chunks
        )

    context = _format_chunks(hint_state.chunks)

    prompt = f"""## Original Question
{hint_state.question_text}

## Source Material
{context}

## Task
Provide a clear, complete answer to the question above using the source material.
Be concise but thorough. This is the final reveal after the user has worked through
several hints, so give them the full picture.

Output ONLY the answer, nothing else."""

    system = (
        "You are a tutoring assistant for NoteSoFast. The user has worked through "
        "several hints and needs the full answer now. Provide a clear, direct answer."
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        source_text = " ".join(c["text"] for c in hint_state.chunks)
        return f"Here's the answer:\n\n{source_text}"


def _fallback_hint(hint_state, level):
    """Fallback hints when LLM is unavailable."""
    title = hint_state.note["title"]
    tags = hint_state.note.get("tags", [])
    related = hint_state.related_notes

    if level == 1:
        if tags:
            return f"Can you think of how the concept of '{tags[0]}' connects to this question?"
        return f"Think broadly about what you know about '{title}'. What comes to mind?"
    elif level == 2:
        if related:
            return (
                f"What do you know about '{related[0]['title']}'? "
                f"How might that relate to this question?"
            )
        return f"What are the key subtopics within '{title}' that might be relevant here?"
    else:  # level 3
        return (
            f"You're very close. Think about the specific details from '{title}' — "
            f"what's the one key piece you might be missing?"
        )

"""Simulated student driven by a weaker LLM (Claude Haiku).

Every call goes through the Budget — if the cap is hit the Budget raises
BudgetExceeded, which the simulator catches to terminate the session cleanly.

The student never calls the teacher's evaluator. It only produces answers.
"""

import os
import random
import time

from evaluation.budget import Budget


STUDENT_MODEL = "claude-haiku-4-5-20251001"
MAX_STUDENT_TOKENS = 400   # hard per-call output cap — short answers by design


_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _build_source_block(note: dict, chunks: list, access_level: str) -> str:
    """Build the 'study material' block visible to the student based on access level."""
    if access_level == "none":
        return f"Topic title: {note['title']}"
    if access_level == "summary":
        tags = ", ".join(note.get("tags", []))
        return (
            f"Topic title: {note['title']}\n"
            f"Tags: {tags}\n"
            f"(You remember this topic generally but do not have the notes in front of you.)"
        )
    # full access: the student has the note + retrieved chunks
    chunk_text = "\n\n".join(f"[{c.get('note_title','?')}] {c['text']}" for c in chunks)
    return (
        f"Topic title: {note['title']}\n"
        f"Full note content:\n{note.get('content','')}\n\n"
        f"Related retrieved passages:\n{chunk_text}"
    )


def generate_student_answer(
    profile: dict,
    note: dict,
    chunks: list,
    question: str,
    budget: Budget,
) -> dict:
    """Produce an answer in the student's voice.

    Returns a dict: {text, latency_ms, input_tokens, output_tokens, source}
      source is 'llm' on success, 'abandon' for an "I don't know" short-circuit,
      or 'fallback' if the client is unavailable / errored.

    Raises BudgetExceeded if the budget cap is hit before the call is made.
    """
    # Probabilistic abandon — models "I give up" without burning tokens.
    if random.random() < profile.get("abandon_rate", 0.0):
        return {
            "text": "I'm not sure — I don't remember this one.",
            "latency_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "source": "abandon",
        }

    # Check budget BEFORE the call
    budget.check()

    client = _get_client()
    if client is None:
        # No API key — return a deterministic stub so the harness still runs
        return {
            "text": f"(no LLM configured) I'd guess this is related to {note['title']}.",
            "latency_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "source": "fallback",
        }

    source_block = _build_source_block(note, chunks, profile["access_level"])
    system = profile["system_prompt"]
    user = (
        f"## Study material you have access to\n{source_block}\n\n"
        f"## Question from tutor\n{question}\n\n"
        f"Answer in-character as the student described. Do NOT answer as an AI assistant. "
        f"Keep the answer to a realistic student length."
    )

    t0 = time.monotonic()
    try:
        resp = client.messages.create(
            model=STUDENT_MODEL,
            max_tokens=MAX_STUDENT_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        text = resp.content[0].text.strip()
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        budget.record_call(in_tok, out_tok)
        return {
            "text": text,
            "latency_ms": latency_ms,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "source": "llm",
        }
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        # Still record a best-effort call so an error loop can't burn budget
        budget.record_call(0, 0)
        return {
            "text": f"(student LLM error: {type(e).__name__}) unsure.",
            "latency_ms": latency_ms,
            "input_tokens": 0,
            "output_tokens": 0,
            "source": "fallback",
        }


def should_request_hint(profile: dict, eval_result: dict) -> bool:
    """Decide whether the student asks for a hint on a missed question."""
    if eval_result.get("correct"):
        return False
    return random.random() < profile.get("hint_usage_rate", 0.0)

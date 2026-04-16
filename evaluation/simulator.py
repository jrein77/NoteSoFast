"""Orchestrates a simulated student <-> teacher session.

Unlike the Flask chat route, the simulator calls the pipeline functions directly
(question_gen, knowledge_trace, llm, hint_generator) so runs don't need a server
and can be reproducible. The same in-process `knowledge_state` is reset per
session so each student starts from the INITIAL_MASTERY prior.

Hard cutoffs live in evaluation/budget.py. Any cap breach raises BudgetExceeded
which the simulator catches to terminate cleanly and log the reason.
"""

import time
import traceback
import uuid

import knowledge_trace as kt
from hint_generator import (
    create_hint_session, clear_hint_session, generate_next_hint,
)
from llm import evaluate_response, evaluate_generation
from question_gen import generate_question, generate_generation_prompt
from similarity import compute_text_overlap

from evaluation.budget import Budget, BudgetExceeded
from evaluation.student import generate_student_answer, should_request_hint


# Per-session safety caps (defense in depth; eval-level Budget is the real limit)
MAX_TURNS_PER_SESSION = 25
MAX_HINTS_PER_QUESTION = 3


def _reset_note_state(note_id: str):
    """Clear any prior knowledge state for this note so the session starts fresh."""
    kt.knowledge_state.pop(note_id, None)


def _record_teacher_call_estimate(budget: Budget, input_chars: int, output_chars: int):
    """Approximate token usage for teacher LLM calls when exact usage isn't returned.

    The LLM helpers in llm.py don't surface token usage directly; we charge the
    budget with a conservative estimate (~4 chars/token) so the caps still bind.
    """
    in_tok = max(1, input_chars // 4)
    out_tok = max(1, output_chars // 4)
    budget.check()
    budget.record_call(in_tok, out_tok)


def _maybe_run_hint_flow(
    note, last_question, chunks, profile, eval_result, budget, logger,
    session_id, turn_idx
):
    """If the student wants a hint, walk through up to MAX_HINTS_PER_QUESTION levels.

    Each hint uses an internal budget check via record_call. If the hint flow
    exhausts or the budget trips, we return gracefully.
    """
    if not should_request_hint(profile, eval_result):
        return 0

    mastery = kt.get_decayed_mastery(note["id"])
    hint_state = create_hint_session(
        note["id"], turn_idx, note, last_question, chunks, mastery, related_notes=None
    )
    hints_used = 0
    try:
        for _ in range(MAX_HINTS_PER_QUESTION):
            if hint_state.is_exhausted():
                break
            budget.check()
            hint = generate_next_hint(hint_state)
            if hint is None:
                break
            _record_teacher_call_estimate(
                budget,
                input_chars=len(note.get("content", "")) + len(last_question),
                output_chars=len(hint.get("text", "")),
            )
            hints_used += 1
            logger.log(
                "hint",
                session_id=session_id,
                turn=turn_idx,
                level=hint.get("level"),
                is_question=hint.get("is_question"),
                is_reveal=hint.get("is_reveal"),
                text=hint.get("text", "")[:500],
            )
            if hint.get("is_reveal"):
                # Full reveal ends the hint flow
                break
    finally:
        clear_hint_session(note["id"], turn_idx)
    return hints_used


def run_session(
    profile_name: str,
    profile: dict,
    note: dict,
    rag_index,
    notes_by_id: dict,
    budget: Budget,
    logger,
    max_turns: int = MAX_TURNS_PER_SESSION,
) -> dict:
    """Run one student<->teacher session over a single note.

    Returns a summary dict. Logs every turn via the RunLogger.
    """
    session_id = uuid.uuid4().hex[:10]
    _reset_note_state(note["id"])

    # Pre-retrieve once; the system also re-queries per turn with user_msg — we
    # mimic that in the loop below.
    initial_chunks = rag_index.query(note["title"], top_k=5)

    logger.log(
        "session_start",
        session_id=session_id,
        profile=profile_name,
        note_id=note["id"],
        note_title=note["title"],
        note_tags=note.get("tags", []),
        initial_mastery=kt.get_decayed_mastery(note["id"]),
        budget_remaining_calls=budget.remaining_calls(),
    )

    turns = []
    termination = "completed"
    last_question = None

    try:
        for turn_idx in range(max_turns):
            # --- Determine difficulty + generate question -----------------
            difficulty_level = kt.get_recommended_difficulty(note["id"])
            mastery_before = kt.get_decayed_mastery(note["id"])

            # Teacher: generate question (or generation prompt every 3rd turn at L2+)
            use_generation = (
                difficulty_level >= 2 and turn_idx > 0 and turn_idx % 3 == 0
            )

            current_chunks = initial_chunks
            if turn_idx > 0:
                # Mirror app.py: re-query using the last student answer as the search key.
                prev = turns[-1]["student_answer"] if turns else note["title"]
                current_chunks = rag_index.query(prev or note["title"], top_k=5)

            budget.check()
            t0 = time.monotonic()
            if use_generation:
                question = generate_generation_prompt(note, current_chunks)
            else:
                # Related notes for L3/L4
                related = None
                if difficulty_level >= 3:
                    cur_tags = set(note.get("tags", []))
                    related = [
                        n for nid, n in notes_by_id.items()
                        if nid != note["id"] and cur_tags & set(n.get("tags", []))
                    ][:3]
                question = generate_question(note, current_chunks, difficulty_level, related)
            q_latency_ms = int((time.monotonic() - t0) * 1000)
            _record_teacher_call_estimate(
                budget,
                input_chars=len(note.get("content", "")) + sum(len(c["text"]) for c in current_chunks),
                output_chars=len(question),
            )
            last_question = question

            # --- Student answers ------------------------------------------
            student = generate_student_answer(
                profile=profile,
                note=note,
                chunks=current_chunks,
                question=question,
                budget=budget,
            )

            # --- Teacher evaluates ---------------------------------------
            source_text = " ".join(c["text"] for c in current_chunks)
            use_verbatim_detection = difficulty_level >= 3 or use_generation
            overlap = None
            if use_verbatim_detection and source_text.strip():
                overlap = compute_text_overlap(student["text"], source_text)

            budget.check()
            t0 = time.monotonic()
            if use_generation:
                eval_result = evaluate_generation(
                    student["text"], current_chunks, question, overlap
                )
            else:
                eval_result = evaluate_response(
                    student["text"], current_chunks, question, overlap
                )
            e_latency_ms = int((time.monotonic() - t0) * 1000)
            _record_teacher_call_estimate(
                budget,
                input_chars=len(student["text"]) + len(source_text) + len(question),
                output_chars=200,
            )

            if not use_verbatim_detection:
                eval_result["verbatim"] = False

            # --- Update mastery (mirror app.py logic) --------------------
            is_correct = eval_result["correct"]
            is_verbatim = eval_result.get("verbatim", False)
            if is_verbatim:
                kt.update_mastery(note["id"], difficulty_level, False)
            elif not is_correct and eval_result["partial"]:
                kt.update_mastery(note["id"], max(1, difficulty_level - 1), True)
            else:
                kt.update_mastery(note["id"], difficulty_level, is_correct)

            mastery_after = kt.get_decayed_mastery(note["id"])

            # --- Optional hint flow --------------------------------------
            hints_used = 0
            try:
                hints_used = _maybe_run_hint_flow(
                    note, question, current_chunks, profile, eval_result,
                    budget, logger, session_id, turn_idx,
                )
            except BudgetExceeded:
                raise
            except Exception:
                # Hints are best-effort — don't let a bug abort the session
                pass

            turn_record = {
                "turn": turn_idx,
                "difficulty_level": difficulty_level,
                "generation_mode": use_generation,
                "question": question,
                "student_answer": student["text"],
                "student_source": student["source"],
                "student_latency_ms": student["latency_ms"],
                "question_latency_ms": q_latency_ms,
                "eval_latency_ms": e_latency_ms,
                "correct": eval_result["correct"],
                "partial": eval_result["partial"],
                "verbatim": eval_result.get("verbatim", False),
                "feedback": eval_result.get("feedback", ""),
                "mastery_before": round(mastery_before, 4),
                "mastery_after": round(mastery_after, 4),
                "hints_used": hints_used,
                "overlap": overlap,
            }
            turns.append(turn_record)
            logger.log("interaction", session_id=session_id, **turn_record)

            # Terminate if the student has "mastered" the topic
            if mastery_after >= kt.MASTERY_THRESHOLD:
                termination = "mastered"
                break
    except BudgetExceeded as e:
        termination = f"budget_exceeded:{e.reason}"
    except Exception as e:
        termination = f"error:{type(e).__name__}:{e}"
        traceback.print_exc()

    summary = {
        "session_id": session_id,
        "profile": profile_name,
        "note_id": note["id"],
        "note_title": note["title"],
        "turns_completed": len(turns),
        "termination": termination,
        "final_mastery": round(kt.get_decayed_mastery(note["id"]), 4),
        "correct_count": sum(1 for t in turns if t["correct"]),
        "partial_count": sum(1 for t in turns if t["partial"] and not t["correct"]),
        "verbatim_count": sum(1 for t in turns if t["verbatim"]),
        "hints_total": sum(t["hints_used"] for t in turns),
        "difficulty_trajectory": [t["difficulty_level"] for t in turns],
        "mastery_trajectory": [t["mastery_after"] for t in turns],
    }
    logger.log("session_end", **summary)
    return summary

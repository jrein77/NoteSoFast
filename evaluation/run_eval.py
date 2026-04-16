"""CLI entry point for running simulated evaluations.

Example:
  python -m evaluation.run_eval --profiles novice,intermediate,expert,gaming \
      --notes 3 --max-turns 8 --max-api-calls 200

Hard budget caps prevent runaway token usage. Defaults are intentionally tight —
raise them with --max-* flags when you're ready to do a bigger run. Any cap hit
terminates the in-flight session and then the whole run.
"""

import argparse
import os
import random
import sys
from typing import Optional

# Allow `python evaluation/run_eval.py` as well as `python -m evaluation.run_eval`
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

# Import app late so .env is loaded and notes/rag_index are seeded.
from evaluation.budget import Budget, BudgetExceeded
from evaluation.logger import RunLogger
from evaluation.profiles import PROFILES, get_profile, profile_names
from evaluation.simulator import run_session


def _pick_notes(all_notes: dict, n: int, seed: Optional[int]) -> list:
    """Sample `n` notes deterministically when seed is set, else randomly."""
    ids = list(all_notes.keys())
    if seed is not None:
        rng = random.Random(seed)
        rng.shuffle(ids)
    else:
        random.shuffle(ids)
    return [all_notes[nid] for nid in ids[:n]]


def main():
    ap = argparse.ArgumentParser(
        description="Run simulated student<->teacher evaluations against NoteSoFast."
    )
    ap.add_argument(
        "--profiles", default=",".join(profile_names()),
        help=f"Comma-separated profile names. Known: {profile_names()}",
    )
    ap.add_argument("--notes", type=int, default=2, help="Notes per profile (default 2)")
    ap.add_argument("--max-turns", type=int, default=8, help="Max turns per session")
    ap.add_argument("--max-api-calls", type=int, default=200, help="Eval-wide API call cap")
    ap.add_argument("--max-input-tokens", type=int, default=300_000, help="Eval-wide input token cap")
    ap.add_argument("--max-output-tokens", type=int, default=80_000, help="Eval-wide output token cap")
    ap.add_argument("--max-wall-seconds", type=float, default=1200.0, help="Eval wall time cap")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible note sampling and profile RNG")
    ap.add_argument("--run-id", default=None, dest="run_id", help="Override the log file name")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan and the budget, but do not call any LLM.",
    )
    args = ap.parse_args()

    # Seed module-level RNG (for profile abandon_rate / hint_usage_rate coin flips)
    random.seed(args.seed)

    selected_profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    for p in selected_profiles:
        if p not in PROFILES:
            ap.error(f"unknown profile {p!r}; choose from {list(PROFILES)}")

    # Import app lazily so we don't spin up RAG/models on --help
    import app as _app  # noqa: F401  (side-effect: seeds notes, rebuilds RAG)

    notes_sample = _pick_notes(_app.notes, args.notes, args.seed)
    if not notes_sample:
        ap.error("No notes available in the app to evaluate against.")

    budget = Budget(
        max_api_calls=args.max_api_calls,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        max_wall_seconds=args.max_wall_seconds,
        scope="eval",
    )

    print("=" * 60)
    print("NoteSoFast — Simulated Evaluation")
    print("=" * 60)
    print(f"Profiles       : {selected_profiles}")
    print(f"Notes per prof : {args.notes}  ({[n['title'] for n in notes_sample]})")
    print(f"Max turns      : {args.max_turns}")
    print(f"Budget caps    : calls={args.max_api_calls}, in_tok={args.max_input_tokens}, "
          f"out_tok={args.max_output_tokens}, wall={args.max_wall_seconds}s")
    api_key_present = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"ANTHROPIC_API_KEY set: {api_key_present}")
    if not api_key_present:
        print("(No API key — the harness will run with stub responses.)")
    if args.dry_run:
        print("\nDry run: exiting before any LLM calls.")
        return

    logger = RunLogger(run_id=args.run_id)
    print(f"Log file       : {logger.path}\n")

    total_sessions = 0
    try:
        for profile_name in selected_profiles:
            profile = get_profile(profile_name)
            for note in notes_sample:
                print(f"--- session: {profile_name} / {note['title']} ---")
                summary = run_session(
                    profile_name=profile_name,
                    profile=profile,
                    note=note,
                    rag_index=_app.rag_index,
                    notes_by_id=_app.notes,
                    budget=budget,
                    logger=logger,
                    max_turns=args.max_turns,
                )
                total_sessions += 1
                print(
                    f"  turns={summary['turns_completed']} "
                    f"correct={summary['correct_count']} "
                    f"verbatim={summary['verbatim_count']} "
                    f"hints={summary['hints_total']} "
                    f"final_mastery={summary['final_mastery']} "
                    f"-> {summary['termination']}"
                )
                if budget.tripped:
                    print("  Budget tripped; aborting remaining sessions.")
                    raise BudgetExceeded("budget already tripped", "eval")
    except BudgetExceeded as e:
        print(f"\nHALTED: {e}")
    finally:
        logger.log("run_end", sessions=total_sessions, budget=budget.summary())
        logger.close()
        print("\n" + "=" * 60)
        print("Run complete")
        print(f"Sessions   : {total_sessions}")
        print(f"Budget     : {budget.summary()}")
        print(f"Log file   : {logger.path}")
        print("\nAnalyze with:")
        print(f"  python -m evaluation.analyze {logger.path}")


if __name__ == "__main__":
    main()

"""Offline analysis of JSONL interaction logs.

Reads a run file (or all files in logs/) and produces:
  - per-session summary rows (CSV + console table)
  - per-profile aggregates (accuracy, avg latency, avg final mastery, hint usage,
    verbatim rate, difficulty trajectory shape)
  - sanity-check flags (monotonic difficulty w/o plateau, zero-hint success, etc.)

Intentionally depends only on the stdlib so it runs anywhere the logs live.
"""

import argparse
import csv
import json
import os
import statistics
from collections import defaultdict
from typing import Optional

from evaluation.logger import DEFAULT_LOG_DIR, read_run


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_events(paths: list) -> list:
    events = []
    for p in paths:
        events.extend(read_run(p))
    return events


def _resolve_paths(target: Optional[str]) -> list:
    if target and os.path.isfile(target):
        return [target]
    base = target or DEFAULT_LOG_DIR
    if not os.path.isdir(base):
        return []
    return sorted(
        os.path.join(base, f) for f in os.listdir(base) if f.endswith(".jsonl")
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def sessions_from_events(events: list) -> list:
    """Reconstruct session dicts from flat event stream."""
    by_session = defaultdict(lambda: {"interactions": [], "hints": []})
    for ev in events:
        sid = ev.get("session_id")
        if not sid:
            continue
        kind = ev["kind"]
        if kind == "session_start":
            by_session[sid].update(ev)
        elif kind == "interaction":
            by_session[sid]["interactions"].append(ev)
        elif kind == "hint":
            by_session[sid]["hints"].append(ev)
        elif kind == "session_end":
            # Merge end fields last so they overwrite defaults
            for k, v in ev.items():
                if k not in ("kind", "ts"):
                    by_session[sid][k] = v
    return list(by_session.values())


def per_profile_summary(sessions: list) -> dict:
    """Aggregate metrics grouped by profile."""
    by_profile = defaultdict(list)
    for s in sessions:
        by_profile[s.get("profile", "unknown")].append(s)

    out = {}
    for profile, rows in by_profile.items():
        all_turns = [t for s in rows for t in s.get("interactions", [])]
        n_turns = len(all_turns)
        correct = [t for t in all_turns if t.get("correct")]
        verbatim = [t for t in all_turns if t.get("verbatim")]
        hints_total = sum(t.get("hints_used", 0) for t in all_turns)
        latencies_q = [t.get("question_latency_ms", 0) for t in all_turns]
        latencies_e = [t.get("eval_latency_ms", 0) for t in all_turns]
        latencies_s = [t.get("student_latency_ms", 0) for t in all_turns]
        finals = [s.get("final_mastery") for s in rows if s.get("final_mastery") is not None]
        difficulty_seqs = [
            [t["difficulty_level"] for t in s.get("interactions", [])]
            for s in rows
        ]

        out[profile] = {
            "sessions": len(rows),
            "turns_total": n_turns,
            "accuracy": round(len(correct) / n_turns, 3) if n_turns else None,
            "verbatim_rate": round(len(verbatim) / n_turns, 3) if n_turns else None,
            "hints_per_turn": round(hints_total / n_turns, 3) if n_turns else None,
            "avg_final_mastery": round(statistics.mean(finals), 3) if finals else None,
            "avg_question_latency_ms": round(statistics.mean(latencies_q), 1) if latencies_q else None,
            "avg_eval_latency_ms": round(statistics.mean(latencies_e), 1) if latencies_e else None,
            "avg_student_latency_ms": round(statistics.mean(latencies_s), 1) if latencies_s else None,
            "terminations": _count(s.get("termination") for s in rows),
            "difficulty_trajectories": difficulty_seqs,
        }
    return out


def _count(seq):
    counts = defaultdict(int)
    for x in seq:
        counts[x] += 1
    return dict(counts)


def _difficulty_shape(seq: list) -> str:
    """Classify a difficulty trajectory: rising, plateau, oscillating, stuck_low, stuck_high, empty."""
    if not seq:
        return "empty"
    if len(seq) == 1:
        return f"single_L{seq[0]}"
    max_level = max(seq)
    min_level = min(seq)
    if max_level == min_level:
        return f"flat_L{max_level}"
    diffs = [b - a for a, b in zip(seq, seq[1:])]
    ups = sum(1 for d in diffs if d > 0)
    downs = sum(1 for d in diffs if d < 0)
    if ups > 0 and downs == 0:
        return "rising"
    if downs > 0 and ups == 0:
        return "falling"
    if ups > 0 and downs > 0:
        return "oscillating"
    return "plateau"


def sanity_flags(sessions: list) -> list:
    """Heuristic flags for suspicious trajectories."""
    flags = []
    for s in sessions:
        seq = [t["difficulty_level"] for t in s.get("interactions", [])]
        shape = _difficulty_shape(seq)
        profile = s.get("profile")
        final = s.get("final_mastery")
        n = len(seq)

        # Novices should not reach mastery quickly
        if profile == "novice" and final and final >= 0.9 and n <= 5:
            flags.append({
                "session_id": s.get("session_id"),
                "profile": profile,
                "flag": "novice_fast_mastery",
                "detail": f"final={final}, turns={n}",
            })
        # Gaming profile should NOT be rewarded — flag high mastery
        if profile == "gaming" and final and final >= 0.8:
            flags.append({
                "session_id": s.get("session_id"),
                "profile": profile,
                "flag": "gaming_high_mastery",
                "detail": f"final={final}, verbatim rate ok? check turns",
            })
        # Experts should reach high mastery with few hints — flag the opposite
        if profile == "expert" and final is not None and final < 0.5:
            flags.append({
                "session_id": s.get("session_id"),
                "profile": profile,
                "flag": "expert_low_mastery",
                "detail": f"final={final}",
            })
        # System never raising difficulty when the student is answering correctly
        accs = [t.get("correct") for t in s.get("interactions", [])]
        if n >= 4 and sum(accs) >= n - 1 and shape.startswith(("flat", "plateau")):
            flags.append({
                "session_id": s.get("session_id"),
                "profile": profile,
                "flag": "plateau_despite_accuracy",
                "detail": f"shape={shape}, correct={sum(accs)}/{n}",
            })
    return flags


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_session_csv(sessions: list, out_path: str):
    fields = [
        "session_id", "profile", "note_title", "turns_completed",
        "correct_count", "partial_count", "verbatim_count",
        "hints_total", "final_mastery", "termination",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in sessions:
            w.writerow({k: s.get(k) for k in fields})


def print_profile_table(summary: dict):
    header = (
        f"{'profile':<14}{'sessions':>9}{'turns':>7}{'acc':>7}"
        f"{'verb':>7}{'hints/t':>9}{'final':>8}{'q ms':>8}{'ev ms':>8}{'st ms':>8}"
    )
    print(header)
    print("-" * len(header))
    for profile, row in summary.items():
        print(
            f"{profile:<14}"
            f"{row['sessions']:>9}"
            f"{row['turns_total']:>7}"
            f"{(row['accuracy'] if row['accuracy'] is not None else '-'):>7}"
            f"{(row['verbatim_rate'] if row['verbatim_rate'] is not None else '-'):>7}"
            f"{(row['hints_per_turn'] if row['hints_per_turn'] is not None else '-'):>9}"
            f"{(row['avg_final_mastery'] if row['avg_final_mastery'] is not None else '-'):>8}"
            f"{(row['avg_question_latency_ms'] if row['avg_question_latency_ms'] is not None else '-'):>8}"
            f"{(row['avg_eval_latency_ms'] if row['avg_eval_latency_ms'] is not None else '-'):>8}"
            f"{(row['avg_student_latency_ms'] if row['avg_student_latency_ms'] is not None else '-'):>8}"
        )


def print_flags(flags: list):
    if not flags:
        print("\nSanity flags: none")
        return
    print(f"\nSanity flags ({len(flags)}):")
    for f in flags:
        print(f"  [{f['flag']}] {f['profile']} / {f['session_id']}: {f['detail']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Analyze NoteSoFast simulated eval logs.")
    ap.add_argument("path", nargs="?", help="Path to a .jsonl file or logs dir (default: evaluation/logs)")
    ap.add_argument("--csv", help="Write per-session CSV to this path")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    args = ap.parse_args()

    paths = _resolve_paths(args.path)
    if not paths:
        print(f"No log files found at {args.path or DEFAULT_LOG_DIR}")
        return
    print(f"Loaded {len(paths)} log file(s).")

    events = load_events(paths)
    sessions = sessions_from_events(events)
    summary = per_profile_summary(sessions)
    flags = sanity_flags(sessions)

    if args.json:
        print(json.dumps({
            "n_sessions": len(sessions),
            "profiles": summary,
            "flags": flags,
        }, indent=2))
    else:
        print(f"\n== Per-profile summary ({len(sessions)} sessions) ==\n")
        print_profile_table(summary)
        print_flags(flags)

    if args.csv:
        write_session_csv(sessions, args.csv)
        print(f"\nWrote CSV: {args.csv}")


if __name__ == "__main__":
    main()

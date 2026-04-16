"""Simulated student-teacher evaluation harness for NoteSoFast.

Modules:
  budget    — hard cutoffs on API calls, tokens, and wall time to prevent runaway usage
  profiles  — learner personas (novice, intermediate, expert, gaming)
  student   — simulated student driven by a weaker LLM (Haiku)
  logger    — JSONL interaction logs + session metadata
  simulator — orchestrates a full session: question -> student answer -> eval -> update
  analyze   — aggregates logs into per-profile and per-session summary stats
"""

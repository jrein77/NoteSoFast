"""
Knowledge tracing module: per-topic mastery estimation with Bayesian-style updates,
time-aware forgetting, few-shot initialization, and adaptive difficulty routing.
"""

from datetime import datetime
import math

# --- Constants (informed by literature) ---

MASTERY_THRESHOLD = 0.95       # Zhang et al., 2025 — BKT mastery threshold
INITIAL_MASTERY = 0.3          # Prior for uninitialized topics
FORGETTING_RATE = 0.1          # Exponential decay rate per day
FEW_SHOT_WINDOW = 3            # Number of interactions before initialization is complete

# How much each difficulty level moves mastery on correct/incorrect answers
LEVEL_WEIGHTS = {1: 0.10, 2: 0.20, 3: 0.35, 4: 0.35}

# Overconfidence penalty multiplier (Dunning-Kruger signal)
OVERCONFIDENCE_PENALTY = 1.5

# --- In-memory store ---

knowledge_state = {}  # note_id -> state dict


def _default_state():
    """Create a default knowledge state for a new topic."""
    return {
        "mastery": INITIAL_MASTERY,
        "interactions": [],
        "last_session": None,
        "initialized": False,
    }


def get_mastery(note_id):
    """Return the current knowledge state for a note, creating a default if new."""
    if note_id not in knowledge_state:
        knowledge_state[note_id] = _default_state()
    return knowledge_state[note_id]


def apply_time_decay(note_id):
    """Apply exponential forgetting based on time since last interaction.

    Decay formula: mastery *= e^(-FORGETTING_RATE * days_elapsed)
    Only applied if there was a previous session.
    """
    state = get_mastery(note_id)
    if state["last_session"] is None:
        return

    days_elapsed = (datetime.now() - state["last_session"]).total_seconds() / 86400.0
    if days_elapsed < 0.01:  # Less than ~15 minutes, skip decay
        return

    decay = math.exp(-FORGETTING_RATE * days_elapsed)
    old_mastery = state["mastery"]
    # Decay toward INITIAL_MASTERY rather than zero (floor effect)
    state["mastery"] = INITIAL_MASTERY + (old_mastery - INITIAL_MASTERY) * decay


def update_mastery(note_id, difficulty_level, correct, confidence=None):
    """Update mastery estimate after an interaction.

    Uses a weighted Bayesian-style update where higher difficulty levels
    produce larger mastery changes. Detects overconfidence (confident but wrong)
    and applies a larger penalty.

    Args:
        note_id: The note being studied
        difficulty_level: 1–4 (cued recall → synthesis)
        correct: Whether the user's answer was correct
        confidence: Optional float 0–1 representing user confidence
    """
    state = get_mastery(note_id)
    weight = LEVEL_WEIGHTS.get(difficulty_level, 0.1)

    if correct:
        # Move mastery toward 1.0, scaled by difficulty weight
        state["mastery"] += weight * (1.0 - state["mastery"])
    else:
        penalty = weight
        # Overconfidence: user was confident but wrong → larger penalty
        if confidence is not None and confidence > 0.7:
            penalty *= OVERCONFIDENCE_PENALTY
        state["mastery"] -= penalty * state["mastery"]

    # Clamp to [0, 1]
    state["mastery"] = max(0.0, min(1.0, state["mastery"]))

    # Record interaction
    state["interactions"].append({
        "timestamp": datetime.now(),
        "difficulty_level": difficulty_level,
        "correct": correct,
        "confidence": confidence,
    })

    state["last_session"] = datetime.now()

    # Check if few-shot initialization window is complete
    if not state["initialized"] and len(state["interactions"]) >= FEW_SHOT_WINDOW:
        state["initialized"] = True


def get_recommended_difficulty(note_id):
    """Return the recommended difficulty level (1–4) based on mastery and session gap.

    After a long gap (time decay applied), starts easier before ramping up.
    During normal sessions, difficulty tracks mastery:
      mastery < 0.3  → Level 1 (cued recall)
      mastery < 0.6  → Level 2 (free recall)
      mastery < 0.85 → Level 3 (application)
      mastery >= 0.85 → Level 4 (synthesis)
    """
    state = get_mastery(note_id)
    mastery = state["mastery"]

    # If returning after a gap and last interaction was at a higher level,
    # start one level lower (Huang et al., 2026 time-awareness)
    if state["last_session"] is not None:
        days_elapsed = (datetime.now() - state["last_session"]).total_seconds() / 86400.0
        if days_elapsed > 1.0 and state["interactions"]:
            last_level = state["interactions"][-1]["difficulty_level"]
            # Drop one level on return after >1 day gap
            return max(1, last_level - 1)

    if mastery < 0.3:
        return 1
    elif mastery < 0.6:
        return 2
    elif mastery < 0.85:
        return 3
    else:
        return 4


def get_response_mode(note_id):
    """Determine the response mode based on mastery state.

    Returns:
        "direct" if mastery >= threshold (user has mastered the topic)
        "question" otherwise (challenge with retrieval practice)
    """
    state = get_mastery(note_id)

    if state["mastery"] >= MASTERY_THRESHOLD:
        return "direct"
    return "question"


def mastery_to_label(mastery_float):
    """Convert a numeric mastery value to the legacy UI label.

    green    >= 0.95 (mastered)
    yellow   >= 0.4  (progressing)
    red      >= 0.1  (struggling)
    not_started < 0.1
    """
    if mastery_float >= 0.95:
        return "green"
    elif mastery_float >= 0.4:
        return "yellow"
    elif mastery_float >= 0.1:
        return "red"
    else:
        return "not_started"

"""
Connection strength between topics: the edges of the knowledge graph.

Each edge behaves like a synapse. It only strengthens when the learner
actively retrieves both ideas together (a cross-concept / interleaving
question), and it fades over time if left alone.

Model (a simplified spaced-repetition memory model applied to edges):
  current_strength = peak * 0.5 ** (days_since_review / half_life)

  correct review   -> peak moves toward 1.0, half_life grows
                      (grows more when the review was spaced out: the
                       spacing effect, i.e. retrieving a partly faded
                       memory strengthens it more than cramming)
  incorrect review -> peak drops, half_life shrinks (a lapse)

So a connection reviewed several times over weeks becomes thick AND
durable, while one crammed once fades within days.
"""

import math
import clock

BASE_HALF_LIFE_DAYS = 2.0
MAX_HALF_LIFE_DAYS = 120.0
LEARN_RATE = 0.4          # how far peak strength moves toward 1.0 on a correct review
LAPSE_STRENGTH = 0.35     # fraction of strength lost on an incorrect review
LAPSE_HALF_LIFE = 0.6     # half-life multiplier on an incorrect review

connection_state = {}  # "idA|idB" (sorted) -> state dict


def edge_key(a, b):
    return "|".join(sorted([a, b]))


def _days_since(moment):
    if moment is None:
        return None
    return max(0.0, (clock.now() - moment).total_seconds() / 86400.0)


def current_strength(a, b):
    state = connection_state.get(edge_key(a, b))
    if not state or state["last_review"] is None:
        return 0.0
    days = _days_since(state["last_review"])
    return state["peak"] * (0.5 ** (days / state["half_life"]))


def reinforce(a, b, correct, weight=1.0):
    """Record a retrieval that exercised the a<->b connection.

    weight < 1 for partial credit. Returns before/after strength so the UI
    can animate the change.
    """
    key = edge_key(a, b)
    state = connection_state.get(key)
    if state is None:
        state = {"peak": 0.0, "half_life": BASE_HALF_LIFE_DAYS,
                 "last_review": None, "reviews": []}
        connection_state[key] = state

    before = current_strength(a, b)
    days_since = _days_since(state["last_review"])

    if correct:
        if state["last_review"] is not None:
            # Spacing bonus: 0.5x when reviewed immediately, up to 1.5x when the
            # connection had decayed to half strength or further.
            spacing = 0.5 + min(1.0, days_since / state["half_life"])
            growth = 1.0 + 0.8 * weight * spacing
            state["half_life"] = min(MAX_HALF_LIFE_DAYS, state["half_life"] * growth)
        state["peak"] = before + LEARN_RATE * weight * (1.0 - before)
    else:
        state["half_life"] = max(1.0, state["half_life"] * LAPSE_HALF_LIFE)
        state["peak"] = before * (1.0 - LAPSE_STRENGTH * weight)

    state["last_review"] = clock.now()
    state["reviews"].append({"timestamp": clock.now(), "correct": bool(correct)})

    return {"source": a, "target": b, "before": round(before, 3),
            "after": round(current_strength(a, b), 3), "correct": bool(correct)}


def edge_info(a, b):
    """Display data for one edge."""
    state = connection_state.get(edge_key(a, b))
    if not state or state["last_review"] is None:
        return {"strength": 0.0, "review_count": 0, "half_life": None,
                "days_since": None, "days_to_fade": None}
    strength = current_strength(a, b)
    # Days until it drops below the "fading" threshold of 0.25
    days_to_fade = None
    if strength > 0.25:
        days_to_fade = round(state["half_life"] * math.log2(strength / 0.25), 1)
    return {
        "strength": round(strength, 3),
        "review_count": len(state["reviews"]),
        "half_life": round(state["half_life"], 1),
        "days_since": round(_days_since(state["last_review"]), 1),
        "days_to_fade": days_to_fade,
    }


def reviewed_pairs():
    return [tuple(k.split("|")) for k, s in connection_state.items() if s["reviews"]]


def remove_node(note_id):
    for key in [k for k in connection_state if note_id in k.split("|")]:
        connection_state.pop(key, None)

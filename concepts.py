"""
Concept hierarchy for the zoomable map:

    group (domain)  ->  concept (a note)  ->  key ideas (sub-concepts)

Groups come from the note's "group" field. Key ideas come from the scripted
demo content when available, otherwise they are parsed from the note's
bullet points so user-created notes still get a sub-concept view.
"""

import hashlib
import re

from demo_seed import GROUPS

try:
    from demo_content import CONCEPTS
except ImportError:  # content file not generated yet
    CONCEPTS = {}

_EXTRA_COLORS = ["#fbbf24", "#38bdf8", "#fb923c", "#4ade80", "#e879f9", "#f87171"]


def _hash(text):
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest(), 16)


def group_of(note):
    if note.get("group"):
        return note["group"]
    tags = note.get("tags") or []
    return tags[0].replace("-", " ").title() if tags else "Unsorted"


def group_color(name):
    return GROUPS.get(name) or _EXTRA_COLORS[_hash(name) % len(_EXTRA_COLORS)]


def group_id(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def key_ideas(note):
    scripted = CONCEPTS.get(note["title"], {}).get("key_ideas")
    if scripted:
        return [{"id": k["id"], "label": k["label"], "summary": k.get("summary", "")} for k in scripted]
    ideas = []
    for line in note.get("content", "").splitlines():
        m = re.match(r"\s*(?:[-*•]|\d+[.)])\s+(.*)", line)
        if not m:
            continue
        text = m.group(1).strip()
        label = re.split(r"[:(—-]", text)[0].strip() or text
        words = label.split()
        label = " ".join(words[:4]) + ("…" if len(words) > 4 else "")
        ideas.append({"id": group_id(label)[:40] or f"idea-{len(ideas)}", "label": label, "summary": text})
    return ideas[:6]


def idea_links(note, ideas):
    scripted = CONCEPTS.get(note["title"], {}).get("idea_links")
    if scripted:
        return [list(p) for p in scripted]
    ids = [i["id"] for i in ideas]
    return [[ids[i], ids[i + 1]] for i in range(len(ids) - 1)]


def idea_strengths(note_id, ideas, mastery, studied, idea_hits):
    """Per-idea strength: the concept's memory strength, varied per idea and
    nudged by how the learner has done on questions targeting that idea."""
    out = {}
    for idea in ideas:
        if not studied:
            out[idea["id"]] = 0.0
            continue
        factor = 0.78 + (_hash(note_id + idea["id"]) % 36) / 100.0   # 0.78 .. 1.13
        hits = idea_hits.get(idea["id"], [])
        bonus = 0.1 * sum(1 if h else -1 for h in hits[-4:])
        out[idea["id"]] = round(max(0.05, min(1.0, mastery * factor + bonus)), 3)
    return out


def idea_label(strength, studied):
    if not studied:
        return "not_started"
    if strength >= 0.85:
        return "green"
    if strength >= 0.5:
        return "yellow"
    return "red"

import os as _os
from dotenv import load_dotenv
load_dotenv(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env"), override=True)

from flask import Flask, render_template, request, redirect, url_for, jsonify
import re
import uuid
from datetime import datetime
import json

from similarity import find_similar_pairs, compute_text_overlap, extract_redaction_targets
from rag import RAGIndex
from llm import (
    generate_rag_response, generate_chat_response,
    evaluate_response, evaluate_generation,
)
from knowledge_trace import (
    get_mastery, apply_time_decay, update_mastery,
    get_recommended_difficulty, get_response_mode,
    knowledge_state, get_decayed_mastery, node_label,
)
from question_gen import generate_question, generate_generation_prompt
from hint_generator import (
    get_hint_session, create_hint_session, clear_hint_session,
    generate_next_hint, evaluate_hint_response,
)
from cognitive_debt import CognitiveDebtTracker
from connections import (
    connection_state, reinforce, current_strength, edge_info, reviewed_pairs,
    remove_node as remove_connections,
)
import clock
import concepts
import demo_seed
import store
import mock_mode
import scripted

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # always revalidate static files during development


@app.context_processor
def inject_mock_mode():
    """Make the current mock-mode state available to every template."""
    return {
        "mock_mode_active": mock_mode.is_mock(),
        "mock_has_api_key": mock_mode.has_api_key(),
    }


@app.route("/api/mock-mode", methods=["GET", "POST"])
def api_mock_mode():
    """Read or toggle mock mode.

    POST body: {"mock": true|false}. Switching to API mode requires
    ANTHROPIC_API_KEY to be set in the environment.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        wanted = bool(data.get("mock", True))
        if not wanted and not mock_mode.has_api_key():
            return jsonify({
                "error": "ANTHROPIC_API_KEY is not set; cannot switch to API mode.",
                "mock": True,
                "has_api_key": False,
            }), 400
        mock_mode.set_mock(wanted)
    return jsonify({
        "mock": mock_mode.is_mock(),
        "has_api_key": mock_mode.has_api_key(),
    })

# RAG index (initialized after seed notes are loaded)
rag_index = RAGIndex()

# Cognitive debt tracker
debt_tracker = CognitiveDebtTracker()

# In-memory working state, persisted to data/state.json after every POST
notes = {}
tags = set()
chat_messages = {}  # { note_id: [ {"role": "user"|"ai", "content": str, ...} ] }
level_choice = {}   # { note_id: 1-4 } level the learner picked; absent = follow the recommendation


def _persist():
    store.save({
        "notes": notes,
        "chat_messages": chat_messages,
        "knowledge_state": knowledge_state,
        "connection_state": connection_state,
        "debt_nodes": debt_tracker._nodes,
        "level_choice": level_choice,
        "clock_offset_days": clock.get_offset_days(),
    })


def _reset_state():
    for d in (notes, chat_messages, knowledge_state, connection_state, debt_tracker._nodes, level_choice):
        d.clear()
    tags.clear()


def _load_or_seed(force_seed=False):
    _reset_state()
    saved = None if force_seed else store.load()
    if saved:
        notes.update(saved["notes"])
        chat_messages.update(saved["chat_messages"])
        knowledge_state.update(saved["knowledge_state"])
        connection_state.update(saved["connection_state"])
        debt_tracker._nodes.update(saved["debt_nodes"])
        level_choice.update(saved.get("level_choice", {}))
        clock.set_offset_days(saved.get("clock_offset_days", 0))
        for n in notes.values():
            tags.update(n.get("tags", []))
    else:
        clock.set_offset_days(0)
        demo_seed.seed(notes, tags, debt_tracker)
        _persist()
    rag_index.rebuild(notes)


_load_or_seed()


@app.after_request
def _save_after_mutation(response):
    if request.method == "POST" and response.status_code < 400:
        _persist()
    return response


def pick_related(note_id, level):
    """Choose related topics for a cross-concept (L3/L4) question.

    Targets the weakest links first: neighbours the learner has studied but
    whose connection to this note is weakest or most decayed. This is what
    makes review actively rebuild fading connections instead of re-drilling
    strong ones.
    """
    if level < 3:
        return []
    note = notes[note_id]
    current_tags = set(note.get("tags", []))
    connected = {b if a == note_id else a for a, b in reviewed_pairs() if note_id in (a, b)}
    candidates = [
        n for nid, n in notes.items()
        if nid != note_id and (current_tags & set(n.get("tags", [])) or nid in connected)
    ]
    candidates.sort(key=lambda n: (
        not get_mastery(n["id"])["interactions"],   # studied topics first
        current_strength(note_id, n["id"]),          # weakest connection first
    ))
    # One partner per question, so each answer maps to exactly one connection
    return candidates[:1]


@app.route("/")
def index():
    debt_count = debt_tracker.get_debt_count(notes)
    return render_template("index.html", debt_count=debt_count)


def _mastery_at_real_now(note_id):
    if not clock.get_offset_days():
        return get_decayed_mastery(note_id)
    with clock.frozen_at(datetime.now()):
        return get_decayed_mastery(note_id)


def _node_payload(note):
    nid = note["id"]
    state = get_mastery(nid)
    note["mastery"] = node_label(nid)
    last = state["last_session"]
    mastery = get_decayed_mastery(nid)
    studied = bool(state["interactions"])
    group = concepts.group_of(note)
    ideas = concepts.key_ideas(note)
    strengths = concepts.idea_strengths(nid, ideas, mastery, studied, state.get("idea_hits", {}))
    for idea in ideas:
        idea["strength"] = strengths[idea["id"]]
        idea["mastery"] = concepts.idea_label(idea["strength"], studied)
    return {
        "id": nid,
        "title": note["title"],
        "mastery": note["mastery"],
        "mastery_value": round(mastery, 3),
        # Strength at the real present, so time travel can show how far it has dropped
        "mastery_now": round(_mastery_at_real_now(nid), 3),
        "review_count": len(state["interactions"]),
        "days_since": round(max(0.0, (clock.now() - last).total_seconds() / 86400), 1) if last else None,
        "tags": note["tags"],
        "group": group,
        "group_id": concepts.group_id(group),
        "ideas": ideas,
        "idea_links": concepts.idea_links(note, ideas),
    }


def _group_summaries(node_list=None):
    """Per-group stats for the map's top level and the sidebar."""
    node_list = node_list or [_node_payload(n) for n in notes.values()]
    groups = {}
    for n in node_list:
        g = groups.setdefault(n["group_id"], {
            "id": n["group_id"], "name": n["group"], "color": concepts.group_color(n["group"]),
            "concept_ids": [], "studied": 0, "strength_sum": 0.0,
        })
        g["concept_ids"].append(n["id"])
        if n["mastery"] != "not_started":
            g["studied"] += 1
            g["strength_sum"] += n["mastery_value"]
    for g in groups.values():
        g["strength"] = round(g["strength_sum"] / g["studied"], 3) if g["studied"] else 0.0
        del g["strength_sum"]
    return sorted(groups.values(), key=lambda g: g["name"])


def _due_concepts(node_list=None):
    """Concepts worth reviewing now: never practiced, or memory has faded."""
    node_list = node_list or [_node_payload(n) for n in notes.values()]
    due = [n for n in node_list if n["mastery"] == "not_started" or n["mastery_value"] < 0.75]
    return sorted(due, key=lambda n: (n["mastery"] != "not_started", n["mastery_value"]))


def _study_stats():
    days = set()
    today_count = 0
    today = clock.now().date()
    for state in knowledge_state.values():
        for i in state["interactions"]:
            d = i["timestamp"].date()
            days.add(d)
            if d == today:
                today_count += 1
    streak = 0
    cursor = today
    if cursor not in days:
        cursor = cursor.fromordinal(cursor.toordinal() - 1)
    while cursor in days:
        streak += 1
        cursor = cursor.fromordinal(cursor.toordinal() - 1)
    return {"streak": streak, "reviews_today": today_count, "daily_goal": 10}


@app.context_processor
def inject_sidebar():
    if request.args.get("embed") == "1" or request.path.startswith("/api/"):
        return {}
    node_list = [_node_payload(n) for n in notes.values()]
    return {
        "sidebar_groups": _group_summaries(node_list),
        "due_count": len(_due_concepts(node_list)),
        "study_stats": _study_stats(),
        "clock_offset_days": clock.get_offset_days(),
    }


@app.route("/api/graph-data")
def graph_data():
    """Nodes (memory strength), edges (connection strength), suggested links, clusters.

    Edges are every pair that shares a tag (a pathway that *could* form) plus
    every pair the learner has actually practiced together. Edge strength
    comes from the connection model: it grows only through cross-concept
    retrieval and decays over time.
    """
    node_list = [_node_payload(n) for n in notes.values()]

    pairs = {}
    note_vals = list(notes.values())
    for i in range(len(note_vals)):
        for j in range(i + 1, len(note_vals)):
            shared = set(note_vals[i]["tags"]) & set(note_vals[j]["tags"])
            if shared:
                pairs[tuple(sorted([note_vals[i]["id"], note_vals[j]["id"]]))] = sorted(shared)
    for a, b in reviewed_pairs():
        if a in notes and b in notes:
            pairs.setdefault(tuple(sorted([a, b])), [])

    edges = []
    for (a, b), shared in pairs.items():
        info = edge_info(a, b)
        edges.append({"source": a, "target": b, "shared_tags": shared, **info})

    potential = []
    try:
        for id1, id2, score in find_similar_pairs(notes, threshold=0.15):
            if tuple(sorted([id1, id2])) not in pairs:
                potential.append({"source": id1, "target": id2, "similarity": round(score, 3)})
    except Exception:
        pass  # Graceful fallback if similarity computation fails

    groups = _group_summaries(node_list)
    group_by_node = {n["id"]: n["group_id"] for n in node_list}
    group_links = {}
    for e in edges:
        ga, gb = group_by_node[e["source"]], group_by_node[e["target"]]
        if ga == gb:
            continue
        key = tuple(sorted([ga, gb]))
        link = group_links.setdefault(key, {"source": key[0], "target": key[1], "count": 0, "strength": 0.0})
        link["count"] += 1
        link["strength"] = max(link["strength"], e["strength"])

    return jsonify({
        "nodes": node_list,
        "edges": edges,
        "potential_connections": potential,
        "groups": groups,
        "group_links": list(group_links.values()),
        "clock_offset_days": clock.get_offset_days(),
    })



@app.route("/api/clock", methods=["GET", "POST"])
def api_clock():
    """Read or set the simulated time offset (time-travel slider)."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        clock.set_offset_days(data.get("offset_days", 0))
    return jsonify({"offset_days": clock.get_offset_days()})


@app.route("/api/demo/reset", methods=["POST"])
def api_demo_reset():
    """Wipe all state and re-seed the demo history (for recording fresh takes)."""
    _load_or_seed(force_seed=True)
    return jsonify({"ok": True})


@app.route("/notes")
def notes_list():
    group_filter = request.args.get("group")
    search_query = request.args.get("q", "").strip().lower()
    cards = []
    for n in notes.values():
        info = _node_payload(n)
        if group_filter and info["group_id"] != group_filter:
            continue
        if search_query and search_query not in (n["title"] + " " + n["content"] + " " + " ".join(n["tags"])).lower():
            continue
        cards.append({"note": n, "info": info})
    cards.sort(key=lambda c: c["note"]["updated_at"], reverse=True)
    return render_template(
        "notes.html",
        cards=cards,
        groups=_group_summaries(),
        active_group=group_filter,
        search_query=request.args.get("q", ""),
        total=len(notes),
    )


@app.route("/notes/new", methods=["GET", "POST"])
def note_create():
    if request.method == "POST":
        note_id = str(uuid.uuid4())
        note_tags = [
            t.strip()
            for t in request.form.get("tags", "").split(",")
            if t.strip()
        ]
        notes[note_id] = {
            "id": note_id,
            "title": request.form["title"],
            "content": request.form["content"],
            "tags": note_tags,
            "group": (request.form.get("group") or "").strip() or None,
            "mastery": "not_started",
            "created_at": clock.now(),
            "updated_at": clock.now(),
        }
        tags.update(note_tags)
        rag_index.add_note(notes[note_id])
        debt_tracker.register_node(note_id, note_tags)
        return redirect(url_for("note_edit", note_id=note_id, saved=1))
    return render_template("note_edit.html", note=None, groups=_group_summaries(),
                           default_group=request.args.get("group", ""))


@app.route("/notes/upload", methods=["POST"])
def notes_upload():
    """Handle bulk file upload of notes."""
    uploaded_files = request.files.getlist("files")
    for f in uploaded_files:
        if not f.filename:
            continue
        filename = f.filename.lower()
        if filename.endswith('.json'):
            try:
                raw = f.read().decode('utf-8')
                data = json.loads(raw)
                if isinstance(data, list):
                    for item in data:
                        note_id = str(uuid.uuid4())
                        note_tags = item.get("tags", [])
                        if isinstance(note_tags, str):
                            note_tags = [t.strip() for t in note_tags.split(",") if t.strip()]
                        notes[note_id] = {
                            "id": note_id,
                            "title": item.get("title", "Untitled"),
                            "content": item.get("content", ""),
                            "tags": note_tags,
                            "mastery": "not_started",
                            "created_at": clock.now(),
                            "updated_at": clock.now(),
                        }
                        tags.update(note_tags)
                elif isinstance(data, dict):
                    note_id = str(uuid.uuid4())
                    note_tags = data.get("tags", [])
                    notes[note_id] = {
                        "id": note_id,
                        "title": data.get("title", "Untitled"),
                        "content": data.get("content", ""),
                        "tags": note_tags if isinstance(note_tags, list) else [],
                        "mastery": "not_started",
                        "created_at": clock.now(),
                        "updated_at": clock.now(),
                    }
                    tags.update(note_tags if isinstance(note_tags, list) else [])
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        elif filename.endswith('.txt') or filename.endswith('.md'):
            try:
                content = f.read().decode('utf-8', errors='replace')
                title = f.filename.rsplit('.', 1)[0]
                note_id = str(uuid.uuid4())
                notes[note_id] = {
                    "id": note_id,
                    "title": title,
                    "content": content,
                    "tags": [],
                    "mastery": "not_started",
                    "created_at": clock.now(),
                    "updated_at": clock.now(),
                }
            except Exception:
                pass
    rag_index.rebuild(notes)
    # Register all uploaded notes with cognitive debt tracker
    for nid, n in notes.items():
        if not debt_tracker.is_registered(nid):
            debt_tracker.register_node(nid, n.get("tags", []))
    return redirect(url_for("notes_list"))


@app.route("/notes/<note_id>")
def note_detail(note_id):
    note = notes.get(note_id)
    if not note:
        return redirect(url_for("notes_list"))
    return redirect(url_for("note_edit", note_id=note_id))


@app.route("/api/notes/<note_id>/keywords")
def note_keywords(note_id):
    """Return redaction targets for a note (keywords + patterns)."""
    note = notes.get(note_id)
    if not note:
        return jsonify({"keywords": [], "patterns": []}), 404
    text = note["title"] + " " + note["content"]
    targets = extract_redaction_targets(text, notes, max_keywords=30)
    return jsonify(targets)


@app.route("/notes/<note_id>/edit", methods=["GET", "POST"])
def note_edit(note_id):
    note = notes.get(note_id)
    if not note:
        return redirect(url_for("notes_list"))

    if request.method == "POST":
        note_tags = [
            t.strip()
            for t in request.form.get("tags", "").split(",")
            if t.strip()
        ]
        note["title"] = request.form["title"]
        note["content"] = request.form["content"]
        note["tags"] = note_tags
        note["group"] = (request.form.get("group") or "").strip() or note.get("group")
        note["updated_at"] = clock.now()
        tags.update(note_tags)
        rag_index.remove_note(note_id)
        rag_index.add_note(note)
        return redirect(url_for("note_edit", note_id=note_id, saved=1))
    return render_template("note_edit.html", note=note, groups=_group_summaries(), default_group="",
                           saved=request.args.get("saved") == "1")


@app.route("/notes/<note_id>/delete", methods=["POST"])
def note_delete(note_id):
    notes.pop(note_id, None)
    chat_messages.pop(note_id, None)
    knowledge_state.pop(note_id, None)
    rag_index.remove_note(note_id)
    debt_tracker.remove_node(note_id)
    remove_connections(note_id)
    # Rebuild tags set from remaining notes
    tags.clear()
    for n in notes.values():
        tags.update(n.get("tags", []))
    return redirect(url_for("notes_list"))


LEVEL_NAMES = {1: "Recall with cues", 2: "Free recall", 3: "Apply", 4: "Synthesize"}


def _last_ai(note_id):
    return next((m for m in reversed(chat_messages.get(note_id, [])) if m["role"] == "ai"), None)


def _make_question(note, level, asked_count, use_explain=False):
    """Produce the next question as structured data: text, related concept, and
    (in scripted demo mode) the answer key used for grading and hints."""
    note_id = note["id"]
    related = pick_related(note_id, level) if not use_explain else []
    scripted_mode = mock_mode.is_mock() and scripted.available(note)
    if scripted_mode:
        qdata = scripted.explain_prompt(note) if use_explain else scripted.pick_question(
            note, level, related[0] if related else None, asked_count)
        if level >= 3 and related and qdata.get("related_title") != related[0]["title"]:
            related = []  # no bridge for this pair; question stays within the concept
        text = qdata["q"]
    else:
        qdata = None
        chunks = rag_index.query(note["title"], top_k=5)
        text = generate_generation_prompt(note, chunks) if use_explain else generate_question(note, chunks, level, related)
    return {
        "text": text,
        "level": level,
        "kind": "explain" if use_explain else "question",
        "related_ids": [n["id"] for n in related],
        "related_titles": [n["title"] for n in related],
        "idea": (qdata or {}).get("idea"),
        "idea_label": _idea_label(note, (qdata or {}).get("idea")),
        "qdata": qdata,
    }


def _idea_label(note, idea_id):
    if not idea_id:
        return None
    return next((i["label"] for i in concepts.key_ideas(note) if i["id"] == idea_id), None)


def _practice_level(note_id):
    """The level to ask at: the learner's pick if they made one, else the recommendation."""
    return level_choice.get(note_id) or get_recommended_difficulty(note_id)


def _drop_unanswered(note_id):
    """A newly asked question replaces one the learner hasn't answered yet."""
    msgs = chat_messages.get(note_id, [])
    if msgs and msgs[-1]["role"] == "ai" and msgs[-1].get("question") and len(msgs) > 0:
        clear_hint_session(note_id, len([m for m in msgs if m["role"] == "ai"]) - 1)
        msgs.pop()
        return True
    return False


def _level_info(note_id):
    return {"recommended_level": get_recommended_difficulty(note_id), "level_choice": level_choice.get(note_id)}


def _public_messages(note_id):
    """Chat history for the browser, without answer keys."""
    return [{k: v for k, v in m.items() if k != "qdata"} for m in chat_messages.get(note_id, [])]


@app.route("/notes/<note_id>/chat", methods=["GET", "POST"])
def note_chat(note_id):
    note = notes.get(note_id)
    if not note:
        return redirect(url_for("index"))

    if request.method == "POST":
        data = request.get_json()
        user_msg = data.get("message", "").strip()
        if not user_msg:
            return jsonify({"error": "Empty message"}), 400

        chat_messages.setdefault(note_id, []).append({"role": "user", "content": user_msg})
        apply_time_decay(note_id)
        last = _last_ai(note_id) or {}
        level = last.get("level") or get_recommended_difficulty(note_id)
        qdata = last.get("qdata")
        reinforced = []

        # A question instead of an answer: respond Socratically, don't grade
        if mock_mode.is_mock() and scripted.available(note) and scripted.is_question(user_msg):
            n_redirects = sum(1 for m in chat_messages[note_id] if m.get("verdict") == "info")
            msg = {
                "role": "ai", "verdict": "info",
                "feedback": scripted.redirect(note, n_redirects),
                "question": None, "level": level,
                "related_ids": last.get("related_ids", []), "qdata": qdata, "idea": last.get("idea"),
                "kind": last.get("kind", "question"),
            }
            msg["content"] = msg["feedback"]
            chat_messages[note_id].append(msg)
            return jsonify({**{k: v for k, v in msg.items() if k != "qdata"},
                            "mastery": node_label(note_id),
                            "mastery_value": round(get_decayed_mastery(note_id), 3),
                            "reinforced": []})

        # --- Grade the answer against the question that was asked ---
        retrieved_chunks = rag_index.query(user_msg, top_k=5)
        source_text = " ".join(c["text"] for c in retrieved_chunks)
        check_verbatim = level >= 3 or last.get("kind") == "explain"
        overlap = compute_text_overlap(user_msg, source_text) if check_verbatim and source_text.strip() else None
        if qdata:
            ev = scripted.grade(user_msg, qdata, overlap)
        elif last.get("kind") == "explain":
            ev = evaluate_generation(user_msg, retrieved_chunks, last.get("content", ""), overlap)
        else:
            ev = evaluate_response(user_msg, retrieved_chunks, last.get("content", ""), overlap)
        if not check_verbatim:
            ev["verbatim"] = False
        verdict = ev.get("verdict") or ("verbatim" if ev.get("verbatim") else
                                        "correct" if ev["correct"] else "partial" if ev["partial"] else "incorrect")

        # --- Update memory strength ---
        if verdict == "verbatim":
            update_mastery(note_id, level, False)
        elif verdict == "partial":
            update_mastery(note_id, max(1, level - 1), True)
        else:
            update_mastery(note_id, level, verdict == "correct")

        # Track which key idea was tested (drives the sub-concept view)
        if qdata and qdata.get("idea"):
            hits = get_mastery(note_id).setdefault("idea_hits", {})
            hits.setdefault(qdata["idea"], []).append(verdict == "correct")

        # --- Strengthen (or weaken) the connection this question exercised ---
        edge_ok, edge_w = {"correct": (True, 1.0), "partial": (True, 0.5)}.get(verdict, (False, 1.0))
        for rid in last.get("related_ids", []):
            if rid in notes:
                r = reinforce(note_id, rid, edge_ok, edge_w)
                r["target_title"] = notes[rid]["title"]
                reinforced.append(r)

        debt_tracker.record_engagement(note_id)
        clear_hint_session(note_id, len([m for m in chat_messages[note_id] if m["role"] == "ai"]) - 1)
        note["mastery"] = node_label(note_id)

        # --- Next question ---
        next_level = _practice_level(note_id)
        n_interactions = len(get_mastery(note_id)["interactions"])
        use_explain = next_level >= 2 and n_interactions % 4 == 0
        asked = sum(1 for m in chat_messages[note_id] if m["role"] == "ai" and m.get("level") == next_level)
        q = _make_question(note, next_level, asked, use_explain)

        msg = {
            "role": "ai", "verdict": verdict, "feedback": ev.get("feedback", ""),
            "question": q["text"], "level": next_level, "kind": q["kind"],
            "related_ids": q["related_ids"], "related_titles": q["related_titles"],
            "reinforced": reinforced, "qdata": q["qdata"], "idea": q["idea"], "idea_label": q["idea_label"],
            "is_generation": q["kind"] == "explain",
        }
        msg["content"] = (msg["feedback"] + "\n\n" + q["text"]).strip()
        chat_messages[note_id].append(msg)

        return jsonify({
            **{k: v for k, v in msg.items() if k != "qdata"},
            "mastery": note["mastery"],
            "mastery_value": round(get_decayed_mastery(note_id), 3),
            "difficulty_level": next_level,
            "level_name": LEVEL_NAMES.get(next_level, ""),
            **_level_info(note_id),
            "evaluation": {"correct": ev["correct"], "partial": ev["partial"], "verbatim": ev.get("verbatim", False)},
        })

    # GET: open with an adaptive first question
    if note_id not in chat_messages:
        apply_time_decay(note_id)
        level = _practice_level(note_id)
        q = _make_question(note, level, 0)
        intro = (f"Let's see what you remember about {note['title']}." if get_mastery(note_id)["interactions"]
                 else f"First time on {note['title']}. Let's start with what you can recall.")
        chat_messages[note_id] = [{
            "role": "ai", "intro": intro, "question": q["text"], "level": level, "kind": q["kind"],
            "related_ids": q["related_ids"], "related_titles": q["related_titles"], "qdata": q["qdata"],
            "idea": q["idea"], "idea_label": q["idea_label"], "content": intro + "\n\n" + q["text"],
        }]

    decayed = get_decayed_mastery(note_id)
    note["mastery"] = node_label(note_id)
    return render_template(
        "chat.html",
        note=note,
        messages=_public_messages(note_id),
        mastery_value=round(decayed, 3),
        level_names=LEVEL_NAMES,
        level_info=_level_info(note_id),
        embed=request.args.get("embed") == "1",
    )


@app.route("/notes/<note_id>/chat/idea", methods=["POST"])
def note_chat_idea(note_id):
    """The learner picked a key idea on the map: ask a question about that idea."""
    note = notes.get(note_id)
    if not note:
        return jsonify({"error": "Unknown note"}), 404
    idea_id = (request.get_json(silent=True) or {}).get("idea")
    label = _idea_label(note, idea_id)
    if not label:
        return jsonify({"error": "Unknown key idea"}), 400
    msgs = chat_messages.setdefault(note_id, [])
    replaced = _drop_unanswered(note_id)
    level = _practice_level(note_id)
    asked = sum(1 for m in msgs if m.get("idea") == idea_id)
    qdata, q_level = (None, level)
    if mock_mode.is_mock() and scripted.available(note):
        qdata, q_level = scripted.question_for_idea(note, idea_id, level, asked)
    if qdata:
        text = qdata["q"]
    else:
        chunks = rag_index.query(note["title"] + " " + label, top_k=5)
        text = generate_question(note, chunks, level, [])
        q_level = level
    msg = {
        "role": "ai", "intro": f"Let's review {label}.", "question": text, "level": q_level,
        "kind": "question", "related_ids": [], "related_titles": [], "idea": idea_id,
        "idea_label": label, "qdata": qdata,
    }
    msg["content"] = msg["intro"] + "\n\n" + text
    msgs.append(msg)
    return jsonify({**{k: v for k, v in msg.items() if k != "qdata"}, "replaced": replaced, **_level_info(note_id)})


@app.route("/notes/<note_id>/chat/level", methods=["POST"])
def note_chat_level(note_id):
    """The learner picked a level (or "auto"). Ask a fresh question at that level.

    Mastery grows by the level answered at: an easier level than recommended
    moves memory less, a harder one moves it more (see LEVEL_WEIGHTS).
    """
    note = notes.get(note_id)
    if not note:
        return jsonify({"error": "Unknown note"}), 404
    choice = (request.get_json(silent=True) or {}).get("level")
    if choice in (1, 2, 3, 4, "1", "2", "3", "4"):
        level_choice[note_id] = int(choice)
    else:
        level_choice.pop(note_id, None)
    replaced = _drop_unanswered(note_id)
    level = _practice_level(note_id)
    msgs = chat_messages.setdefault(note_id, [])
    asked = sum(1 for m in msgs if m["role"] == "ai" and m.get("level") == level)
    q = _make_question(note, level, asked)
    rec = get_recommended_difficulty(note_id)
    if level < rec:
        intro = f"Level {level}: easier than recommended, so it builds memory a little less."
    elif level > rec:
        intro = f"Level {level}: a stretch above your level, so it builds memory more."
    else:
        intro = f"Level {level}: right at your level."
    msg = {
        "role": "ai", "intro": intro, "question": q["text"], "level": level, "kind": q["kind"],
        "related_ids": q["related_ids"], "related_titles": q["related_titles"], "idea": q["idea"],
        "idea_label": q["idea_label"], "qdata": q["qdata"],
    }
    msg["content"] = intro + "\n\n" + q["text"]
    msgs.append(msg)
    return jsonify({**{k: v for k, v in msg.items() if k != "qdata"}, "replaced": replaced, **_level_info(note_id)})


@app.route("/api/hint", methods=["POST"])
def api_hint():
    """Generate the next progressive hint for an active question.

    Accepts JSON: { note_id, question_index (optional), hint_response (optional) }
    Returns JSON: { level, text, is_question, is_reveal, mastery_recovery (optional) }
    """
    data = request.get_json()
    note_id = data.get("note_id")
    hint_response = data.get("hint_response", "").strip()

    if not note_id or note_id not in notes:
        return jsonify({"error": "Invalid note_id"}), 400

    note = notes[note_id]

    # Determine question index (current AI question count)
    msgs = chat_messages.get(note_id, [])
    question_index = data.get("question_index")
    if question_index is None:
        question_index = len([m for m in msgs if m["role"] == "ai"]) - 1

    # Get or create hint session
    hint_state = get_hint_session(note_id, question_index)

    if hint_state is None:
        # Find the last AI question
        last_question = ""
        for msg in reversed(msgs):
            if msg["role"] == "ai":
                last_question = msg.get("question") or msg["content"]
                break

        if not last_question:
            return jsonify({"error": "No active question"}), 400

        # Retrieve context
        retrieved_chunks = rag_index.query(note["title"], top_k=5)
        kt_state = get_mastery(note_id)
        mastery = get_decayed_mastery(note_id)

        # Gather related notes for graph context
        current_tags = set(note.get("tags", []))
        related_notes = [
            n for nid, n in notes.items()
            if nid != note_id and current_tags & set(n.get("tags", []))
        ][:3]

        hint_state = create_hint_session(
            note_id, question_index, note, last_question,
            retrieved_chunks, mastery, related_notes,
        )
        last_ai = _last_ai(note_id) or {}
        if mock_mode.is_mock() and last_ai.get("qdata"):
            hint_state.script = last_ai["qdata"]
            hint_state.start_level = hint_state.current_level = 1

    # If user responded to a previous hint question, evaluate it
    mastery_recovery = None
    if hint_response and hint_state.hints_given:
        last_hint = hint_state.hints_given[-1]
        if last_hint["level"] < 4:  # Only evaluate responses to Socratic hints
            eval_result = evaluate_hint_response(
                hint_state, hint_response, last_hint["level"]
            )
            mastery_recovery = eval_result
            # Credit partial mastery recovery if response was good
            if eval_result["above_threshold"]:
                update_mastery(note_id, max(1, last_hint["level"]), True)
                note["mastery"] = node_label(note_id)

    # Generate next hint
    hint = generate_next_hint(hint_state)

    if hint is None:
        return jsonify({"error": "All hints exhausted", "exhausted": True}), 200

    # If this is the reveal (L4), update mastery downward
    if hint["is_reveal"]:
        update_mastery(note_id, 1, False)  # Penalty for needing full reveal
        note["mastery"] = node_label(note_id)

    kt_state = get_mastery(note_id)
    response = {
        "level": hint["level"],
        "text": hint["text"],
        "is_question": hint["is_question"],
        "is_reveal": hint["is_reveal"],
        "hints_remaining": max(0, 4 - hint_state.current_level + 1),
        "mastery": note["mastery"],
        "mastery_value": round(get_decayed_mastery(note_id), 3),
    }
    if mastery_recovery:
        response["mastery_recovery"] = mastery_recovery

    return jsonify(response)


@app.route("/api/cognitive-debt")
def api_cognitive_debt():
    """Return list of unengaged nodes with metadata.

    Returns JSON: { debt_count, nodes: [{note_id, title, tags, hours_since_creation,
                    engagement_count, child_count}], nudge_message }
    """
    debt_nodes = debt_tracker.get_debt_nodes(notes)

    # Rank by graph centrality (nodes connected to many others first)
    tag_counts = {}
    for n in notes.values():
        for t in n.get("tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1

    for node in debt_nodes:
        note = notes.get(node["note_id"])
        if note:
            centrality = sum(tag_counts.get(t, 0) for t in note.get("tags", []))
            node["centrality"] = centrality

    debt_nodes.sort(key=lambda x: x.get("centrality", 0), reverse=True)

    nudge = None
    if len(debt_nodes) >= 3:
        nudge = (
            f"You've added {len(debt_nodes)} new topics you haven't reviewed yet. "
            f"Let's make sure they stick — start a quick quiz on your newest notes."
        )
    elif debt_nodes:
        nudge = (
            f"You have {len(debt_nodes)} unreviewed "
            f"{'topic' if len(debt_nodes) == 1 else 'topics'}. "
            f"Want to start a quick quiz?"
        )

    return jsonify({
        "debt_count": len(debt_nodes),
        "nodes": debt_nodes[:20],  # Cap at 20 for display
        "nudge_message": nudge,
    })


@app.route("/query")
def query():
    return render_template("query.html")


ASK_DIRECT_THRESHOLD = 0.85   # memory score at which Ask answers straight away


def _ask_answer(note, user_query, chunks):
    if mock_mode.is_mock() and scripted.available(note):
        return scripted.summary(note)
    return generate_rag_response(user_query, chunks, mode="direct")


@app.route("/api/ask", methods=["POST"])
def api_ask():
    """Ask your notes, with recall first for anything still being learned.

    step "ask":     find the concept. Mastered -> answer now. Otherwise -> ask the
                    learner to recall first (capture is free, lookup is earned).
    step "attempt": compare their recall to the concept's key ideas, then answer.
    step "reveal":  answer without an attempt; recorded as a lookup, no memory gain.
    """
    data = request.get_json(silent=True) or {}
    step = data.get("step", "ask")
    user_query = (data.get("query") or "").strip()
    if not user_query:
        return jsonify({"error": "Ask a question"}), 400
    chunks = rag_index.query(user_query, top_k=5)
    order = []
    for c in chunks:
        if c["note_id"] in notes and c["note_id"] not in order:
            order.append(c["note_id"])
    concept_id = data.get("concept_id") or (order[0] if order else None)
    if not concept_id or concept_id not in notes:
        return jsonify({"mode": "none", "message": "Nothing in your notes covers that yet. Capture it as a note first."})
    note = notes[concept_id]
    info = _node_payload(note)
    sources = [{"id": nid, "title": notes[nid]["title"]} for nid in order[:3]]
    base = {"concept": {"id": concept_id, "title": note["title"], "group": info["group"],
                        "mastery": info["mastery"], "mastery_value": info["mastery_value"]},
            "sources": sources}

    if step == "ask":
        if info["mastery"] != "not_started" and info["mastery_value"] >= ASK_DIRECT_THRESHOLD:
            return jsonify({**base, "mode": "answer", "why": "mastered",
                            "answer": _ask_answer(note, user_query, chunks)})
        state = "haven't practiced" if info["mastery"] == "not_started" else f"are at {round(info['mastery_value'] * 100)}% on"
        return jsonify({**base, "mode": "recall",
                        "prompt": f"You {state} {note['title']}. Before I answer, what do you already remember about it?",
                        "ideas": len(info["ideas"])})

    if step == "attempt":
        attempt = (data.get("attempt") or "").lower()
        recalled = []
        for idea in info["ideas"]:
            words = [w for w in re.findall(r"[a-z]+", idea["label"].lower()) if len(w) > 3]
            if any(w[:5] in attempt for w in words):
                recalled.append(idea["label"])
        total = len(info["ideas"]) or 1
        good = len(recalled) >= max(1, total // 2)
        update_mastery(concept_id, 1, good)
        debt_tracker.record_engagement(concept_id)
        return jsonify({**base, "mode": "answer", "why": "attempted", "recalled": recalled, "total": len(info["ideas"]),
                        "answer": _ask_answer(note, user_query, chunks),
                        "mastery_after": round(get_decayed_mastery(concept_id), 3)})

    return jsonify({**base, "mode": "answer", "why": "revealed", "answer": _ask_answer(note, user_query, chunks)})


if __name__ == "__main__":
    app.run(debug=True, port=5001)

import os as _os
from dotenv import load_dotenv
load_dotenv(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env"), override=True)

from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime
import uuid
import json

from similarity import find_similar_pairs, compute_text_overlap, extract_redaction_targets
from rag import RAGIndex
from llm import (
    generate_rag_response, generate_chat_response,
    evaluate_response, evaluate_generation,
)
from knowledge_trace import (
    get_mastery, apply_time_decay, update_mastery,
    get_recommended_difficulty, get_response_mode, mastery_to_label,
    knowledge_state,
)
from question_gen import generate_question, generate_generation_prompt

app = Flask(__name__)

# RAG index (initialized after seed notes are loaded)
rag_index = RAGIndex()

# In-memory storage (will be replaced with a database later)
notes = {}
tags = set()
chat_messages = {}  # { note_id: [ {"role": "user"|"ai", "content": str} ] }


def seed_sample_notes():
    """Seed some sample notes for demonstration purposes."""
    samples = [
        {
            "title": "Desirable Difficulties in Learning",
            "content": (
                "Bjork & Bjork (2020) formalized the idea that making retrieval "
                "harder leads to deeper cognitive processing and better long-term "
                "retention.\n\n"
                "Key points:\n"
                "- Repeated testing yields ~80% recall vs passive review\n"
                "- Difficulty during encoding strengthens memory traces\n"
                "- Spacing, interleaving, and variation are core mechanisms\n"
                "- The effort must be productive, not just hard"
            ),
            "tags": ["learning-science", "memory"],
            "mastery": "green",
        },
        {
            "title": "RAG Pipeline Overview",
            "content": (
                "Retrieval-Augmented Generation (Lewis et al., 2020) combines "
                "retrieval with generation.\n\n"
                "Pipeline steps:\n"
                "1. Chunk and embed documents\n"
                "2. Index embeddings (e.g. FAISS)\n"
                "3. On query, retrieve top-k similar chunks\n"
                "4. Pass retrieved context + query to LLM\n"
                "5. Generate grounded response"
            ),
            "tags": ["ai", "rag"],
            "mastery": "yellow",
        },
        {
            "title": "Knowledge Tracing Methods",
            "content": (
                "Knowledge tracing models a learner's mastery over time.\n\n"
                "Approaches:\n"
                "- Bayesian Knowledge Tracing (BKT): probabilistic per-skill model\n"
                "- Deep Knowledge Tracing (DKT): RNN-based sequence modeling\n"
                "- Few-shot methods (Li et al., 2025): accurate with minimal data\n"
                "- Time-aware models (Huang et al., 2026): account for forgetting"
            ),
            "tags": ["learning-science", "ai"],
            "mastery": "red",
        },
        {
            "title": "Spaced Repetition Systems",
            "content": (
                "Spaced repetition leverages the spacing effect to optimize review intervals.\n\n"
                "Key algorithms:\n"
                "- SM-2 (SuperMemo): original algorithm with ease factors\n"
                "- FSRS: modern algorithm using neural network predictions\n"
                "- Leitner system: simple box-based approach\n"
                "Optimal intervals increase exponentially with mastery."
            ),
            "tags": ["learning-science", "memory"],
            "mastery": "not_started",
        },
        {
            "title": "Transformer Architecture",
            "content": (
                "The Transformer (Vaswani et al., 2017) introduced self-attention.\n\n"
                "Components:\n"
                "- Multi-head self-attention\n"
                "- Position-wise feed-forward networks\n"
                "- Layer normalization and residual connections\n"
                "- Positional encoding for sequence order"
            ),
            "tags": ["ai", "deep-learning"],
            "mastery": "not_started",
        },
        {
            "title": "Active Recall Techniques",
            "content": (
                "Active recall forces retrieval from memory rather than passive review.\n\n"
                "Techniques:\n"
                "- Flashcards with self-testing\n"
                "- Free recall after reading\n"
                "- Practice problems without notes\n"
                "- Teaching concepts to others"
            ),
            "tags": ["learning-science", "memory"],
            "mastery": "green",
        },
        {
            "title": "Vector Embeddings",
            "content": (
                "Embeddings map discrete tokens to continuous vector spaces.\n\n"
                "Key ideas:\n"
                "- Word2Vec: skip-gram and CBOW models\n"
                "- Sentence embeddings capture semantic meaning\n"
                "- Cosine similarity measures relatedness\n"
                "- Dense vectors enable nearest-neighbor search"
            ),
            "tags": ["ai", "rag"],
            "mastery": "yellow",
        },
        {
            "title": "Metacognition in Learning",
            "content": (
                "Metacognition is thinking about thinking.\n\n"
                "Components:\n"
                "- Self-monitoring: awareness of comprehension\n"
                "- Self-regulation: adjusting study strategies\n"
                "- Calibration: matching confidence to actual knowledge\n"
                "- Reflection: evaluating what worked and what didn't"
            ),
            "tags": ["learning-science", "psychology"],
            "mastery": "red",
        },
        {
            "title": "Neural Network Basics",
            "content": (
                "Neural networks are composed of layers of interconnected neurons.\n\n"
                "Fundamentals:\n"
                "- Neurons apply weights, bias, and activation\n"
                "- Backpropagation computes gradients\n"
                "- SGD and Adam are common optimizers\n"
                "- Overfitting prevented by dropout and regularization"
            ),
            "tags": ["ai", "deep-learning"],
            "mastery": "green",
        },
        {
            "title": "Forgetting Curve",
            "content": (
                "Ebbinghaus showed memory decays exponentially without review.\n\n"
                "Key findings:\n"
                "- ~50% forgotten within one hour\n"
                "- ~70% forgotten within 24 hours\n"
                "- Spaced review resets the curve\n"
                "- Each review extends retention duration"
            ),
            "tags": ["memory", "psychology"],
            "mastery": "yellow",
        },
        {
            "title": "Prompt Engineering",
            "content": (
                "Designing effective prompts for large language models.\n\n"
                "Strategies:\n"
                "- Chain-of-thought reasoning\n"
                "- Few-shot examples in context\n"
                "- Role-based system prompts\n"
                "- Structured output formatting"
            ),
            "tags": ["ai", "rag"],
            "mastery": "not_started",
        },
        {
            "title": "Interleaving Practice",
            "content": (
                "Mixing different topics during study sessions improves learning.\n\n"
                "Benefits:\n"
                "- Forces discrimination between concepts\n"
                "- Strengthens retrieval pathways\n"
                "- Better transfer to novel problems\n"
                "- Feels harder but produces lasting results"
            ),
            "tags": ["learning-science"],
            "mastery": "red",
        },
    ]
    for sample in samples:
        note_id = str(uuid.uuid4())
        notes[note_id] = {
            "id": note_id,
            "title": sample["title"],
            "content": sample["content"],
            "tags": sample["tags"],
            "mastery": sample["mastery"],
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        tags.update(sample["tags"])


seed_sample_notes()
rag_index.rebuild(notes)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/graph-data")
def graph_data():
    """Return nodes, edges, potential connections, and clusters for the knowledge graph."""
    node_list = []
    for note in notes.values():
        node_list.append({
            "id": note["id"],
            "title": note["title"],
            "mastery": note["mastery"],
            "tags": note["tags"],
        })

    edges = []
    note_vals = list(notes.values())
    for i in range(len(note_vals)):
        for j in range(i + 1, len(note_vals)):
            shared = set(note_vals[i]["tags"]) & set(note_vals[j]["tags"])
            if shared:
                m1 = note_vals[i]["mastery"]
                m2 = note_vals[j]["mastery"]
                t1 = note_vals[i]["title"]
                t2 = note_vals[j]["title"]
                if m1 == "green" and m2 == "green":
                    edge_mastery = "green"
                    reason = "Strong connection: both topics mastered"
                elif "red" in (m1, m2):
                    edge_mastery = "red"
                    weak = t1 if m1 == "red" else t2
                    reason = f"Weak link: '{weak}' not understood"
                elif "yellow" in (m1, m2) or "green" in (m1, m2):
                    edge_mastery = "yellow"
                    reason = "Partial: one or both topics still progressing"
                else:
                    edge_mastery = "not_started"
                    reason = "Unexplored: neither topic has been studied"
                edges.append({
                    "source": note_vals[i]["id"],
                    "target": note_vals[j]["id"],
                    "shared_tags": list(shared),
                    "mastery": edge_mastery,
                    "reason": reason,
                    "source_mastery": m1,
                    "target_mastery": m2,
                })

    # Cosine similarity for potential connections
    existing_edge_keys = set()
    for e in edges:
        key = tuple(sorted([e["source"], e["target"]]))
        existing_edge_keys.add(key)

    potential = []
    try:
        similar_pairs = find_similar_pairs(notes, threshold=0.15)
        for id1, id2, score in similar_pairs:
            key = tuple(sorted([id1, id2]))
            if key not in existing_edge_keys:
                potential.append({
                    "source": id1,
                    "target": id2,
                    "similarity": round(score, 3),
                })
    except Exception:
        pass  # Graceful fallback if similarity computation fails

    # Clusters by primary tag
    clusters = {}
    for note in notes.values():
        primary_tag = note["tags"][0] if note["tags"] else "uncategorized"
        if primary_tag not in clusters:
            clusters[primary_tag] = []
        clusters[primary_tag].append(note["id"])

    return jsonify({
        "nodes": node_list,
        "edges": edges,
        "potential_connections": potential,
        "clusters": clusters,
    })


@app.route("/notes")
def notes_list():
    tag_filter = request.args.get("tag")
    search_query = request.args.get("q", "").strip().lower()
    search_scope = request.args.get("scope", "all")

    filtered = list(notes.values())

    if tag_filter:
        filtered = [n for n in filtered if tag_filter in n["tags"]]
    if search_query:
        if search_scope == "title":
            filtered = [n for n in filtered if search_query in n["title"].lower()]
        elif search_scope == "content":
            filtered = [n for n in filtered if search_query in n["content"].lower()]
        else:
            filtered = [
                n
                for n in filtered
                if search_query in n["title"].lower()
                or search_query in n["content"].lower()
            ]

    filtered.sort(key=lambda n: n["updated_at"], reverse=True)
    return render_template(
        "notes.html",
        notes=filtered,
        all_tags=sorted(tags),
        active_tag=tag_filter,
        search_query=request.args.get("q", ""),
        search_scope=search_scope,
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
            "mastery": "not_started",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        tags.update(note_tags)
        rag_index.add_note(notes[note_id])
        return redirect(url_for("note_edit", note_id=note_id))
    return render_template("note_edit.html", note=None)


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
                            "created_at": datetime.now(),
                            "updated_at": datetime.now(),
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
                        "created_at": datetime.now(),
                        "updated_at": datetime.now(),
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
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
            except Exception:
                pass
    rag_index.rebuild(notes)
    return redirect(url_for("notes_list"))


@app.route("/notes/<note_id>")
def note_detail(note_id):
    note = notes.get(note_id)
    if not note:
        return redirect(url_for("notes_list"))
    return render_template("note_detail.html", note=note)


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
        note["updated_at"] = datetime.now()
        tags.update(note_tags)
        rag_index.remove_note(note_id)
        rag_index.add_note(note)
        return redirect(url_for("note_edit", note_id=note_id))
    return render_template("note_edit.html", note=note)


@app.route("/notes/<note_id>/delete", methods=["POST"])
def note_delete(note_id):
    notes.pop(note_id, None)
    chat_messages.pop(note_id, None)
    knowledge_state.pop(note_id, None)
    rag_index.remove_note(note_id)
    # Rebuild tags set from remaining notes
    tags.clear()
    for n in notes.values():
        tags.update(n.get("tags", []))
    return redirect(url_for("notes_list"))


@app.route("/notes/<note_id>/chat", methods=["GET", "POST"])
def note_chat(note_id):
    note = notes.get(note_id)
    if not note:
        return redirect(url_for("index"))

    if request.method == "POST":
        data = request.get_json()
        user_msg = data.get("message", "").strip()
        mode = data.get("mode", "auto")
        if not user_msg:
            return jsonify({"error": "Empty message"}), 400

        if note_id not in chat_messages:
            chat_messages[note_id] = []

        chat_messages[note_id].append({"role": "user", "content": user_msg})

        # --- Knowledge tracing: apply time decay on returning sessions ---
        apply_time_decay(note_id)
        kt_state = get_mastery(note_id)

        # --- Retrieval decision router ---
        # In "auto" mode, the router decides; otherwise respect the user's choice
        if mode == "auto":
            routed_mode = get_response_mode(note_id)
        else:
            routed_mode = mode

        # Determine difficulty level for question generation
        difficulty_level = get_recommended_difficulty(note_id)

        # Retrieve relevant chunks via RAG
        retrieved_chunks = rag_index.query(user_msg, top_k=5)

        # --- Compute text overlap for verbatim detection ---
        # Only run verbatim detection for levels 3+ and generation assessments.
        # Levels 1-2 (cued/free recall) often expect near-verbatim answers
        # (fill-in-the-blank, T/F, listing), so penalizing copying is wrong.
        source_text = " ".join(c["text"] for c in retrieved_chunks)
        use_verbatim_detection = difficulty_level >= 3
        overlap_stats = None

        # --- Evaluate the user's answer against the last AI question ---
        eval_result = {"correct": False, "partial": True, "verbatim": False, "feedback": "", "overlap": None}
        last_ai_msg = None
        is_generation_assessment = False
        for msg in reversed(chat_messages[note_id][:-1]):
            if msg["role"] == "ai":
                last_ai_msg = msg["content"]
                # Detect if the last AI message was a generation-based prompt
                is_generation_assessment = msg.get("is_generation", False)
                break

        # Generation assessments always check for verbatim
        if is_generation_assessment:
            use_verbatim_detection = True

        if use_verbatim_detection and source_text.strip():
            overlap_stats = compute_text_overlap(user_msg, source_text)

        if last_ai_msg:
            if is_generation_assessment:
                eval_result = evaluate_generation(
                    user_msg, retrieved_chunks, last_ai_msg, overlap_stats
                )
            else:
                eval_result = evaluate_response(
                    user_msg, retrieved_chunks, last_ai_msg, overlap_stats
                )

        # Force verbatim=False for levels 1-2 even if LLM flagged it
        if not use_verbatim_detection:
            eval_result["verbatim"] = False

        # --- Update mastery based on evaluation ---
        is_correct = eval_result["correct"]
        is_verbatim = eval_result.get("verbatim", False)

        if is_verbatim:
            # Verbatim copying: no mastery gain, small penalty
            update_mastery(note_id, difficulty_level, False)
        elif not is_correct and eval_result["partial"]:
            # Partial credit: treat as correct at reduced weight
            update_mastery(note_id, max(1, difficulty_level - 1), True)
        else:
            update_mastery(note_id, difficulty_level, is_correct)

        # Sync legacy mastery label on the note
        note["mastery"] = mastery_to_label(kt_state["mastery"])

        # --- Gather related notes for Level 3–4 questions ---
        related_notes = None
        if difficulty_level >= 3:
            # Find notes that share tags with the current note
            current_tags = set(note.get("tags", []))
            related_notes = [
                n for nid, n in notes.items()
                if nid != note_id and current_tags & set(n.get("tags", []))
            ][:3]

        # --- Generate response ---
        if routed_mode == "direct":
            # Mastered topic: provide direct RAG answer
            ai_response = generate_chat_response(
                note=note,
                history=chat_messages[note_id][:-1],
                user_msg=user_msg,
                chunks=retrieved_chunks,
                mode="direct",
            )
            msg_meta = {"role": "ai", "content": ai_response}
        elif routed_mode == "question":
            # Recalculate difficulty after mastery update
            difficulty_level = get_recommended_difficulty(note_id)

            # Decide whether to use a generation-based prompt
            # Use generation assessment ~every 3rd question at level 2+
            interaction_count = len(kt_state.get("interactions", []))
            use_generation = (
                difficulty_level >= 2
                and interaction_count > 0
                and interaction_count % 3 == 0
            )

            if use_generation:
                next_question = generate_generation_prompt(note, retrieved_chunks)
            else:
                # Gather related notes for L3/L4
                if difficulty_level >= 3 and related_notes is None:
                    current_tags = set(note.get("tags", []))
                    related_notes = [
                        n for nid, n in notes.items()
                        if nid != note_id and current_tags & set(n.get("tags", []))
                    ][:3]
                next_question = generate_question(
                    note, retrieved_chunks, difficulty_level, related_notes
                )

            # Build a response: feedback on their answer + next question
            feedback = eval_result.get("feedback", "")
            verbatim_warning = ""
            if is_verbatim:
                verbatim_warning = (
                    " It looks like your answer was copied closely from the source material. "
                    "Try to rephrase in your own words — that's where real learning happens!"
                )

            if is_correct:
                ai_response = f"That's right! {feedback}{verbatim_warning}\n\nHere's your next question:\n\n{next_question}"
            elif is_verbatim:
                ai_response = f"{feedback}{verbatim_warning}\n\nLet's try again:\n\n{next_question}"
            elif eval_result["partial"]:
                ai_response = f"You're on the right track. {feedback}{verbatim_warning}\n\nLet's try another one:\n\n{next_question}"
            else:
                ai_response = f"Not quite. {feedback}\n\nLet's try this:\n\n{next_question}"

            msg_meta = {"role": "ai", "content": ai_response, "is_generation": use_generation}
        else:
            # Hints or other modes: pass through to chat LLM
            ai_response = generate_chat_response(
                note=note,
                history=chat_messages[note_id][:-1],
                user_msg=user_msg,
                chunks=retrieved_chunks,
                mode=routed_mode,
            )
            msg_meta = {"role": "ai", "content": ai_response}

        chat_messages[note_id].append(msg_meta)

        return jsonify({
            "response": ai_response,
            "mastery": note["mastery"],
            "mastery_value": round(kt_state["mastery"], 3),
            "difficulty_level": difficulty_level,
            "evaluation": {
                "correct": eval_result["correct"],
                "partial": eval_result["partial"],
                "verbatim": eval_result.get("verbatim", False),
            },
        })

    # GET: render the chat page with initial AI question
    LEVEL_LABELS = {
        1: "Level 1 (cued recall)",
        2: "Level 2 (free recall)",
        3: "Level 3 (application)",
        4: "Level 4 (synthesis)",
    }
    if note_id not in chat_messages:
        # Apply time decay for returning users
        apply_time_decay(note_id)
        # Use knowledge trace to determine starting difficulty
        difficulty_level = get_recommended_difficulty(note_id)
        # Retrieve chunks for question generation
        retrieved_chunks = rag_index.query(note["title"], top_k=5)
        # Gather related notes for L3/L4
        related_notes = None
        if difficulty_level >= 3:
            current_tags = set(note.get("tags", []))
            related_notes = [
                n for nid, n in notes.items()
                if nid != note_id and current_tags & set(n.get("tags", []))
            ][:3]
        # Generate an adaptive initial question
        initial_question = generate_question(
            note, retrieved_chunks, difficulty_level, related_notes
        )
        level_label = LEVEL_LABELS.get(difficulty_level, f"Level {difficulty_level}")
        initial_msg = f"Let's test your knowledge of '{note['title']}' — {level_label}.\n\n{initial_question}"
        chat_messages[note_id] = [{"role": "ai", "content": initial_msg}]

    kt_state = get_mastery(note_id)

    return render_template(
        "chat.html",
        note=note,
        messages=chat_messages[note_id],
        mastery_value=round(kt_state["mastery"], 3),
        difficulty_level=get_recommended_difficulty(note_id),
    )


@app.route("/query", methods=["GET", "POST"])
def query():
    result = None
    if request.method == "POST":
        user_query = request.form.get("query", "").strip()
        if user_query:
            # Retrieve relevant chunks
            retrieved_chunks = rag_index.query(user_query, top_k=5)

            # Generate LLM response
            response_text = generate_rag_response(user_query, retrieved_chunks, mode="direct")

            # Collect source notes (deduplicated, preserving order)
            source_ids = []
            seen = set()
            for chunk in retrieved_chunks:
                nid = chunk["note_id"]
                if nid not in seen and nid in notes:
                    seen.add(nid)
                    source_ids.append(nid)

            result = {
                "query": user_query,
                "mode": "direct",
                "response": response_text,
                "sources": [notes[nid] for nid in source_ids],
            }
    return render_template("query.html", result=result)


if __name__ == "__main__":
    app.run(debug=True, port=5001)

"""
Demo seed data: sample notes plus a realistic, back-dated review history.

Instead of hard-coding mastery colors, each note's history is *replayed*
through the real knowledge-tracing and connection models with the clock
pinned to the past. What the graph shows on first load is therefore exactly
what the models produce: well-practiced topics are strong, neglected ones
have faded, and untouched ones are dormant.
"""

import uuid
from datetime import timedelta

import clock
from knowledge_trace import update_mastery, apply_time_decay
from connections import reinforce

NAMESPACE = uuid.UUID("6f1d3c2a-9b7e-4c55-8e21-0a4b5c6d7e8f")


def note_id_for(title):
    return str(uuid.uuid5(NAMESPACE, title))


SAMPLES = [
    ("Desirable Difficulties in Learning",
     "Bjork & Bjork (2020) formalized the idea that making retrieval harder leads to "
     "deeper cognitive processing and better long-term retention.\n\nKey points:\n"
     "- Repeated testing yields ~80% recall vs passive review\n"
     "- Difficulty during encoding strengthens memory traces\n"
     "- Spacing, interleaving, and variation are core mechanisms\n"
     "- The effort must be productive, not just hard",
     ["learning-science", "memory"]),
    ("RAG Pipeline Overview",
     "Retrieval-Augmented Generation (Lewis et al., 2020) combines retrieval with "
     "generation.\n\nPipeline steps:\n1. Chunk and embed documents\n"
     "2. Index embeddings (e.g. FAISS)\n3. On query, retrieve top-k similar chunks\n"
     "4. Pass retrieved context + query to LLM\n5. Generate grounded response",
     ["ai", "rag"]),
    ("Knowledge Tracing Methods",
     "Knowledge tracing models a learner's mastery over time.\n\nApproaches:\n"
     "- Bayesian Knowledge Tracing (BKT): probabilistic per-skill model\n"
     "- Deep Knowledge Tracing (DKT): RNN-based sequence modeling\n"
     "- Few-shot methods (Li et al., 2025): accurate with minimal data\n"
     "- Time-aware models (Huang et al., 2026): account for forgetting",
     ["learning-science", "ai"]),
    ("Spaced Repetition Systems",
     "Spaced repetition leverages the spacing effect to optimize review intervals.\n\n"
     "Key algorithms:\n- SM-2 (SuperMemo): original algorithm with ease factors\n"
     "- FSRS: modern algorithm using neural network predictions\n"
     "- Leitner system: simple box-based approach\n"
     "Optimal intervals increase exponentially with mastery.",
     ["learning-science", "memory"]),
    ("Transformer Architecture",
     "The Transformer (Vaswani et al., 2017) introduced self-attention.\n\nComponents:\n"
     "- Multi-head self-attention\n- Position-wise feed-forward networks\n"
     "- Layer normalization and residual connections\n"
     "- Positional encoding for sequence order",
     ["ai", "deep-learning"]),
    ("Active Recall Techniques",
     "Active recall forces retrieval from memory rather than passive review.\n\n"
     "Techniques:\n- Flashcards with self-testing\n- Free recall after reading\n"
     "- Practice problems without notes\n- Teaching concepts to others",
     ["learning-science", "memory"]),
    ("Vector Embeddings",
     "Embeddings map discrete tokens to continuous vector spaces.\n\nKey ideas:\n"
     "- Word2Vec: skip-gram and CBOW models\n"
     "- Sentence embeddings capture semantic meaning\n"
     "- Cosine similarity measures relatedness\n"
     "- Dense vectors enable nearest-neighbor search",
     ["ai", "rag"]),
    ("Metacognition in Learning",
     "Metacognition is thinking about thinking.\n\nComponents:\n"
     "- Self-monitoring: awareness of comprehension\n"
     "- Self-regulation: adjusting study strategies\n"
     "- Calibration: matching confidence to actual knowledge\n"
     "- Reflection: evaluating what worked and what didn't",
     ["learning-science", "psychology"]),
    ("Neural Network Basics",
     "Neural networks are composed of layers of interconnected neurons.\n\n"
     "Fundamentals:\n- Neurons apply weights, bias, and activation\n"
     "- Backpropagation computes gradients\n- SGD and Adam are common optimizers\n"
     "- Overfitting prevented by dropout and regularization",
     ["ai", "deep-learning"]),
    ("Forgetting Curve",
     "Ebbinghaus showed memory decays exponentially without review.\n\nKey findings:\n"
     "- ~50% forgotten within one hour\n- ~70% forgotten within 24 hours\n"
     "- Spaced review resets the curve\n- Each review extends retention duration",
     ["memory", "psychology"]),
    ("Prompt Engineering",
     "Designing effective prompts for large language models.\n\nStrategies:\n"
     "- Chain-of-thought reasoning\n- Few-shot examples in context\n"
     "- Role-based system prompts\n- Structured output formatting",
     ["ai", "rag"]),
    ("Interleaving Practice",
     "Mixing different topics during study sessions improves learning.\n\nBenefits:\n"
     "- Forces discrimination between concepts\n- Strengthens retrieval pathways\n"
     "- Better transfer to novel problems\n- Feels harder but produces lasting results",
     ["learning-science"]),
]

# Concept groups: the top level of the zoomable map
GROUPS = {
    "Learning Strategies": "#34d399",
    "Memory & Cognition": "#a78bfa",
    "Retrieval & LLMs": "#60a5fa",
    "Machine Learning": "#f472b6",
}

NOTE_GROUP = {
    "Desirable Difficulties in Learning": "Learning Strategies",
    "Active Recall Techniques": "Learning Strategies",
    "Interleaving Practice": "Learning Strategies",
    "Forgetting Curve": "Memory & Cognition",
    "Spaced Repetition Systems": "Memory & Cognition",
    "Metacognition in Learning": "Memory & Cognition",
    "RAG Pipeline Overview": "Retrieval & LLMs",
    "Vector Embeddings": "Retrieval & LLMs",
    "Prompt Engineering": "Retrieval & LLMs",
    "Neural Network Basics": "Machine Learning",
    "Transformer Architecture": "Machine Learning",
    "Knowledge Tracing Methods": "Machine Learning",
}

# Review histories: (days_ago, difficulty_level, correct)
_MASTERED = [(30, 1, True), (26, 2, True), (21, 3, True), (16, 3, True), (11, 4, True),
             (7, 4, True), (4, 4, True), (2, 4, True), (1, 4, True), (0.4, 4, True),
             (0.3, 4, True)]
_PROGRESSING = [(12, 1, True), (9, 2, True), (5, 2, True), (2, 3, True), (1, 3, False)]
_FADED = [(45, 1, True), (42, 2, True), (38, 3, True), (35, 3, True)]
_STRUGGLING = [(6, 1, True), (4, 2, False), (2, 2, False)]

NOTE_HISTORY = {
    "Desirable Difficulties in Learning": _MASTERED,
    "Active Recall Techniques": _MASTERED,
    "Neural Network Basics": _MASTERED[2:],
    "RAG Pipeline Overview": _PROGRESSING,
    "Vector Embeddings": _PROGRESSING,
    "Forgetting Curve": _FADED,
    "Knowledge Tracing Methods": _STRUGGLING,
    "Metacognition in Learning": _STRUGGLING,
    "Interleaving Practice": [(20, 1, True), (3, 2, False)],
    # Spaced Repetition, Transformer, Prompt Engineering: never practiced
}

# Connection histories between topics: (a, b, [(days_ago, correct), ...])
EDGE_HISTORY = [
    ("Desirable Difficulties in Learning", "Active Recall Techniques",
     [(21, True), (14, True), (7, True), (2, True), (0.4, True)]),          # strong, durable
    ("Active Recall Techniques", "Forgetting Curve",
     [(38, True), (35, True)]),                                               # long faded
    ("Desirable Difficulties in Learning", "Forgetting Curve",
     [(10, True), (6, True)]),                                                # fading
    ("RAG Pipeline Overview", "Vector Embeddings",
     [(5, True), (2, True), (1, True)]),                                      # recent, crammed
    ("Neural Network Basics", "Vector Embeddings",
     [(9, True), (3, False)]),                                                # weak after lapse
    ("Metacognition in Learning", "Active Recall Techniques",
     [(4, False)]),                                                           # failed once
    ("Desirable Difficulties in Learning", "Interleaving Practice",
     [(3, True)]),                                                            # single review
]

NEVER_PRACTICED_AGE_DAYS = 2  # makes untouched notes show up as cognitive debt


def seed(notes, tags, debt_tracker):
    """Populate notes and replay their review history. Mutates the given stores."""
    now = clock.now()
    for title, content, note_tags in SAMPLES:
        nid = note_id_for(title)
        history = NOTE_HISTORY.get(title, [])
        created_days_ago = max([h[0] for h in history], default=NEVER_PRACTICED_AGE_DAYS) + 1
        created = now - timedelta(days=created_days_ago)
        notes[nid] = {
            "id": nid, "title": title, "content": content, "tags": note_tags,
            "group": NOTE_GROUP[title],
            "mastery": "not_started", "created_at": created, "updated_at": created,
        }
        tags.update(note_tags)
        with clock.frozen_at(created):
            debt_tracker.register_node(nid, note_tags)

    events = []
    for title, history in NOTE_HISTORY.items():
        for days_ago, level, correct in history:
            events.append((days_ago, "note", (note_id_for(title), level, correct)))
    for a, b, history in EDGE_HISTORY:
        for days_ago, correct in history:
            events.append((days_ago, "edge", (note_id_for(a), note_id_for(b), correct)))

    # Replay oldest first so decay between reviews is applied correctly
    for days_ago, kind, payload in sorted(events, key=lambda e: -e[0]):
        with clock.frozen_at(now - timedelta(days=days_ago)):
            if kind == "note":
                nid, level, correct = payload
                apply_time_decay(nid)
                update_mastery(nid, level, correct)
                debt_tracker.record_engagement(nid)
            else:
                reinforce(*payload)

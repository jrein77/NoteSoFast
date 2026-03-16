"""
Offline TF-IDF cosine similarity engine for note recommendations.
Pure Python stdlib — no external dependencies.
"""
import re
import math
from collections import Counter


STOPWORDS = frozenset({
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'to', 'of', 'in', 'for',
    'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during',
    'before', 'after', 'and', 'but', 'or', 'nor', 'not', 'so', 'yet',
    'both', 'either', 'neither', 'each', 'every', 'all', 'any', 'few',
    'more', 'most', 'other', 'some', 'such', 'no', 'only', 'own', 'same',
    'than', 'too', 'very', 'just', 'because', 'this', 'that', 'these',
    'those', 'it', 'its', 'he', 'she', 'they', 'them', 'their', 'we',
    'our', 'you', 'your', 'what', 'which', 'who', 'whom', 'how', 'when',
    'where', 'why', 'if', 'then', 'else', 'about', 'up', 'out', 'off',
    'over', 'under', 'again', 'also', 'using', 'used', 'use', 'based',
})


def tokenize(text):
    """Simple word tokenizer: lowercase, split on non-alpha, remove stopwords."""
    words = re.findall(r'[a-z]+', text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def compute_tfidf(documents):
    """Compute TF-IDF vectors for a list of (id, text) tuples.
    Returns dict of {doc_id: {word: tfidf_score}}."""
    doc_tokens = {}
    for doc_id, text in documents:
        doc_tokens[doc_id] = tokenize(text)

    # Document frequency
    df = Counter()
    for tokens in doc_tokens.values():
        unique = set(tokens)
        for word in unique:
            df[word] += 1

    n_docs = len(documents)

    # TF-IDF vectors
    tfidf = {}
    for doc_id, tokens in doc_tokens.items():
        if not tokens:
            tfidf[doc_id] = {}
            continue
        tf = Counter(tokens)
        vec = {}
        for word, count in tf.items():
            tf_val = count / len(tokens)
            idf_val = math.log((n_docs + 1) / (df[word] + 1)) + 1
            vec[word] = tf_val * idf_val
        tfidf[doc_id] = vec

    return tfidf


def cosine_sim(vec_a, vec_b):
    """Compute cosine similarity between two sparse vectors (dicts)."""
    if not vec_a or not vec_b:
        return 0.0
    common = set(vec_a.keys()) & set(vec_b.keys())
    if not common:
        return 0.0
    dot = sum(vec_a[k] * vec_b[k] for k in common)
    mag_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
    mag_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def find_similar_pairs(notes_dict, threshold=0.15):
    """Find pairs of notes with cosine similarity above threshold.
    Returns list of (id1, id2, similarity_score) sorted by score desc."""
    documents = [
        (nid, n["title"] + " " + n["content"] + " " + " ".join(n["tags"]))
        for nid, n in notes_dict.items()
    ]
    tfidf = compute_tfidf(documents)

    ids = list(tfidf.keys())
    pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            sim = cosine_sim(tfidf[ids[i]], tfidf[ids[j]])
            if sim >= threshold:
                pairs.append((ids[i], ids[j], sim))

    return sorted(pairs, key=lambda x: -x[2])

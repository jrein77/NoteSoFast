"""
Offline TF-IDF cosine similarity engine for note recommendations.
Pure Python stdlib — no external dependencies.
"""

import re
import math
from collections import Counter


STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "because",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "he",
        "she",
        "they",
        "them",
        "their",
        "we",
        "our",
        "you",
        "your",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "if",
        "then",
        "else",
        "about",
        "up",
        "out",
        "off",
        "over",
        "under",
        "again",
        "also",
        "using",
        "used",
        "use",
        "based",
    }
)


def tokenize(text):
    """Simple word tokenizer: lowercase, split on non-alpha, remove stopwords."""
    words = re.findall(r"[a-z]+", text.lower())
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
    mag_a = math.sqrt(sum(v**2 for v in vec_a.values()))
    mag_b = math.sqrt(sum(v**2 for v in vec_b.values()))
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


# ---------------------------------------------------------------------------
# Keyword extraction for redaction (offline, no API calls)
# ---------------------------------------------------------------------------

def extract_redaction_targets(text, notes_dict=None, max_keywords=30, ratio=0.35):
    """Extract words and patterns to redact from text.

    Combines TF-IDF keyword extraction with pattern-based detection of
    names (capitalized words), numbers, percentages, and years.

    Args:
        text: The text to extract redaction targets from
        notes_dict: Optional dict of all notes for corpus-level IDF
        max_keywords: Hard cap on TF-IDF keywords
        ratio: Maximum fraction of content words from TF-IDF (default 35%)

    Returns a dict with:
        - keywords: list of lowercase TF-IDF keyword strings
        - patterns: list of regex pattern strings to also redact
    """
    keywords = set()
    patterns = []

    if not text.strip():
        return {"keywords": [], "patterns": []}

    # --- TF-IDF keywords ---
    if notes_dict and len(notes_dict) > 1:
        documents = [("target", text)]
        for nid, n in notes_dict.items():
            documents.append((nid, n.get("title", "") + " " + n.get("content", "")))
        tfidf = compute_tfidf(documents)
        target_vec = tfidf.get("target", {})
    else:
        tokens = tokenize(text)
        if not tokens:
            target_vec = {}
        else:
            tf = Counter(tokens)
            total = len(tokens)
            target_vec = {w: count / total for w, count in tf.items()}

    if target_vec:
        ranked = sorted(target_vec.items(), key=lambda x: -x[1])
        content_tokens = tokenize(text)
        unique_count = len(set(content_tokens))
        limit = min(max_keywords, max(3, int(unique_count * ratio)))

        for word, score in ranked:
            if len(word) < 3:
                continue
            keywords.add(word)
            if len(keywords) >= limit:
                break

    # --- Pattern-based: proper nouns / names ---
    # Capitalized words not at sentence start, multi-word names, abbreviations
    # Find capitalized words (excluding sentence starters)
    proper_nouns = set()
    lines = text.replace("\n", ". ").split(". ")
    for line in lines:
        words = line.split()
        # Skip first word (sentence start); check remaining for capitalization
        for w in words[1:]:
            clean = re.sub(r"[^a-zA-Z]", "", w)
            if clean and clean[0].isupper() and len(clean) >= 2:
                proper_nouns.add(clean)
    # Also catch abbreviations like BKT, RNN, FAISS, SM-2
    abbreviations = re.findall(r"\b[A-Z]{2,}(?:-\d+)?\b", text)
    for abbr in abbreviations:
        proper_nouns.add(abbr)

    # --- Pattern-based: numbers, percentages, years ---
    # Percentages like ~80%, 0.95, ~50%
    patterns.append(r"~?\d+(?:\.\d+)?%")
    # Years in parentheses like (2020), (2025)
    patterns.append(r"\(\d{4}\)")
    # Standalone years
    patterns.append(r"\b(?:19|20)\d{2}\b")
    # Numbers with decimals
    patterns.append(r"\b\d+(?:\.\d+)?\b")

    # Add proper nouns as exact-match patterns (case-sensitive)
    for pn in proper_nouns:
        patterns.append(r"\b" + re.escape(pn) + r"\b")

    return {
        "keywords": sorted(keywords),
        "patterns": patterns,
    }


# ---------------------------------------------------------------------------
# Paraphrase vs. verbatim detection
# ---------------------------------------------------------------------------

def _ngrams(tokens, n):
    """Generate n-grams from a token list."""
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def compute_text_overlap(response_text, source_text):
    """Compute overlap metrics between a user response and source material.

    Returns a dict with:
        - token_overlap: Jaccard similarity of unique tokens
        - bigram_overlap: Jaccard similarity of bigrams
        - trigram_overlap: Jaccard similarity of trigrams
        - longest_common_seq: length of longest common contiguous word sequence
        - verbatim_ratio: proportion of response tokens appearing in a contiguous
          source span (sliding window match)
        - is_verbatim: True if the response appears to be copied verbatim
        - is_paraphrase: True if substantial semantic overlap with low verbatim ratio
    """
    resp_tokens = tokenize(response_text)
    src_tokens = tokenize(source_text)

    if not resp_tokens or not src_tokens:
        return {
            "token_overlap": 0.0,
            "bigram_overlap": 0.0,
            "trigram_overlap": 0.0,
            "longest_common_seq": 0,
            "verbatim_ratio": 0.0,
            "is_verbatim": False,
            "is_paraphrase": False,
        }

    # Jaccard similarity on unique tokens
    resp_set = set(resp_tokens)
    src_set = set(src_tokens)
    union = resp_set | src_set
    token_overlap = len(resp_set & src_set) / len(union) if union else 0.0

    # Bigram and trigram overlap
    resp_bi = set(_ngrams(resp_tokens, 2))
    src_bi = set(_ngrams(src_tokens, 2))
    bi_union = resp_bi | src_bi
    bigram_overlap = len(resp_bi & src_bi) / len(bi_union) if bi_union else 0.0

    resp_tri = set(_ngrams(resp_tokens, 3))
    src_tri = set(_ngrams(src_tokens, 3))
    tri_union = resp_tri | src_tri
    trigram_overlap = len(resp_tri & src_tri) / len(tri_union) if tri_union else 0.0

    # Longest common contiguous subsequence
    longest = 0
    for i in range(len(resp_tokens)):
        for j in range(len(src_tokens)):
            k = 0
            while (
                i + k < len(resp_tokens)
                and j + k < len(src_tokens)
                and resp_tokens[i + k] == src_tokens[j + k]
            ):
                k += 1
            longest = max(longest, k)

    # Verbatim ratio: what fraction of response tokens appear in any contiguous
    # window of the source of the same length
    window_size = len(resp_tokens)
    best_window_match = 0.0
    if window_size <= len(src_tokens):
        for start in range(len(src_tokens) - window_size + 1):
            window = src_tokens[start : start + window_size]
            matches = sum(1 for a, b in zip(resp_tokens, window) if a == b)
            ratio = matches / window_size
            best_window_match = max(best_window_match, ratio)
    else:
        # Response is longer than source; check how much of source appears
        best_window_match = longest / len(resp_tokens) if resp_tokens else 0.0

    verbatim_ratio = best_window_match

    # Heuristic thresholds for classification
    # Verbatim: high trigram overlap AND high verbatim ratio
    is_verbatim = trigram_overlap > 0.5 or verbatim_ratio > 0.6 or longest >= 8
    # Paraphrase: moderate token overlap but low trigram/verbatim
    is_paraphrase = (
        token_overlap > 0.2
        and trigram_overlap < 0.35
        and verbatim_ratio < 0.5
        and not is_verbatim
    )

    return {
        "token_overlap": round(token_overlap, 4),
        "bigram_overlap": round(bigram_overlap, 4),
        "trigram_overlap": round(trigram_overlap, 4),
        "longest_common_seq": longest,
        "verbatim_ratio": round(verbatim_ratio, 4),
        "is_verbatim": is_verbatim,
        "is_paraphrase": is_paraphrase,
    }

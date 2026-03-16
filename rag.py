"""
RAG pipeline: paragraph-based chunking, sentence-transformer embeddings, FAISS indexing.
"""

import numpy as np

# Lazy-loaded globals
_model = None


def _get_model():
    """Load sentence-transformers model on first use."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def chunk_note(note_id, title, content, tags):
    """Split a note into paragraph-based chunks with metadata.

    First chunk is prefixed with title + tags for better retrieval.
    Short paragraphs (<50 chars) are merged with the next paragraph.
    """
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    # Merge short paragraphs with the next one
    merged = []
    buffer = ""
    for para in paragraphs:
        if buffer:
            buffer = buffer + "\n\n" + para
            if len(buffer) >= 50:
                merged.append(buffer)
                buffer = ""
        elif len(para) < 50 and para != paragraphs[-1]:
            buffer = para
        else:
            merged.append(para)
    if buffer:
        merged.append(buffer)

    # If no paragraphs resulted, use the whole content as one chunk
    if not merged:
        merged = [content.strip()] if content.strip() else [title]

    # Prefix first chunk with title + tags
    tag_str = ", ".join(tags) if tags else ""
    prefix = f"[{title}]"
    if tag_str:
        prefix += f" (tags: {tag_str})"
    merged[0] = prefix + " " + merged[0]

    chunks = []
    for i, text in enumerate(merged):
        chunks.append({
            "text": text,
            "note_id": note_id,
            "chunk_index": i,
        })
    return chunks


class RAGIndex:
    """In-memory FAISS index for semantic search over note chunks."""

    def __init__(self):
        self.faiss_index = None
        self.chunks_metadata = []  # Parallel list to FAISS rows
        self.note_chunk_map = {}   # note_id -> list of FAISS row indices
        self.note_titles = {}      # note_id -> title (for results)
        self._dead_count = 0

    def _embed(self, texts):
        """Encode texts into L2-normalized embeddings."""
        model = _get_model()
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.array(embeddings, dtype=np.float32)

    def add_note(self, note):
        """Chunk and index a single note."""
        import faiss

        note_id = note["id"]
        chunks = chunk_note(note_id, note["title"], note["content"], note["tags"])
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = self._embed(texts)

        # Initialize index on first add
        if self.faiss_index is None:
            dim = embeddings.shape[1]
            self.faiss_index = faiss.IndexFlatIP(dim)

        start_idx = self.faiss_index.ntotal
        self.faiss_index.add(embeddings)

        indices = []
        for i, chunk in enumerate(chunks):
            idx = start_idx + i
            self.chunks_metadata.append(chunk)
            indices.append(idx)

        self.note_chunk_map[note_id] = indices
        self.note_titles[note_id] = note["title"]

    def remove_note(self, note_id):
        """Mark a note's chunks as dead. Triggers rebuild if >20% dead."""
        if note_id not in self.note_chunk_map:
            return

        for idx in self.note_chunk_map[note_id]:
            if idx < len(self.chunks_metadata):
                self.chunks_metadata[idx] = None  # Mark as dead
                self._dead_count += 1

        del self.note_chunk_map[note_id]
        self.note_titles.pop(note_id, None)

        # Rebuild if too many dead entries
        total = len(self.chunks_metadata)
        if total > 0 and self._dead_count / total > 0.2:
            self._compact()

    def _compact(self):
        """Rebuild index from live chunks only."""
        import faiss

        live_chunks = [c for c in self.chunks_metadata if c is not None]
        if not live_chunks:
            self.faiss_index = None
            self.chunks_metadata = []
            self.note_chunk_map = {}
            self._dead_count = 0
            return

        texts = [c["text"] for c in live_chunks]
        embeddings = self._embed(texts)

        dim = embeddings.shape[1]
        self.faiss_index = faiss.IndexFlatIP(dim)
        self.faiss_index.add(embeddings)

        self.chunks_metadata = live_chunks
        self._dead_count = 0

        # Rebuild note_chunk_map
        self.note_chunk_map = {}
        for i, chunk in enumerate(self.chunks_metadata):
            nid = chunk["note_id"]
            if nid not in self.note_chunk_map:
                self.note_chunk_map[nid] = []
            self.note_chunk_map[nid].append(i)

    def rebuild(self, notes_dict):
        """Full rebuild from all notes."""
        import faiss

        self.faiss_index = None
        self.chunks_metadata = []
        self.note_chunk_map = {}
        self.note_titles = {}
        self._dead_count = 0

        all_chunks = []
        for note in notes_dict.values():
            chunks = chunk_note(note["id"], note["title"], note["content"], note["tags"])
            all_chunks.extend(chunks)
            self.note_titles[note["id"]] = note["title"]

        if not all_chunks:
            return

        texts = [c["text"] for c in all_chunks]
        embeddings = self._embed(texts)

        dim = embeddings.shape[1]
        self.faiss_index = faiss.IndexFlatIP(dim)
        self.faiss_index.add(embeddings)

        self.chunks_metadata = all_chunks
        for i, chunk in enumerate(self.chunks_metadata):
            nid = chunk["note_id"]
            if nid not in self.note_chunk_map:
                self.note_chunk_map[nid] = []
            self.note_chunk_map[nid].append(i)

    def query(self, query_text, top_k=5):
        """Retrieve top-k most similar chunks for a query.

        Returns list of {text, note_id, note_title, score}.
        Deduplicates by note_id (keeps highest-scoring chunk per note).
        """
        if self.faiss_index is None or self.faiss_index.ntotal == 0:
            return []

        query_embedding = self._embed([query_text])
        k = min(top_k * 3, self.faiss_index.ntotal)  # Over-fetch to handle dead/dupes
        scores, indices = self.faiss_index.search(query_embedding, k)

        seen_notes = set()
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.chunks_metadata):
                continue
            chunk = self.chunks_metadata[idx]
            if chunk is None:  # Dead entry
                continue
            nid = chunk["note_id"]
            if nid in seen_notes:
                continue
            seen_notes.add(nid)
            results.append({
                "text": chunk["text"],
                "note_id": nid,
                "note_title": self.note_titles.get(nid, "Unknown"),
                "score": float(score),
            })
            if len(results) >= top_k:
                break

        return results

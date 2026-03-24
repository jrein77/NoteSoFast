"""
LLM integration: Anthropic Claude API for RAG response generation.
"""

import os

_client = None


def _get_client():
    """Initialize Anthropic client on first use."""
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1024


def _format_chunks(chunks):
    """Format retrieved chunks into a context block for the prompt."""
    if not chunks:
        return "No relevant notes found."
    parts = []
    for i, chunk in enumerate(chunks, 1):
        parts.append(f"[Source {i}: {chunk['note_title']}]\n{chunk['text']}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Query page: standalone RAG response
# ---------------------------------------------------------------------------

QUERY_SYSTEM_PROMPT = """You are an educational assistant for a Personal Knowledge Management system called NoteSoFast. \
You help users understand and recall information from their personal notes.

You are given context retrieved from the user's notes. Use ONLY this context to answer. \
If the context doesn't contain enough information, say so honestly. \
Keep responses concise and focused."""

QUERY_MODE_INSTRUCTIONS = {
    "direct": "Answer the user's question directly using the provided context. Be clear and concise.",
    "question": (
        "Instead of answering the question, generate a retrieval practice question that would help "
        "the user actively recall the relevant information from memory. Frame it as a challenge. "
        "Do NOT reveal the answer."
    ),
    "hints": (
        "Instead of answering directly, provide the first hint in a series of progressive hints "
        "that would guide the user toward the answer. Start broad, don't give away the answer. "
        "End by asking the user to try answering with this hint."
    ),
}


def generate_rag_response(query, chunks, mode="direct"):
    """Generate a response for the /query page.

    Args:
        query: User's question text
        chunks: List of {text, note_id, note_title, score} from RAG retrieval
        mode: One of "direct", "question", "hints"

    Returns:
        Response text string
    """
    client = _get_client()
    if client is None:
        return (
            "LLM is not configured. Add your ANTHROPIC_API_KEY to the .env file "
            "to enable AI-powered responses."
        )

    context = _format_chunks(chunks)
    mode_instruction = QUERY_MODE_INSTRUCTIONS.get(mode, QUERY_MODE_INSTRUCTIONS["direct"])

    user_message = f"""## Retrieved Context
{context}

## Instruction
{mode_instruction}

## User Question
{query}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=QUERY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
    except Exception as e:
        return f"Error generating response: {str(e)}"


# ---------------------------------------------------------------------------
# Chat page: conversational tutoring with note context
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """You are a tutoring assistant in NoteSoFast, a Personal Knowledge Management system \
that uses "desirable difficulties" to strengthen learning.

You are chatting with a student about a specific note from their knowledge base. \
Your goal is to help them deeply understand and retain the material — not just give them answers.

Guidelines:
- Use the retrieved context from their notes to ground your responses
- Be encouraging but push for deeper understanding
- Keep responses concise (2-4 sentences typically)
- If the student's answer is partially correct, acknowledge what's right and probe the gaps
- Never be condescending; treat the student as capable"""

CHAT_MODE_INSTRUCTIONS = {
    "auto": (
        "Respond naturally based on the conversation. If the student is recalling well, "
        "push to a harder level. If struggling, offer gentle guidance without giving the answer."
    ),
    "direct": (
        "Provide a direct, informative answer using the note context. "
        "The student has requested a direct response."
    ),
    "retrieval": (
        "Ask the student a retrieval practice question about the topic. "
        "Do NOT reveal information — make them recall from memory. "
        "If they just answered a question, evaluate their response and ask a follow-up."
    ),
    "hints": (
        "Guide the student with progressive hints. Don't give the answer. "
        "Start with a broad hint and get more specific only if they're struggling. "
        "Ask them to try after each hint."
    ),
}


def generate_chat_response(note, history, user_msg, chunks, mode="auto"):
    """Generate a chat response for the /notes/<id>/chat endpoint.

    Args:
        note: Dict with note title, content, tags
        history: List of {role, content} message dicts
        user_msg: The latest user message
        chunks: Retrieved context chunks from RAG
        mode: One of "auto", "direct", "retrieval", "hints"

    Returns:
        Response text string
    """
    client = _get_client()
    if client is None:
        return (
            "LLM is not configured. Add your ANTHROPIC_API_KEY to the .env file "
            "to enable AI-powered responses."
        )

    context = _format_chunks(chunks)
    mode_instruction = CHAT_MODE_INSTRUCTIONS.get(mode, CHAT_MODE_INSTRUCTIONS["auto"])

    tag_str = ", ".join(note.get("tags", []))
    system = f"""{CHAT_SYSTEM_PROMPT}

## Current Note
Title: {note['title']}
Tags: {tag_str}

## Retrieved Context from Notes
{context}

## Response Mode
{mode_instruction}"""

    # Build conversation messages for the API
    messages = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["content"]})

    # Add the current user message
    messages.append({"role": "user", "content": user_msg})

    # Ensure conversation starts with user message (API requirement)
    # If first message is from assistant (the initial AI prompt), prepend a synthetic user turn
    if messages and messages[0]["role"] == "assistant":
        messages.insert(0, {"role": "user", "content": "Let's begin."})

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        return f"Error generating response: {str(e)}"


# ---------------------------------------------------------------------------
# Answer evaluation: grade user responses for knowledge tracing
# ---------------------------------------------------------------------------

EVAL_SYSTEM_PROMPT = """You are an answer evaluator for an adaptive tutoring system. \
Your job is to assess whether a student's answer demonstrates genuine understanding \
of the source material.

You must distinguish between:
- Correct understanding (explained in their own words)
- Exact copying (memorized verbatim without understanding)
- Partial understanding (some concepts correct, gaps remain)
- Incorrect (wrong or irrelevant answer)

Respond in EXACTLY this JSON format, no other text:
{"correct": true/false, "partial": true/false, "feedback": "brief feedback"}

Rules for "correct":
- true if the answer captures the key ideas, even if wording differs
- false if the answer is wrong, too vague, or copied verbatim without elaboration
For "partial":
- true if some parts are right but important pieces are missing
- false otherwise"""


def evaluate_response(user_answer, source_chunks, question):
    """Evaluate a user's answer against source material.

    Args:
        user_answer: The user's response text
        source_chunks: List of {text, note_id, note_title, score} from RAG
        question: The question that was asked

    Returns:
        Dict with keys: correct (bool), partial (bool), feedback (str)
    """
    import json as _json

    client = _get_client()
    if client is None:
        return {"correct": True, "partial": False, "feedback": ""}

    context = _format_chunks(source_chunks)

    prompt = f"""## Question Asked
{question}

## Student's Answer
{user_answer}

## Source Material (ground truth)
{context}

Evaluate the student's answer. Respond in the required JSON format."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=256,
            system=EVAL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        result = _json.loads(text)
        return {
            "correct": bool(result.get("correct", False)),
            "partial": bool(result.get("partial", False)),
            "feedback": str(result.get("feedback", "")),
        }
    except Exception:
        # Fallback: assume partial correctness to avoid penalizing on eval errors
        return {"correct": False, "partial": True, "feedback": ""}

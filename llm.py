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
{"correct": true/false, "partial": true/false, "verbatim": true/false, "feedback": "brief feedback"}

Rules for "correct":
- true if the answer captures the key ideas, even if wording differs
- false if the answer is wrong, too vague, or copied verbatim without elaboration
For "partial":
- true if some parts are right but important pieces are missing
- false otherwise
For "verbatim":
- true if the answer appears to be copied directly from the source with little to no rephrasing
- false if the student used their own words, even if the ideas match"""


def evaluate_response(user_answer, source_chunks, question, overlap_stats=None):
    """Evaluate a user's answer against source material.

    Combines LLM semantic evaluation with optional text-overlap statistics
    from the similarity module to detect verbatim copying vs. paraphrase.

    Args:
        user_answer: The user's response text
        source_chunks: List of {text, note_id, note_title, score} from RAG
        question: The question that was asked
        overlap_stats: Optional dict from similarity.compute_text_overlap()

    Returns:
        Dict with keys: correct (bool), partial (bool), verbatim (bool),
                        feedback (str), overlap (dict|None)
    """
    import json as _json

    client = _get_client()
    if client is None:
        return {
            "correct": True, "partial": False, "verbatim": False,
            "feedback": "", "overlap": overlap_stats,
        }

    context = _format_chunks(source_chunks)

    # Include overlap hint for the LLM when available
    overlap_hint = ""
    if overlap_stats:
        overlap_hint = (
            f"\n\n## Text Overlap Analysis (automated)\n"
            f"Token overlap: {overlap_stats['token_overlap']:.0%}, "
            f"Trigram overlap: {overlap_stats['trigram_overlap']:.0%}, "
            f"Longest common sequence: {overlap_stats['longest_common_seq']} words, "
            f"Verbatim ratio: {overlap_stats['verbatim_ratio']:.0%}\n"
            f"Automated verdict: {'VERBATIM' if overlap_stats['is_verbatim'] else 'PARAPHRASE' if overlap_stats['is_paraphrase'] else 'UNCLEAR'}\n"
            f"Use this data to help inform your verbatim assessment, but apply your own judgment."
        )

    prompt = f"""## Question Asked
{question}

## Student's Answer
{user_answer}

## Source Material (ground truth)
{context}{overlap_hint}

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

        llm_verbatim = bool(result.get("verbatim", False))
        # Combine LLM and statistical verbatim detection
        if overlap_stats and overlap_stats["is_verbatim"]:
            llm_verbatim = True

        is_correct = bool(result.get("correct", False))
        # Verbatim copying is not genuine understanding
        if llm_verbatim and is_correct:
            is_correct = False

        return {
            "correct": is_correct,
            "partial": bool(result.get("partial", False)),
            "verbatim": llm_verbatim,
            "feedback": str(result.get("feedback", "")),
            "overlap": overlap_stats,
        }
    except Exception:
        return {
            "correct": False, "partial": True, "verbatim": False,
            "feedback": "", "overlap": overlap_stats,
        }


# ---------------------------------------------------------------------------
# Generation-based assessment evaluation (Feynman Technique)
# ---------------------------------------------------------------------------

GENERATION_EVAL_SYSTEM_PROMPT = """You are evaluating a student's explanation of a concept \
from their notes. The student was asked to explain the concept in their own words \
(Feynman Technique). Your job is to assess the quality of their explanation.

Evaluate along these dimensions:
1. Accuracy: Does the explanation correctly represent the source material?
2. Completeness: Are the key ideas covered?
3. Originality: Is this in the student's own words (not copied)?
4. Depth: Does the explanation show genuine understanding beyond surface recall?
5. Clarity: Would someone unfamiliar with the topic understand this?

Respond in EXACTLY this JSON format, no other text:
{"correct": true/false, "partial": true/false, "verbatim": true/false, "depth": "shallow"/"moderate"/"deep", "feedback": "brief constructive feedback"}

Rules:
- "correct" = true if the explanation is accurate and covers key ideas
- "partial" = true if some ideas are right but significant gaps exist
- "verbatim" = true if the explanation is mostly copied from source
- "depth": "shallow" = definitions only, "moderate" = some reasoning, "deep" = analogies/examples/connections"""


def evaluate_generation(user_explanation, source_chunks, prompt_text, overlap_stats=None):
    """Evaluate a generation-based (Feynman Technique) explanation.

    Args:
        user_explanation: The user's explanation text
        source_chunks: Source material chunks for comparison
        prompt_text: The generation prompt that was given
        overlap_stats: Optional dict from similarity.compute_text_overlap()

    Returns:
        Dict with: correct, partial, verbatim, depth, feedback, overlap
    """
    import json as _json

    client = _get_client()
    if client is None:
        return {
            "correct": True, "partial": False, "verbatim": False,
            "depth": "moderate", "feedback": "", "overlap": overlap_stats,
        }

    context = _format_chunks(source_chunks)

    overlap_hint = ""
    if overlap_stats:
        overlap_hint = (
            f"\n\n## Text Overlap Analysis (automated)\n"
            f"Token overlap: {overlap_stats['token_overlap']:.0%}, "
            f"Trigram overlap: {overlap_stats['trigram_overlap']:.0%}, "
            f"Longest common sequence: {overlap_stats['longest_common_seq']} words, "
            f"Verbatim ratio: {overlap_stats['verbatim_ratio']:.0%}\n"
            f"Automated verdict: {'VERBATIM' if overlap_stats['is_verbatim'] else 'PARAPHRASE' if overlap_stats['is_paraphrase'] else 'UNCLEAR'}"
        )

    prompt = f"""## Prompt Given to Student
{prompt_text}

## Student's Explanation
{user_explanation}

## Source Material (ground truth)
{context}{overlap_hint}

Evaluate the student's explanation. Respond in the required JSON format."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=384,
            system=GENERATION_EVAL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        result = _json.loads(text)

        llm_verbatim = bool(result.get("verbatim", False))
        if overlap_stats and overlap_stats["is_verbatim"]:
            llm_verbatim = True

        is_correct = bool(result.get("correct", False))
        if llm_verbatim and is_correct:
            is_correct = False

        return {
            "correct": is_correct,
            "partial": bool(result.get("partial", False)),
            "verbatim": llm_verbatim,
            "depth": str(result.get("depth", "shallow")),
            "feedback": str(result.get("feedback", "")),
            "overlap": overlap_stats,
        }
    except Exception:
        return {
            "correct": False, "partial": True, "verbatim": False,
            "depth": "shallow", "feedback": "", "overlap": overlap_stats,
        }

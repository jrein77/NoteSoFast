"""
Question generation module: Level 1 (cued recall) and Level 2 (free recall)
question generation using LLM with structured prompt templates.
"""

from llm import _get_client, _format_chunks, MODEL, MAX_TOKENS


QUESTION_SYSTEM_PROMPT = """You are a question generator for NoteSoFast, an adaptive tutoring system. \
Your job is to create targeted retrieval practice questions from the user's personal notes. \
Generate exactly ONE question. Do not answer the question. Do not include the answer."""


def generate_level1_question(note, chunks):
    """Generate a Level 1 (cued recall) question.

    Cued recall provides recognition-style prompts: fill-in-the-blank,
    true/false, or "which of these" questions that give the user partial
    information to trigger recall.

    Args:
        note: Dict with note title, content, tags
        chunks: Retrieved context chunks from RAG

    Returns:
        Question text string
    """
    client = _get_client()
    if client is None:
        return (
            f"Let's start with a warm-up on '{note['title']}'. "
            f"Can you tell me what this topic is generally about?"
        )

    context = _format_chunks(chunks)
    tag_str = ", ".join(note.get("tags", []))

    prompt = f"""## Source Material
Title: {note['title']}
Tags: {tag_str}

{context}

## Task
Generate a Level 1 (cued recall) question about this material. Use ONE of these formats:
- Fill-in-the-blank: Provide a sentence from the material with a key term blanked out
- True/False: Make a statement that is either true or a plausible misconception
- Recognition: "Which of the following best describes..." with 3-4 short options (mark none as correct)

The question should test basic factual recall. Provide enough context clues that someone \
who studied the material could recall the answer, but not so much that no retrieval is needed.

Output ONLY the question, nothing else."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=QUESTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        return f"Can you recall a key concept from '{note['title']}'?"


def generate_level2_question(note, chunks):
    """Generate a Level 2 (free recall) question.

    Free recall requires open-ended retrieval with no cues: the user must
    explain, list, or describe concepts entirely from memory.

    Args:
        note: Dict with note title, content, tags
        chunks: Retrieved context chunks from RAG

    Returns:
        Question text string
    """
    client = _get_client()
    if client is None:
        return (
            f"In your own words, explain the main concepts from '{note['title']}'. "
            f"Try to be specific without looking at your notes."
        )

    context = _format_chunks(chunks)
    tag_str = ", ".join(note.get("tags", []))

    prompt = f"""## Source Material
Title: {note['title']}
Tags: {tag_str}

{context}

## Task
Generate a Level 2 (free recall) question about this material. Use ONE of these formats:
- Open explanation: "Explain [concept] in your own words"
- Listing from memory: "What are the key [components/steps/principles] of [topic]?"
- Comparison: "How does [concept A] differ from [concept B]?"
- Cause/effect: "Why does [phenomenon] occur?"

The question should require genuine retrieval from memory — do NOT provide any cues, \
hints, options, or partial information. The user must recall the information entirely on their own.

Output ONLY the question, nothing else."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=QUESTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        return (
            f"Without looking at your notes, explain the main ideas "
            f"from '{note['title']}' in your own words."
        )


def generate_question(note, chunks, difficulty_level):
    """Generate a question at the specified difficulty level.

    Args:
        note: Dict with note title, content, tags
        chunks: Retrieved context chunks from RAG
        difficulty_level: 1 (cued recall) or 2 (free recall)

    Returns:
        Question text string
    """
    if difficulty_level <= 1:
        return generate_level1_question(note, chunks)
    else:
        return generate_level2_question(note, chunks)

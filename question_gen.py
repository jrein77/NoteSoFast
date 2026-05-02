"""
Question generation module: Levels 1–4 question generation and generation-based
assessment using LLM with structured prompt templates.

Levels:
  1 — Cued recall (fill-in-blank, T/F, recognition)
  2 — Free recall (open explanation, listing, comparison)
  3 — Application (apply to novel scenario, problem-solving, cross-concept)
  4 — Synthesis / Interleaving (integrate multiple topics, create, evaluate)
"""

from llm import _get_client, _format_chunks, MODEL, MAX_TOKENS
import mock_llm


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
        # --- mock-mode branch (was: generic warm-up string) ---
        # return (
        #     f"Let's start with a warm-up on '{note['title']}'. "
        #     f"Can you tell me what this topic is generally about?"
        # )
        return mock_llm.mock_level1_question(note, chunks)

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
        # --- mock-mode branch (was: generic free-recall string) ---
        # return (
        #     f"In your own words, explain the main concepts from '{note['title']}'. "
        #     f"Try to be specific without looking at your notes."
        # )
        return mock_llm.mock_level2_question(note, chunks)

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


def generate_level3_question(note, chunks, related_notes=None):
    """Generate a Level 3 (application) question.

    Application questions require the user to apply concepts to a new scenario,
    solve a problem using the material, or connect ideas across related topics.

    Args:
        note: Dict with note title, content, tags
        chunks: Retrieved context chunks from RAG
        related_notes: Optional list of related note dicts for cross-concept questions

    Returns:
        Question text string
    """
    client = _get_client()
    if client is None:
        # --- mock-mode branch (was: generic application string) ---
        # return (
        #     f"Imagine you're explaining '{note['title']}' to solve a real-world problem. "
        #     f"Describe a scenario where these concepts apply and how you'd use them."
        # )
        return mock_llm.mock_level3_question(note, chunks, related_notes)

    context = _format_chunks(chunks)
    tag_str = ", ".join(note.get("tags", []))

    related_context = ""
    if related_notes:
        related_parts = []
        for rn in related_notes[:2]:
            related_parts.append(f"- {rn['title']}: {rn['content'][:200]}")
        related_context = (
            "\n\n## Related Topics (for cross-concept questions)\n"
            + "\n".join(related_parts)
        )

    prompt = f"""## Source Material
Title: {note['title']}
Tags: {tag_str}

{context}{related_context}

## Task
Generate a Level 3 (application) question about this material. Use ONE of these formats:
- Scenario-based: "Given [realistic scenario], how would you apply [concept] to [goal]?"
- Problem-solving: "A system exhibits [symptom]. Using your knowledge of [topic], diagnose the issue."
- Cross-concept: "How does [concept A] from this topic relate to or interact with [concept B]?"
- Transfer: "If you had to adapt [method/principle] for a different domain, what would change?"

The question MUST require applying knowledge to a new situation — not just recalling facts. \
The user should need to reason about the material, not repeat it.

Output ONLY the question, nothing else."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=QUESTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception:
        return (
            f"Think of a real-world scenario where the concepts from "
            f"'{note['title']}' would apply. How would you use them?"
        )


def generate_level4_question(note, chunks, related_notes=None):
    """Generate a Level 4 (synthesis / interleaving) question.

    Synthesis questions require integrating ideas across multiple topics,
    evaluating trade-offs, creating novel connections, or critiquing approaches.

    Args:
        note: Dict with note title, content, tags
        chunks: Retrieved context chunks from RAG
        related_notes: Optional list of related note dicts for interleaving

    Returns:
        Question text string
    """
    client = _get_client()
    if client is None:
        # --- mock-mode branch (was: generic synthesis string) ---
        # return (
        #     f"Synthesize the key ideas from '{note['title']}' with related concepts "
        #     f"you've studied. What new insight emerges from combining them?"
        # )
        return mock_llm.mock_level4_question(note, chunks, related_notes)

    context = _format_chunks(chunks)
    tag_str = ", ".join(note.get("tags", []))

    related_context = ""
    if related_notes:
        related_parts = []
        for rn in related_notes[:3]:
            related_parts.append(
                f"- {rn['title']} (tags: {', '.join(rn.get('tags', []))}): "
                f"{rn['content'][:250]}"
            )
        related_context = (
            "\n\n## Related Topics for Interleaving\n"
            + "\n".join(related_parts)
        )

    prompt = f"""## Source Material
Title: {note['title']}
Tags: {tag_str}

{context}{related_context}

## Task
Generate a Level 4 (synthesis/interleaving) question about this material. Use ONE of these formats:
- Integration: "How would you combine [concept A] and [concept B] to design/build [something new]?"
- Evaluation: "Compare the strengths and limitations of [approach X] vs [approach Y] for [goal]."
- Creative synthesis: "Design a [system/approach/framework] that incorporates principles from [topic A] and [topic B]."
- Critical analysis: "What are the potential failure modes of [approach] and how might [related concept] address them?"
- Interleaving: "How do the principles of [topic from related note] complement or contradict [topic from main note]?"

The question MUST require synthesizing across multiple concepts or topics — not just applying a single idea. \
Push the user to think at a higher level: evaluate, create, connect, or critique.

{"If related topics are provided, prefer questions that interleave concepts across them." if related_notes else "Focus on synthesizing different aspects within this topic."}

Output ONLY the question, nothing else."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=QUESTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception:
        return (
            f"How would you combine ideas from '{note['title']}' with other concepts "
            f"you've studied to create something new or solve a complex problem?"
        )


def generate_generation_prompt(note, chunks):
    """Generate a generation-based assessment prompt (Feynman Technique).

    Asks the user to explain a concept in their own words as if teaching
    someone else. The response is later evaluated for semantic similarity
    to the source material, distinguishing paraphrase from verbatim copying.

    Args:
        note: Dict with note title, content, tags
        chunks: Retrieved context chunks from RAG

    Returns:
        Prompt text string
    """
    client = _get_client()
    if client is None:
        # --- mock-mode branch (was: generic Feynman-prompt string) ---
        # return (
        #     f"Explain the core ideas from '{note['title']}' in your own words, "
        #     f"as if you were teaching someone who has never encountered this topic."
        # )
        return mock_llm.mock_generation_prompt(note, chunks)

    context = _format_chunks(chunks)
    tag_str = ", ".join(note.get("tags", []))

    prompt = f"""## Source Material
Title: {note['title']}
Tags: {tag_str}

{context}

## Task
Generate a generation-based assessment prompt using the Feynman Technique. \
Ask the user to explain a specific concept from the material in their own words, \
as if teaching it to someone unfamiliar with the topic.

Choose ONE specific concept or idea from the material (not the entire topic). \
The prompt should:
- Name the specific concept to explain
- Ask them to use their own words (not copy from notes)
- Suggest they use analogies or examples if helpful
- Be encouraging but set a clear expectation of depth

Example format: "In your own words, explain [specific concept]. Imagine you're \
teaching this to a friend who has no background in [field]. Try to use an analogy \
or concrete example to make it clear."

Output ONLY the prompt, nothing else."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=QUESTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception:
        return (
            f"In your own words, explain the core ideas from '{note['title']}'. "
            f"Pretend you're teaching someone who has no background in this area. "
            f"Use analogies or examples if it helps."
        )


def generate_question(note, chunks, difficulty_level, related_notes=None):
    """Generate a question at the specified difficulty level.

    Args:
        note: Dict with note title, content, tags
        chunks: Retrieved context chunks from RAG
        difficulty_level: 1 (cued recall), 2 (free recall), 3 (application), 4 (synthesis)
        related_notes: Optional list of related note dicts (used for levels 3–4)

    Returns:
        Question text string
    """
    if difficulty_level <= 1:
        return generate_level1_question(note, chunks)
    elif difficulty_level == 2:
        return generate_level2_question(note, chunks)
    elif difficulty_level == 3:
        return generate_level3_question(note, chunks, related_notes)
    else:
        return generate_level4_question(note, chunks, related_notes)

document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const messagesContainer = document.getElementById('chat-messages');
    const noteId = window.CHAT_NOTE_ID;
    const hintBtn = document.getElementById('hint-btn');

    if (!form || !input || !messagesContainer || !noteId) return;

    // Scroll to bottom on load
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    // Auto-resize textarea: grows up to ~4 rows, then scrolls
    var MAX_HEIGHT = 120; // ~4 rows
    function autoResize() {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, MAX_HEIGHT) + 'px';
        input.style.overflowY = input.scrollHeight > MAX_HEIGHT ? 'auto' : 'hidden';
    }
    input.addEventListener('input', autoResize);

    // Enter sends, Shift+Enter adds newline
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.dispatchEvent(new Event('submit', { cancelable: true }));
        }
    });

    // --- Hint state ---
    var hintActive = false;
    var lastHintLevel = 0;
    var hintResponsePending = false; // true when waiting for user to respond to a Socratic hint

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const message = input.value.trim();
        if (!message) return;

        // If a Socratic hint response is pending, send it to the hint API instead
        if (hintResponsePending) {
            await submitHintResponse(message);
            return;
        }

        // Add user message to UI
        appendMessage('user', message);
        input.value = '';
        autoResize();
        input.focus();

        // Reset hint state when user submits a normal answer
        hintActive = false;
        lastHintLevel = 0;
        hintResponsePending = false;
        if (hintBtn) {
            hintBtn.title = 'Get a hint';
            hintBtn.disabled = false;
        }

        // Mode is always auto (dropdown removed)
        const mode = 'auto';

        // Show thinking indicator
        const thinkingDiv = document.createElement('div');
        thinkingDiv.className = 'chat-message chat-message--ai';
        thinkingDiv.innerHTML = '<div class="chat-bubble chat-bubble--ai chat-bubble--thinking">Thinking\u2026</div>';
        messagesContainer.appendChild(thinkingDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        // Send to backend
        try {
            const response = await fetch('/notes/' + noteId + '/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message, mode: mode }),
            });
            thinkingDiv.remove();
            const data = await response.json();
            appendMessage('ai', data.response);

            // Update mastery and difficulty indicators if present
            if (data.mastery_value !== undefined) {
                updateMasteryDisplay(data.mastery, data.mastery_value, data.difficulty_level);
            }
            // Show verbatim warning badge if detected
            if (data.evaluation && data.evaluation.verbatim) {
                showVerbatimBadge();
            }
        } catch (err) {
            thinkingDiv.remove();
            appendMessage('ai', 'Sorry, something went wrong. Please try again.');
        }
    });

    // --- Hint button handler ---
    if (hintBtn) {
        hintBtn.addEventListener('click', async function () {
            hintBtn.disabled = true;

            // Show thinking indicator
            var thinkingDiv = document.createElement('div');
            thinkingDiv.className = 'chat-message chat-message--ai';
            thinkingDiv.innerHTML = '<div class="chat-bubble chat-bubble--ai chat-bubble--thinking">Generating hint\u2026</div>';
            messagesContainer.appendChild(thinkingDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;

            try {
                var body = { note_id: noteId };
                var response = await fetch('/api/hint', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                thinkingDiv.remove();
                var data = await response.json();

                if (data.error && data.exhausted) {
                    appendMessage('ai', 'All hints have been given. Try answering the question or move on.');
                    hintBtn.disabled = true;
                    return;
                }
                if (data.error) {
                    appendMessage('ai', 'Could not generate hint: ' + data.error);
                    hintBtn.disabled = false;
                    return;
                }

                hintActive = true;
                lastHintLevel = data.level;

                // Build hint message
                var levelLabel = 'Hint Level ' + data.level;
                if (data.is_reveal) {
                    levelLabel += ' (Answer Revealed)';
                }
                var hintText = levelLabel + '\n\n' + data.text;

                if (data.is_question && !data.is_reveal) {
                    hintText += '\n\n(You can type a response below, or click "Get a Hint" for the next hint)';
                    hintResponsePending = true;
                    input.placeholder = 'Respond to the hint question, or click next hint to skip...';
                } else {
                    hintResponsePending = false;
                    input.placeholder = 'Type your answer...';
                }

                appendHintMessage(data.level, data.text, data.is_question, data.is_reveal);

                // Update mastery display
                if (data.mastery_value !== undefined) {
                    updateMasteryDisplay(data.mastery, data.mastery_value);
                }

                // Update button state
                if (data.is_reveal || data.hints_remaining === 0) {
                    hintBtn.title = 'Answer revealed';
                    hintBtn.disabled = true;
                    hintResponsePending = false;
                    input.placeholder = 'Type your answer...';
                } else {
                    hintBtn.title = 'Next hint (' + data.hints_remaining + ' left)';
                    hintBtn.disabled = false;
                }
            } catch (err) {
                thinkingDiv.remove();
                appendMessage('ai', 'Sorry, something went wrong with the hint. Please try again.');
                hintBtn.disabled = false;
            }
        });
    }

    async function submitHintResponse(response) {
        appendMessage('user', response);
        input.value = '';
        autoResize();
        input.focus();

        // Show thinking indicator
        var thinkingDiv = document.createElement('div');
        thinkingDiv.className = 'chat-message chat-message--ai';
        thinkingDiv.innerHTML = '<div class="chat-bubble chat-bubble--ai chat-bubble--thinking">Evaluating\u2026</div>';
        messagesContainer.appendChild(thinkingDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        try {
            var fetchResponse = await fetch('/api/hint', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ note_id: noteId, hint_response: response }),
            });
            thinkingDiv.remove();
            var data = await fetchResponse.json();

            // Show recovery feedback if present
            if (data.mastery_recovery) {
                var recoveryMsg = data.mastery_recovery.feedback;
                if (data.mastery_recovery.above_threshold) {
                    recoveryMsg += ' (Partial mastery recovered!)';
                }
                appendSystemMessage(recoveryMsg);
            }

            if (data.error && data.exhausted) {
                appendMessage('ai', 'All hints have been given. Try answering the question or move on.');
                hintBtn.disabled = true;
                hintResponsePending = false;
                input.placeholder = 'Type your answer...';
                return;
            }

            // Show the next hint
            if (data.text) {
                appendHintMessage(data.level, data.text, data.is_question, data.is_reveal);

                if (data.is_question && !data.is_reveal) {
                    hintResponsePending = true;
                    input.placeholder = 'Respond to the hint question, or click next hint to skip...';
                } else {
                    hintResponsePending = false;
                    input.placeholder = 'Type your answer...';
                }

                // Update mastery display
                if (data.mastery_value !== undefined) {
                    updateMasteryDisplay(data.mastery, data.mastery_value);
                }

                // Update button
                if (data.is_reveal || data.hints_remaining === 0) {
                    hintBtn.title = 'Answer revealed';
                    hintBtn.disabled = true;
                    hintResponsePending = false;
                    input.placeholder = 'Type your answer...';
                } else {
                    hintBtn.title = 'Next hint (' + data.hints_remaining + ' left)';
                    hintBtn.disabled = false;
                }
            }
        } catch (err) {
            thinkingDiv.remove();
            appendMessage('ai', 'Sorry, something went wrong. Please try again.');
            hintResponsePending = false;
            input.placeholder = 'Type your answer...';
        }
    }

    function appendMessage(role, content) {
        var div = document.createElement('div');
        div.className = 'chat-message chat-message--' + role;

        var bubble = document.createElement('div');
        bubble.className = 'chat-bubble chat-bubble--' + role;
        bubble.textContent = content;

        div.appendChild(bubble);
        messagesContainer.appendChild(div);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function appendHintMessage(level, text, isQuestion, isReveal) {
        var div = document.createElement('div');
        div.className = 'chat-message chat-message--ai';

        var bubble = document.createElement('div');
        bubble.className = 'chat-bubble chat-bubble--ai chat-bubble--hint';
        if (isReveal) {
            bubble.classList.add('chat-bubble--reveal');
        }

        var badge = document.createElement('span');
        badge.className = 'hint-level-badge hint-level-badge--' + level;
        badge.textContent = isReveal ? 'Answer Revealed' : 'Hint Level ' + level;
        bubble.appendChild(badge);

        var textNode = document.createElement('p');
        textNode.className = 'hint-text';
        textNode.textContent = text;
        bubble.appendChild(textNode);

        if (isQuestion && !isReveal) {
            var prompt = document.createElement('p');
            prompt.className = 'hint-response-prompt';
            prompt.textContent = 'Try answering this question, or click "Next Hint" to skip.';
            bubble.appendChild(prompt);
        }

        div.appendChild(bubble);
        messagesContainer.appendChild(div);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function appendSystemMessage(text) {
        var div = document.createElement('div');
        div.className = 'chat-message chat-message--system';

        var bubble = document.createElement('div');
        bubble.className = 'chat-bubble chat-bubble--system';
        bubble.textContent = text;

        div.appendChild(bubble);
        messagesContainer.appendChild(div);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    var LEVEL_LABELS = {
        1: 'Level 1 (cued recall)',
        2: 'Level 2 (free recall)',
        3: 'Level 3 (application)',
        4: 'Level 4 (synthesis)',
    };

    var LEVEL_TOOLTIPS = {
        1: 'Cued recall \u2014 recognition-style prompts with partial information to trigger memory',
        2: 'Free recall \u2014 open-ended questions with no cues, requiring retrieval entirely from memory',
        3: 'Application \u2014 apply concepts to new scenarios, problem-solving, cross-concept reasoning',
        4: 'Synthesis \u2014 integrate ideas across topics, evaluate trade-offs, create novel connections',
    };

    function updateMasteryDisplay(masteryLabel, masteryValue, difficultyLevel) {
        var pct = Math.round(masteryValue * 100);
        var fill = document.getElementById('mastery-bar-fill');
        var pctEl = document.getElementById('mastery-bar-pct');
        if (fill) {
            fill.style.width = pct + '%';
            if (masteryLabel) {
                fill.className = 'mastery-bar-fill mastery-bar-fill--' + masteryLabel;
            }
        }
        if (pctEl) {
            pctEl.textContent = pct + '%';
        }
        if (difficultyLevel) {
            var levelEl = document.getElementById('difficulty-indicator');
            if (levelEl) {
                levelEl.textContent = 'Level ' + difficultyLevel;
                levelEl.setAttribute('data-tooltip', LEVEL_TOOLTIPS[difficultyLevel] || '');
            }
        }
    }

    function showVerbatimBadge() {
        // Briefly flash a warning on the last AI bubble
        var bubbles = messagesContainer.querySelectorAll('.chat-bubble--ai');
        var lastBubble = bubbles[bubbles.length - 1];
        if (lastBubble) {
            var badge = document.createElement('span');
            badge.className = 'verbatim-badge';
            badge.textContent = 'Verbatim detected \u2014 try your own words';
            lastBubble.prepend(badge);
        }
    }
});

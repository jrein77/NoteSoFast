document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const messagesContainer = document.getElementById('chat-messages');
    const noteId = window.CHAT_NOTE_ID;
    const modeSelect = document.getElementById('chat-mode');

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

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const message = input.value.trim();
        if (!message) return;

        // Add user message to UI
        appendMessage('user', message);
        input.value = '';
        autoResize();
        input.focus();

        // Get selected mode
        const mode = modeSelect ? modeSelect.value : 'auto';

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

    function appendMessage(role, content) {
        const div = document.createElement('div');
        div.className = 'chat-message chat-message--' + role;

        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble chat-bubble--' + role;
        bubble.textContent = content;

        div.appendChild(bubble);
        messagesContainer.appendChild(div);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    const LEVEL_LABELS = {
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
            // Update color class
            fill.className = 'mastery-bar-fill mastery-bar-fill--' + masteryLabel;
        }
        if (pctEl) {
            pctEl.textContent = pct + '%';
        }
        var levelEl = document.getElementById('difficulty-indicator');
        if (levelEl) {
            levelEl.textContent = 'Level ' + difficultyLevel;
            levelEl.setAttribute('data-tooltip', LEVEL_TOOLTIPS[difficultyLevel] || '');
        }
    }

    function showVerbatimBadge() {
        // Briefly flash a warning on the last AI bubble
        const bubbles = messagesContainer.querySelectorAll('.chat-bubble--ai');
        const lastBubble = bubbles[bubbles.length - 1];
        if (lastBubble) {
            const badge = document.createElement('span');
            badge.className = 'verbatim-badge';
            badge.textContent = 'Verbatim detected — try your own words';
            lastBubble.prepend(badge);
        }
    }
});

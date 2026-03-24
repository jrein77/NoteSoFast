document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const messagesContainer = document.getElementById('chat-messages');
    const noteId = window.CHAT_NOTE_ID;
    const modeSelect = document.getElementById('chat-mode');

    if (!form || !input || !messagesContainer || !noteId) return;

    // Scroll to bottom on load
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const message = input.value.trim();
        if (!message) return;

        // Add user message to UI
        appendMessage('user', message);
        input.value = '';
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

    function updateMasteryDisplay(masteryLabel, masteryValue, difficultyLevel) {
        const masteryEl = document.getElementById('mastery-indicator');
        if (masteryEl) {
            masteryEl.textContent = (masteryValue * 100).toFixed(0) + '% — ' + masteryLabel;
            masteryEl.className = 'mastery-indicator mastery-indicator--' + masteryLabel;
        }
        const levelEl = document.getElementById('difficulty-indicator');
        if (levelEl) {
            levelEl.textContent = LEVEL_LABELS[difficultyLevel] || ('Level ' + difficultyLevel);
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

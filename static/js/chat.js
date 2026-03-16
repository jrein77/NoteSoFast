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
});

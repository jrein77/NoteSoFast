/* Practice chat: structured tutor turns (feedback card + question card), streamed like a live model. */
(function () {
    const C = window.CHAT;
    if (!C) return;
    const scroll = document.getElementById('chat-scroll');
    const form = document.getElementById('composer');
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const hintBtn = document.getElementById('hint-btn');
    const STATUS = { green: '#4f7d5c', yellow: '#b08433', red: '#bb5a45', not_started: '#a3a39b' };
    const LABEL = { green: 'mastered', yellow: 'progressing', red: 'struggling', not_started: 'not practiced yet' };
    const VERDICT = {
        correct: ['check', 'Correct'],
        partial: ['circle-dot', 'Partly there'],
        incorrect: ['x', 'Not quite'],
        verbatim: ['quote', 'Try your own words'],
        info: ['messages-square', 'Let’s think first'],
    };
    const bar = (v, n) => { const f = Math.round(Math.max(0, Math.min(1, v)) * n); return '#'.repeat(f) + '.'.repeat(n - f); };
    let level = 1;
    let levelInfo = C.levelInfo || { recommended_level: 1, level_choice: null };
    let openQuestionEl = null;   // the AI message holding the question awaiting an answer
    let busy = false;
    let hintPending = false;

    const esc = (s) => String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const icons = () => window.NSF && window.NSF.icons();
    const toBottom = () => { scroll.scrollTop = scroll.scrollHeight; };

    // ---------- Status ----------
    function setMemory(label, value) {
        const ring = document.getElementById('mem-ring');
        const p = label === 'not_started' ? 0 : Math.round(value * 100);
        ring.style.setProperty('--p', p);
        ring.style.setProperty('--c', STATUS[label]);
        document.getElementById('mem-pct').textContent = label === 'not_started' ? '–' : p;
        document.getElementById('mem-label').textContent = LABEL[label];
    }
    function setLevel(l) {
        level = l || level;
        const steps = [1, 2, 3, 4].map((i) => '<i class="' + (i <= level ? 'on' : '') + '"></i>').join('');
        document.getElementById('level-pill').innerHTML =
            '<span class="level-steps">' + steps + '</span> L' + level + ' · ' + (C.levelNames[level] || '') +
            '<svg class="level-chev" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>';
    }

    // ---------- Rendering ----------
    function el(html) { const d = document.createElement('div'); d.innerHTML = html.trim(); return d.firstChild; }
    const avatar = '<span class="msg-avatar msg-avatar--text" aria-hidden="true">N</span>';

    function userMsg(text) {
        scroll.appendChild(el('<div class="msg msg-user"><div class="msg-body">' + esc(text) + '</div></div>'));
        toBottom();
    }
    function aiShell(tag) {
        const m = el('<div class="msg msg-ai">' + avatar + '<div class="msg-body"><div class="typing"><i></i><i></i><i></i></div></div></div>');
        if (tag) m.dataset.hintFor = tag;
        scroll.appendChild(m);
        toBottom();
        return m.querySelector('.msg-body');
    }
    function feedbackCard(m) {
        const [icon, title] = VERDICT[m.verdict] || VERDICT.info;
        let links = '';
        (m.reinforced || []).forEach((r) => {
            const up = r.after >= r.before;
            links += '<div class="fb-link ' + (up ? 'up' : 'down') + '">' + (up ? '↑' : '↓') + ' link to ' + esc(r.target_title) +
                '  [' + bar(r.before, 6) + '] → [' + bar(r.after, 6) + ']  ' + Math.round(r.after * 100) + '%</div>';
        });
        return '<div class="fb-card ' + m.verdict + '"><div class="fb-icon"><i data-lucide="' + icon + '"></i></div>' +
            '<div><div class="fb-verdict">' + title + '</div><div class="fb-text" data-stream>' + esc(m.feedback) + '</div>' +
            (links ? '<div class="fb-links">' + links + '</div>' : '') + '</div></div>';
    }
    function questionCard(m) {
        const kind = m.kind === 'explain' ? 'Explain it' : 'L' + m.level + ' · ' + (C.levelNames[m.level] || '');
        const ideaTag = m.idea_label ? '<span class="connects">key idea <b>' + esc(m.idea_label) + '</b></span>' : '';
        const connects = (m.related_titles || []).length
            ? '<span class="connects">connects to <b>' + esc(m.related_titles[0]) + '</b></span>' : '';
        return '<div class="q-card"><div class="q-card-head"><span class="level-pill">' + kind + '</span>' + ideaTag + connects +
            '</div><div class="q-text" data-stream>' + esc(m.question) + '</div></div>';
    }
    function aiHtml(m) {
        let html = '';
        if (m.intro) html += '<p data-stream>' + esc(m.intro) + '</p>';
        if (m.verdict) html += feedbackCard(m);
        if (m.question) html += questionCard(m);
        if (!m.intro && !m.verdict && !m.question) html += '<p data-stream>' + esc(m.content) + '</p>';
        return html;
    }
    function hintHtml(h) {
        const dots = [1, 2, 3, 4].map((i) => '<i class="' + (i <= h.level ? 'on' : '') + '"></i>').join('');
        return '<div class="hint-card ' + (h.is_reveal ? 'reveal' : '') + '"><div class="hint-card-head"><i data-lucide="' +
            (h.is_reveal ? 'eye' : 'lightbulb') + '"></i>' + (h.is_reveal ? 'Answer' : 'Hint ' + h.level) +
            '<span class="hint-dots">' + dots + '</span></div><div class="fb-text" data-stream>' + esc(h.text) + '</div>' +
            (h.is_question && !h.is_reveal ? '<div class="fb-text" style="margin-top:6px;color:var(--text-3)">Answer the hint below, or ask for another.</div>' : '') +
            '</div>';
    }

    // Reveal text progressively, like a model streaming tokens
    async function stream(body, html, thinkMs) {
        await new Promise((r) => setTimeout(r, thinkMs));
        body.innerHTML = html;
        icons();
        const targets = [...body.querySelectorAll('[data-stream]')];
        const texts = targets.map((t) => t.textContent);
        targets.forEach((t) => { t.textContent = ''; });
        body.querySelectorAll('.fb-links').forEach((l) => { l.style.opacity = 0; });
        for (let i = 0; i < targets.length; i++) {
            const t = targets[i], full = texts[i];
            t.classList.add('caret');
            for (let n = 0; n <= full.length; n += 3) {
                t.textContent = full.slice(0, n);
                if (n % 15 === 0) toBottom();
                await new Promise((r) => setTimeout(r, 12));
            }
            t.textContent = full;
            t.classList.remove('caret');
        }
        body.querySelectorAll('.fb-links').forEach((l) => { l.style.transition = 'opacity .4s'; l.style.opacity = 1; });
        toBottom();
    }

    // One question at a time: start a fresh thread for each new question
    function clearThread() { scroll.innerHTML = ''; openQuestionEl = null; }

    function renderHistory() {
        // Show only the current exchange: the last answer (if any) and the open question
        let iq = -1;
        C.messages.forEach((m, i) => { if (m.role === 'ai' && m.question) iq = i; });
        const from = iq > 0 && C.messages[iq - 1].role === 'user' ? iq - 1 : Math.max(0, iq);
        C.messages.slice(from).forEach((m) => {
            if (m.role === 'user') { userMsg(m.content); openQuestionEl = null; return; }
            const body = aiShell();
            body.innerHTML = aiHtml(m);
            if (m.question) openQuestionEl = body.closest('.msg');
            if (m.level) setLevel(m.level);
        });
        icons();
        toBottom();
    }

    // ---------- Send ----------
    // Tell the map which concept, key idea and link the open question is testing
    function postFocus(m) {
        if (window.parent === window || !m || !m.question) return;
        window.parent.postMessage({ type: 'nsf:focus', noteId: C.noteId, idea: m.idea || null,
            related: m.related_ids || [] }, location.origin);
    }

    function notifyGraph(reinforced) {
        if (window.parent === window) return;
        window.parent.postMessage({ type: 'nsf:update', noteId: C.noteId, reinforced: reinforced || [] }, location.origin);
    }

    async function send(text) {
        busy = true;
        sendBtn.disabled = true;
        if (!hintPending) clearThread();
        userMsg(text);
        input.value = '';
        autosize();
        const body = aiShell();
        try {
            if (hintPending) {
                const d = await (await fetch('/api/hint', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ note_id: C.noteId, hint_response: text }),
                })).json();
                const ok = d.mastery_recovery && d.mastery_recovery.above_threshold;
                let html = '';
                if (d.mastery_recovery) {
                    html += '<div class="fb-card ' + (ok ? 'correct' : 'partial') + '"><div class="fb-icon"><i data-lucide="' +
                        (ok ? 'check' : 'circle-dot') + '"></i></div><div><div class="fb-text" data-stream>' +
                        (ok ? 'Good thinking. That gets you closer. Now try the original question again.'
                            : 'Not quite there yet. Here is another nudge.') + '</div></div></div>';
                }
                if (d.text && !ok) html += hintHtml(d);
                hintPending = !!(d.text && d.is_question && !d.is_reveal && !ok);
                await stream(body, html || '<p data-stream>Try the original question again.</p>', 600);
                if (d.mastery_value !== undefined) setMemory(d.mastery, d.mastery_value);
                updateHintButton(d);
                notifyGraph([]);
            } else {
                const d = await (await fetch('/notes/' + C.noteId + '/chat', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text }),
                })).json();
                await stream(body, aiHtml(d), 750);
                setMemory(d.mastery, d.mastery_value);
                if (d.recommended_level) levelInfo = { recommended_level: d.recommended_level, level_choice: d.level_choice };
                if (d.question) openQuestionEl = body.closest('.msg');
                if (d.verdict !== 'info') { setLevel(d.level); resetHints(); }
                notifyGraph(d.reinforced);
                postFocus(d);
            }
        } catch (e) {
            body.innerHTML = '<p>Something went wrong. Try again.</p>';
        }
        busy = false;
        sendBtn.disabled = !input.value.trim();
        input.focus();
    }

    // ---------- Hints ----------
    function resetHints() {
        hintPending = false;
        hintBtn.disabled = false;
        hintBtn.innerHTML = '<i data-lucide="lightbulb"></i> Hint';
        input.placeholder = 'Answer in your own words…';
        icons();
    }
    function updateHintButton(d) {
        if (d.is_reveal || d.exhausted || d.hints_remaining === 0) {
            hintBtn.disabled = true;
            hintBtn.innerHTML = '<i data-lucide="eye"></i> Revealed';
            input.placeholder = 'Now answer in your own words…';
        } else if (d.hints_remaining !== undefined) {
            hintBtn.innerHTML = '<i data-lucide="lightbulb"></i> ' + (d.hints_remaining === 1 ? 'Show answer' : 'Another hint');
            input.placeholder = hintPending ? 'Answer the hint, or ask for another…' : 'Answer in your own words…';
        }
        icons();
    }
    hintBtn.addEventListener('click', async () => {
        if (busy) return;
        busy = true;
        hintBtn.disabled = true;
        const body = aiShell('open');
        let d = {};
        try {
            d = await (await fetch('/api/hint', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ note_id: C.noteId }),
            })).json();
            if (d.error) {
                await stream(body, '<p data-stream>' + esc(d.exhausted ? 'That was the last hint. Give it your best shot.' : d.error) + '</p>', 300);
            } else {
                hintPending = d.is_question && !d.is_reveal;
                await stream(body, hintHtml(d), 500);
                if (d.mastery_value !== undefined) setMemory(d.mastery, d.mastery_value);
                notifyGraph([]);
            }
        } catch (e) {
            body.innerHTML = '<p>Couldn’t get a hint. Try again.</p>';
        }
        hintBtn.disabled = false;
        updateHintButton(d);
        busy = false;
        input.focus();
    });

    // ---------- Composer ----------
    function autosize() {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 180) + 'px';
    }
    input.addEventListener('input', () => { autosize(); sendBtn.disabled = busy || !input.value.trim(); });
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!busy && input.value.trim()) send(input.value.trim());
        }
    });
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        if (!busy && input.value.trim()) send(input.value.trim());
    });

    setMemory(C.mastery, C.masteryValue);
    setLevel(1);
    // Ask the server for a new question that replaces the open one
    async function replaceQuestion(url, payload) {
        if (busy) return;
        busy = true;
        clearThread();
        const body = aiShell();
        try {
            const d = await (await fetch(url, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })).json();
            if (d.error) throw new Error(d.error);
            levelInfo = { recommended_level: d.recommended_level, level_choice: d.level_choice };
            await stream(body, aiHtml(d), 450);
            openQuestionEl = body.closest('.msg');
            setLevel(d.level);
            resetHints();
            postFocus(d);
        } catch (e) {
            body.innerHTML = '<p>Couldn’t load a new question. Try again.</p>';
        }
        busy = false;
        input.focus();
    }

    // The map can ask for a question on one key idea
    window.addEventListener('message', (event) => {
        if (event.origin !== location.origin || !event.data || event.data.type !== 'nsf:review-idea') return;
        replaceQuestion('/notes/' + C.noteId + '/chat/idea', { idea: event.data.idea });
    });

    // Level picker
    const levelBtn = document.getElementById('level-pill');
    const levelMenu = document.getElementById('level-menu');
    function renderLevelMenu() {
        const rec = levelInfo.recommended_level;
        let html = '<button type="button" class="level-opt' + (!levelInfo.level_choice ? ' is-active' : '') + '" data-level="auto">' +
            '<span>Auto</span><small>follows your memory · L' + rec + '</small></button><div class="level-sep"></div>';
        [1, 2, 3, 4].forEach((l) => {
            const note = l === rec ? 'recommended' : l < rec ? 'easier · smaller gain' : 'harder · bigger gain';
            html += '<button type="button" class="level-opt' + (levelInfo.level_choice === l ? ' is-active' : '') + '" data-level="' + l + '">' +
                '<span>L' + l + ' · ' + C.levelNames[l] + '</span><small>' + note + '</small></button>';
        });
        levelMenu.innerHTML = html;
    }
    levelBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        renderLevelMenu();
        levelMenu.hidden = !levelMenu.hidden;
        levelBtn.setAttribute('aria-expanded', String(!levelMenu.hidden));
    });
    levelMenu.addEventListener('click', (e) => {
        const opt = e.target.closest('.level-opt');
        if (!opt) return;
        levelMenu.hidden = true;
        levelBtn.setAttribute('aria-expanded', 'false');
        const v = opt.dataset.level;
        replaceQuestion('/notes/' + C.noteId + '/chat/level', { level: v === 'auto' ? 'auto' : Number(v) });
    });
    document.addEventListener('click', (e) => { if (!levelMenu.contains(e.target) && e.target !== levelBtn) levelMenu.hidden = true; });

    renderHistory();
    postFocus([...C.messages].reverse().find((m) => m.role === 'ai' && m.question));
})();

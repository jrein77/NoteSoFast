/* Shared UI: icons, profile menu, AI-mode toggle, demo reset, concept search palette. */
(function () {
    const NSF = (window.NSF = window.NSF || {});

    NSF.icons = function () {
        if (window.lucide) window.lucide.createIcons();
    };
    NSF.icons();

    NSF.masteryColor = { green: '#34d399', yellow: '#fbbf24', red: '#f87171', not_started: '#4b5060' };

    // ---------- Profile menu ----------
    const profileBtn = document.getElementById('profile-btn');
    const profileMenu = document.getElementById('profile-menu');
    if (profileBtn && profileMenu) {
        const close = () => { profileMenu.hidden = true; profileBtn.setAttribute('aria-expanded', 'false'); };
        profileBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const open = profileMenu.hidden;
            profileMenu.hidden = !open;
            profileBtn.setAttribute('aria-expanded', String(open));
        });
        document.addEventListener('click', (e) => { if (!profileMenu.contains(e.target)) close(); });
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
    }

    const modeToggle = document.getElementById('mode-toggle');
    if (modeToggle) {
        modeToggle.addEventListener('click', async (e) => {
            const btn = e.target.closest('button[data-mode]');
            if (!btn || btn.classList.contains('is-active')) return;
            const wantMock = btn.dataset.mode === 'mock';
            if (!wantMock && modeToggle.dataset.hasKey !== '1') {
                document.getElementById('mode-hint').textContent =
                    'Add ANTHROPIC_API_KEY to .env and restart the server to use live Claude.';
                return;
            }
            const res = await fetch('/api/mock-mode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mock: wantMock }),
            });
            if (res.ok) location.reload();
        });
    }

    document.getElementById('menu-reset')?.addEventListener('click', async () => {
        if (!confirm('Reset demo data? This restores the sample concepts and review history and clears chats.')) return;
        await fetch('/api/demo/reset', { method: 'POST' });
        location.href = '/';
    });

    // ---------- Concept search palette ----------
    const palette = document.getElementById('palette');
    const input = document.getElementById('palette-input');
    const results = document.getElementById('palette-results');
    if (!palette) return;

    let data = null;
    let items = [];
    let active = 0;

    const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    function highlight(text, q) {
        const safe = escapeHtml(text);
        if (!q) return safe;
        const i = text.toLowerCase().indexOf(q);
        if (i < 0) return safe;
        return escapeHtml(text.slice(0, i)) + '<mark>' + escapeHtml(text.slice(i, i + q.length)) + '</mark>' +
            escapeHtml(text.slice(i + q.length));
    }

    async function openPalette() {
        palette.hidden = false;
        input.value = '';
        input.focus();
        if (!data) {
            results.innerHTML = '<div class="palette-empty">Loading…</div>';
            data = await (await fetch('/api/graph-data')).json();
        }
        render();
    }
    function closePalette() { palette.hidden = true; }
    NSF.openPalette = openPalette;

    function render() {
        const q = input.value.trim().toLowerCase();
        const groups = data.groups.filter((g) => !q || g.name.toLowerCase().includes(q));
        const concepts = data.nodes
            .map((n) => {
                const idea = q && n.ideas.find((i) => i.label.toLowerCase().includes(q));
                const hit = !q || n.title.toLowerCase().includes(q) || n.group.toLowerCase().includes(q) ||
                    n.tags.some((t) => t.includes(q)) || idea;
                return hit ? { n, idea } : null;
            })
            .filter(Boolean)
            .sort((a, b) => (a.idea ? 1 : 0) - (b.idea ? 1 : 0) || a.n.title.localeCompare(b.n.title));

        items = [];
        let html = '';
        if (concepts.length) {
            html += '<div class="palette-section">Concepts</div>';
            concepts.slice(0, 8).forEach(({ n, idea }) => {
                const pct = n.mastery === 'not_started' ? 'New' : Math.round(n.mastery_value * 100) + '%';
                const sub = idea ? 'Key idea: ' + highlight(idea.label, q) : escapeHtml(n.group);
                html += '<div class="palette-item" data-i="' + items.length + '">' +
                    '<span class="orb ' + n.mastery + '"></span>' +
                    '<div><div class="palette-item-title">' + highlight(n.title, q) + '</div>' +
                    '<div class="palette-item-sub">' + sub + '</div></div>' +
                    '<div class="palette-item-meta"><span class="meter" style="--c:' + NSF.masteryColor[n.mastery] + '">' +
                    '<span style="width:' + Math.round(n.mastery_value * 100 * (n.mastery === 'not_started' ? 0 : 1)) + '%"></span></span>' + pct + '</div></div>';
                items.push({ type: 'concept', id: n.id });
            });
        }
        if (groups.length) {
            html += '<div class="palette-section">Groups</div>';
            groups.forEach((g) => {
                html += '<div class="palette-item" data-i="' + items.length + '">' +
                    '<span class="group-dot" style="--c:' + g.color + '"></span>' +
                    '<div><div class="palette-item-title">' + highlight(g.name, q) + '</div>' +
                    '<div class="palette-item-sub">' + g.concept_ids.length + ' concepts</div></div>' +
                    '<div class="palette-item-meta">' + Math.round(g.strength * 100) + '%</div></div>';
                items.push({ type: 'group', id: g.id });
            });
        }
        results.innerHTML = html || '<div class="palette-empty">No concepts match “' + escapeHtml(q) + '”</div>';
        active = 0;
        paintActive();
    }

    function paintActive() {
        results.querySelectorAll('.palette-item').forEach((el) => {
            el.classList.toggle('is-active', Number(el.dataset.i) === active);
        });
        results.querySelector('.palette-item.is-active')?.scrollIntoView({ block: 'nearest' });
    }

    function choose(i) {
        const item = items[i];
        if (!item) return;
        closePalette();
        const hash = '#/' + item.type + '/' + item.id;
        if (window.NSFMap) {
            location.hash = hash;
        } else {
            location.href = '/' + hash;
        }
    }

    input.addEventListener('input', render);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { active = Math.min(items.length - 1, active + 1); paintActive(); e.preventDefault(); }
        if (e.key === 'ArrowUp') { active = Math.max(0, active - 1); paintActive(); e.preventDefault(); }
        if (e.key === 'Enter') choose(active);
        if (e.key === 'Escape') closePalette();
    });
    results.addEventListener('mousemove', (e) => {
        const el = e.target.closest('.palette-item');
        if (el && Number(el.dataset.i) !== active) { active = Number(el.dataset.i); paintActive(); }
    });
    results.addEventListener('click', (e) => {
        const el = e.target.closest('.palette-item');
        if (el) choose(Number(el.dataset.i));
    });
    palette.addEventListener('click', (e) => { if (e.target === palette) closePalette(); });
    document.querySelectorAll('[data-open-palette]').forEach((b) => b.addEventListener('click', openPalette));
    document.addEventListener('keydown', (e) => {
        const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
        if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && !typing)) {
            e.preventDefault();
            palette.hidden ? openPalette() : closePalette();
        }
    });
})();

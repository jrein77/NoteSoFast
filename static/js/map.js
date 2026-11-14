/*
 * Knowledge map rendered in ASCII.
 *
 *   map      every concept, clustered by group; practiced links between them
 *   group    the concepts inside one group + practiced links leaving it
 *   concept  one concept: key ideas around it, connected concepts further out
 *
 * Reading a node:
 *   - the outer ring of glyphs fills clockwise with memory strength  ●●●●●···
 *   - the character core is dense and steady when strong; when a memory
 *     decays it thins out and flickers
 *   - while time travelling, labels show how far a concept has dropped
 *
 * Layout is driven by connection strength: strongly linked concepts sit
 * close, weak links drift outward. Practiced connections occasionally carry
 * a travelling signal (more often when stronger). All motion is disabled
 * under prefers-reduced-motion.
 */
(function () {
    const root = document.getElementById('map');
    if (!root) return;

    const INK = '#232321', INK2 = '#55554f', INK3 = '#7b7b74', FAINT = '#adada5', BG = '#f4f4f1', ACCENT = '#3e6474';
    const STATUS = { green: '#4f7d5c', yellow: '#b08433', red: '#bb5a45', not_started: '#a3a39b' };
    const MONO = "'JetBrains Mono', ui-monospace, monospace";
    const SANS = "'Inter', system-ui, sans-serif";
    const RAMP = ' .:-=+*#%@';
    const DRAWER_W = 460, GUTTER = 12;
    const REDUCED = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const pct = (v) => Math.round(v * 100) + '%';
    const edgeKey = (a, b) => [a, b].sort().join('|');
    const quizEdge = (key) => !!quiz && quiz.related.some((rid) => edgeKey(quiz.noteId, rid) === key);
    const hash = (str) => { let h = 2166136261; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967295; };

    // ---------- SVG scaffolding ----------
    const svg = d3.select('#map-svg');
    const defs = svg.append('defs');
    const grid = defs.append('pattern').attr('id', 'grid').attr('width', 28).attr('height', 28)
        .attr('patternUnits', 'userSpaceOnUse');
    grid.append('text').attr('x', 14).attr('y', 14).attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
        .attr('font-family', MONO).attr('font-size', 9).attr('fill', 'rgba(35,35,33,0.09)').text('·');
    const bg = svg.append('rect').attr('fill', 'url(#grid)');
    const camera = svg.append('g');
    const sceneWrap = camera.append('g').attr('class', 'scene');
    const tooltip = document.getElementById('map-tooltip');

    // ---------- State ----------
    let data = null;
    let view = { level: 'map', groupId: null, conceptId: null };
    let renderedKey = null;
    let transitioning = false;
    let fitTransform = d3.zoomIdentity;
    let bounds = { x0: -300, y0: -200, x1: 300, y1: 200 };
    let positions = {};      // id -> {x, y, r}  (things you can click / zoom into)
    let layoutCache = {};    // sceneKey -> positions, so refreshes don't reshuffle
    let liveEdges = [];      // edges that can carry signals
    let quiz = null;         // { noteId, idea, related[] } for the question open in the drawer
    let liveSpokes = [];     // filled dendrites that carry waves
    let liveRings = [];      // cell bodies with an orbiting glyph

    const zoom = d3.zoom().scaleExtent([0.25, 4])
        .filter((e) => !e.button && e.type !== 'dblclick')
        .on('zoom', (e) => {
            camera.attr('transform', e.transform);
            if (e.sourceEvent && e.sourceEvent.type === 'wheel') semanticZoom(e.transform, e.sourceEvent);
        });
    svg.call(zoom);

    function nodeById(id) { return data.nodes.find((n) => n.id === id); }
    function groupById(id) { return data.groups.find((g) => g.id === id); }
    function layer(name) {
        let l = sceneWrap.select('g.layer-' + name);
        if (l.empty()) l = sceneWrap.append('g').attr('class', 'layer-' + name);
        return l;
    }

    // ---------- Viewport / fit ----------
    function viewport() {
        const w = root.clientWidth, h = root.clientHeight;
        const left = w > 860 ? 240 + GUTTER * 2 : 0;
        const right = root.classList.contains('drawer-open') && w > 860 ? DRAWER_W + GUTTER * 2 : 0;
        return { x0: left + 16, x1: w - right - 16, y0: 128, y1: h - 84 };
    }
    function computeBounds(list, pad) {
        const vals = list || Object.values(positions);
        if (!vals.length) return;
        bounds = {
            x0: d3.min(vals, (p) => p.x - p.r - 60) - pad, x1: d3.max(vals, (p) => p.x + p.r + 60) + pad,
            y0: d3.min(vals, (p) => p.y - p.r - 14) - pad, y1: d3.max(vals, (p) => p.y + p.r + 40) + pad,
        };
    }
    function computeFit() {
        const v = viewport();
        const bw = bounds.x1 - bounds.x0, bh = bounds.y1 - bounds.y0;
        const k = Math.max(0.4, Math.min(1.3, Math.min((v.x1 - v.x0) / bw, (v.y1 - v.y0) / bh)));
        const cx = (bounds.x0 + bounds.x1) / 2, cy = (bounds.y0 + bounds.y1) / 2;
        return d3.zoomIdentity.translate((v.x0 + v.x1) / 2 - cx * k, (v.y0 + v.y1) / 2 - cy * k).scale(k);
    }
    function fit(duration) {
        fitTransform = computeFit();
        (duration ? svg.transition().duration(duration).ease(d3.easeCubicInOut) : svg).call(zoom.transform, fitTransform);
    }

    // ---------- Tooltip ----------
    function showTip(event, html) {
        tooltip.innerHTML = html;
        tooltip.hidden = false;
        const r = root.getBoundingClientRect();
        let x = event.clientX - r.left + 16, y = event.clientY - r.top + 14;
        if (x + tooltip.offsetWidth > r.width - 10) x = event.clientX - r.left - tooltip.offsetWidth - 16;
        if (y + tooltip.offsetHeight > r.height - 10) y = event.clientY - r.top - tooltip.offsetHeight - 14;
        tooltip.style.left = x + 'px';
        tooltip.style.top = y + 'px';
    }
    const hideTip = () => { tooltip.hidden = true; };
    const gauge = (v, n) => { const f = Math.round(Math.max(0, Math.min(1, v)) * n); return '●'.repeat(f) + '·'.repeat(n - f); };
    const tipMeter = (v, status) => '<div style="margin-top:6px;color:' + STATUS[status] + '">' + gauge(v, 12) +
        ' <span style="color:' + INK2 + '">' + pct(v) + ' memory score</span></div>';
    function trend(n) {
        if (!data.clock_offset_days || n.mastery === 'not_started') return null;
        const drop = Math.round((n.mastery_now - n.mastery_value) * 100);
        return drop >= 3 ? drop : null;
    }
    function conceptTip(n) {
        if (n.mastery === 'not_started') return '<strong>' + n.title + '</strong>not practiced yet';
        const last = n.days_since === null ? '' : (n.days_since < 1 ? 'today' : Math.round(n.days_since) + 'd ago');
        const t = trend(n);
        return '<strong>' + n.title + '</strong>' + n.review_count + ' reviews · last ' + last + tipMeter(n.mastery_value, n.mastery) +
            (t ? '<span style="color:' + STATUS.red + '">↓ ' + t + ' points since today</span>' : '');
    }
    function edgeTip(e) {
        const head = '<strong>' + nodeById(e.source).title + ' ↔ ' + nodeById(e.target).title + '</strong>';
        if (!e.review_count) return head + 'never practiced together<br>a cross-topic question builds this link';
        const fade = e.days_to_fade ? 'fades in ~' + Math.round(e.days_to_fade) + 'd without review' : 'fading · review to rebuild';
        return head + 'practiced together ' + e.review_count + '× · half-life ' + e.half_life + 'd' +
            '<div style="margin-top:6px">' + gauge(e.strength, 12) + ' ' + pct(e.strength) + '</div>' + fade;
    }

    // ---------- Neuron drawing ----------
    // One glyph figure carries everything:
    //   cell body   a ring of characters with the concept's memory % inside
    //   spokes      one dendrite per key idea; each is a progress bar of dots,
    //               filled out to that idea's strength (equal length, so they
    //               compare like a radial bar chart)
    //   axons       dotted connections to other concepts; density = strength
    const PALE = '#a9a9a1';
    const rand = (seed) => { let x = Math.floor(hash(seed) * 2147483646) + 1; return () => (x = (x * 16807) % 2147483647) / 2147483647; };

    function glyphRun(g, pts, glyph, o) {
        if (!pts.length) return null;
        return g.append('text')
            .attr('x', pts.map((p) => p[0].toFixed(1)).join(' '))
            .attr('y', pts.map((p) => p[1].toFixed(1)).join(' '))
            .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
            .attr('font-family', MONO).attr('font-size', o.size || 7).attr('fill', o.fill || INK3)
            .attr('font-weight', o.weight || 400)
            .attr('opacity', o.opacity === undefined ? 1 : o.opacity).style('pointer-events', 'none')
            .text(glyph.length === 1 ? glyph.repeat(pts.length) : glyph);
    }
    function dotsAlong(x0, y0, x1, y1, gap) {
        const len = Math.hypot(x1 - x0, y1 - y0);
        const n = Math.max(1, Math.floor(len / gap));
        const out = [];
        for (let i = 0; i <= n; i++) out.push([x0 + ((x1 - x0) * i) / n, y0 + ((y1 - y0) * i) / n]);
        return out;
    }
    const edgeInk = (s) => (s <= 0 ? FAINT : s < 0.3 ? INK3 : s < 0.6 ? INK2 : INK);
    const angDist = (a, b) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));

    // Spread spokes evenly, rotated to stay clear of axons and the label below
    function spokeAngles(n, avoid) {
        if (!n) return [];
        const step = (Math.PI * 2) / n;
        const blockers = (avoid || []).concat([Math.PI / 2]);
        let best = -Math.PI / 2, bestScore = -1;
        for (let k = 0; k < 16; k++) {
            const off = -Math.PI / 2 + (k / 16) * step;
            let score = Infinity;
            for (let i = 0; i < n; i++) blockers.forEach((b) => { score = Math.min(score, angDist(off + i * step, b)); });
            if (score > bestScore + 1e-6) { bestScore = score; best = off; }
        }
        return Array.from({ length: n }, (_, i) => best + i * step);
    }

    // Axon: straight dotted line, soma ring to soma ring, forked terminal at the far end
    function drawEdges(layerSel, edges, update) {
        const sel = layerSel.selectAll('g.axon').data(edges, (d) => d.key);
        const enter = sel.enter().append('g').attr('class', 'axon');
        enter.append('line').attr('class', 'axon-hit').attr('stroke', 'transparent').attr('stroke-width', 14).style('cursor', 'help');
        const all = enter.merge(sel);
        all.each(function (d) {
            const g = d3.select(this);
            const prev = g.attr('data-s');
            g.attr('data-s', String(d.strength));
            g.selectAll('text').remove();
            const s = typeof d.strength === 'number' ? d.strength : 0;
            const a = d.a, b = d.b, ra = a.soma || a.r, rb = b.soma || b.r;
            const dx = b.x - a.x, dy = b.y - a.y, dist = Math.hypot(dx, dy) || 1;
            const ux = dx / dist, uy = dy / dist;
            const gapA = ra + 6, gapB = rb + (s > 0 && !d.noTerminal ? 15 : 6);
            const x0 = a.x + ux * gapA, y0 = a.y + uy * gapA, x1 = b.x - ux * gapB, y1 = b.y - uy * gapB;
            const len = Math.hypot(x1 - x0, y1 - y0);
            d.sample = { len: dist > gapA + gapB ? len : 0, at: (t) => ({ x: x0 + (x1 - x0) * t, y: y0 + (y1 - y0) * t }) };
            d.shaft = null;
            g.select('.axon-hit').attr('x1', x0).attr('y1', y0).attr('x2', x1).attr('y2', y1)
                .on('mouseenter mousemove', (e) => d.tip && showTip(e, d.tip()))
                .on('mouseleave', hideTip);
            if (!d.sample.len) return;
            d.hot = false;
            const ink = d.hot ? ACCENT : (d.ink || edgeInk(s));
            const changed = update && prev !== null && prev !== String(d.strength);
            const pts = dotsAlong(x0, y0, x1, y1, s <= 0 ? 7 : 3.3);
            const base = (s >= 0.55 ? '•' : '·').repeat(pts.length);
            const shaft = glyphRun(g, pts, base, { size: (s >= 0.55 ? 7.5 : 8.5) + (d.hot ? 1 : 0), fill: changed ? ACCENT : ink, weight: d.hot ? 700 : 400, opacity: d.dim && !d.hot ? 0.55 : 1 });
            if (changed && shaft) shaft.transition().duration(1400).attr('fill', ink);
            d.shaft = { el: shaft, base };
            if (s > 0 && !d.noTerminal) {
                const ang = Math.atan2(uy, ux), tips = [], twig = [];
                [-0.55, 0, 0.55].forEach((o) => {
                    const l = 9 + 4 * s;
                    const tx = x1 + l * Math.cos(ang + o), ty = y1 + l * Math.sin(ang + o);
                    twig.push(...dotsAlong(x1, y1, tx, ty, 3).slice(1));
                    tips.push([tx, ty]);
                });
                glyphRun(g, twig, '·', { size: 7, fill: ink, opacity: d.dim ? 0.5 : 0.9 });
                glyphRun(g, tips, '•', { size: 7.5, fill: ink, opacity: d.dim ? 0.5 : 1 });
            }
        });
        sel.exit().remove();
        all.each((d) => { if (d.shaft && d.shaft.el && (d.hot || (typeof d.strength === 'number' && d.strength > 0.08))) liveEdges.push(d); });
    }

    function label(g, x, y, text, o) {
        o = o || {};
        return g.append('text').attr('x', x).attr('y', y).attr('text-anchor', o.anchor || 'middle').attr('dominant-baseline', 'central')
            .attr('font-family', o.family || MONO).attr('font-size', o.size || 11.5).attr('font-weight', o.weight || 500)
            .attr('fill', o.fill || INK).attr('stroke', BG).attr('stroke-width', 4).attr('paint-order', 'stroke')
            .style('pointer-events', 'none').text(text);
    }

    function ringOfDots(g, rr, glyph, o) {
        const n = Math.max(8, Math.round((2 * Math.PI * rr) / (o.spacing || 3.6)));
        const pts = [];
        for (let i = 0; i < n; i++) { const a = -Math.PI / 2 + (i / n) * Math.PI * 2; pts.push([o.cx + rr * Math.cos(a), o.cy + rr * Math.sin(a)]); }
        return { el: glyphRun(g, pts, glyph, o), n };
    }

    // ASCII fill: a fine grid of characters packed into the disc, shaded like
    // a lit sphere. Heavier characters = stronger memory, so a mastered concept
    // reads dense ( # % @ ) and a fading one light ( . : - ). Kept pale enough
    // for the score on top to stay readable.
    const FILL_RAMP = ' .:-=+*#%@';
    function halftone(g, cx, cy, r, s, color, fresh) {
        const step = r > 34 ? 2.9 : r > 18 ? 2.6 : r > 9 ? 2.2 : 1.8;
        const lh = step * 1.15;
        const body = g.append('g').attr('opacity', fresh ? 0.4 : 0.5 + 0.3 * s);
        for (let y = -r + lh / 2; y < r; y += lh) {
            const pts = [];
            let str = '';
            for (let x = -r + step / 2; x < r; x += step) {
                const d = Math.hypot(x, y) / r;
                if (d > 0.97) continue;
                const shade = Math.sqrt(Math.max(0, 1 - d * d));
                const light = 0.55 + 0.45 * (-(x + y) / (r * 2) + 0.5);
                let ch;
                if (fresh) ch = (Math.round((x + r) / step) + Math.round((y + r) / lh)) % 3 === 0 ? '.' : ' ';
                else {
                    const v = (0.12 + 0.88 * s) * (0.55 * shade + 0.45 * light);
                    ch = FILL_RAMP[Math.max(1, Math.min(FILL_RAMP.length - 1, Math.round(v * (FILL_RAMP.length - 1))))];
                }
                if (ch === ' ') continue;
                pts.push([cx + x, cy + y]);
                str += ch;
            }
            if (pts.length) glyphRun(body, pts, str, { size: step * 1.55, fill: color });
        }
    }

    // Dendrites: short branching arbors; fuller when the memory is strong,
    // withered when it has decayed. Kept clear of the label below the soma.
    function dendrites(g, id, r, s, avoid) {
        const rnd = rand('dend:' + id);
        const count = 3 + Math.round(4 * s);
        const reach = r * (0.45 + 0.9 * s) + 6;
        const pts = [], tips = [];
        const blocked = (a) => (avoid || []).some((b) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b))) < 0.32);
        let placed = 0;
        for (let k = 0; k < 24 && placed < count; k++) {
            const a = -Math.PI / 2 + (k / 24) * Math.PI * 2 * 1.618 + rnd() * 0.4;
            const down = Math.sin(a) > 0.75;
            if (down || blocked(a)) continue;
            placed++;
            const x0 = (r + 9) * Math.cos(a), y0 = (r + 9) * Math.sin(a);
            const L = reach * (0.7 + rnd() * 0.5);
            const x1 = x0 + L * Math.cos(a), y1 = y0 + L * Math.sin(a);
            pts.push(...dotsAlong(x0, y0, x1, y1, 3.2));
            // one fork into two twigs
            [-0.5, 0.5].forEach((t) => {
                const b = a + t * (0.6 + rnd() * 0.3);
                const l2 = L * (0.35 + rnd() * 0.25);
                const x2 = x1 + l2 * Math.cos(b), y2 = y1 + l2 * Math.sin(b);
                pts.push(...dotsAlong(x1, y1, x2, y2, 3.2).slice(1));
                tips.push([x2, y2]);
            });
        }
        glyphRun(g, pts, '·', { size: 7.5, fill: INK3, opacity: 0.6 + 0.35 * s });
        glyphRun(g, tips, '•', { size: 6, fill: INK3, opacity: 0.6 + 0.35 * s });
    }

    function scoreText(g, cx, cy, r, s, fresh, caption) {
        const num = g.append('text').attr('x', cx).attr('y', cy - (caption ? r * 0.12 : 0))
            .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
            .attr('font-family', MONO).attr('font-weight', 700).attr('fill', fresh ? INK3 : INK)
            .attr('stroke', BG).attr('stroke-width', Math.max(2.5, r * 0.12)).attr('stroke-linejoin', 'round').attr('paint-order', 'stroke')
            .attr('font-size', Math.max(7, r * (fresh ? 0.48 : 0.6))).style('pointer-events', 'none');
        if (fresh) num.text('new');
        else {
            num.append('tspan').text(Math.round(s * 100));
            num.append('tspan').attr('font-size', Math.max(5.5, r * 0.32)).attr('fill', INK3).text('%');
        }
        if (caption && !fresh) {
            g.append('text').attr('x', cx).attr('y', cy + r * 0.42).attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
                .attr('font-family', MONO).attr('font-size', Math.max(6, r * 0.2)).attr('letter-spacing', '0.06em')
                .attr('fill', INK2).attr('stroke', BG).attr('stroke-width', 3).attr('paint-order', 'stroke')
                .style('pointer-events', 'none').text('memory');
        }
    }

    // A concept neuron. Each key idea is its own small neuron, joined to the
    // concept by a dendrite that lights up (solid dots) to the idea's strength.
    // Concepts without key ideas have no satellites: they stand alone.
    function neuron(g, d) {
        const { soma: r, L, sat } = d.pos;
        const fresh = d.mastery === 'not_started';
        const s = fresh ? 0 : Math.max(0, Math.min(1, d.value || 0));
        const ideas = d.ideas || [];
        const angles = spokeAngles(ideas.length, d.avoid);
        const gap = r > 30 ? 4 : 3.3;
        const big = sat >= 14;
        d.spokeTips = {};

        // Branching dendrite arbors (kept clear of key ideas, axons and the label)
        dendrites(g, d.id, r, s, (d.avoid || []).concat(angles));

        ideas.forEach((idea, i) => {
            const a = angles[i], ca = Math.cos(a), sa = Math.sin(a);
            const ideaFresh = idea.mastery === 'not_started' || fresh;
            const is = ideaFresh ? 0 : idea.strength;
            const color = ideaFresh ? PALE : STATUS[idea.mastery];
            const cx = (r + L) * ca, cy = (r + L) * sa;

            // dendrite: soma edge -> satellite edge, lit outward to the idea's strength
            const pts = dotsAlong((r + 5) * ca, (r + 5) * sa, cx - (sat + 4) * ca, cy - (sat + 4) * sa, gap);
            const litN = ideaFresh ? 0 : Math.max(1, Math.round(pts.length * is));
            glyphRun(g, pts.slice(litN), '·', { size: 7.5, fill: PALE });
            const base = '•'.repeat(litN);
            const el = glyphRun(g, pts.slice(0, litN), base, { size: big ? 7.5 : 6.5, fill: color });
            if (el && !REDUCED && is > 0.3) liveSpokes.push({ el, base, s: is, key: d.id + ':' + idea.id });

            // the idea's own neuron
            g.append('circle').attr('cx', cx).attr('cy', cy).attr('r', sat + 1.5).attr('fill', BG);
            if (!big) halftone(g, cx, cy, sat - 0.5, is, ideaFresh ? INK3 : color, ideaFresh);
            const rd = ringOfDots(g, sat, '·', { cx, cy, size: big ? 8.5 : 6.5, fill: ideaFresh ? INK3 : color, weight: 600, spacing: big ? 3.8 : 2.8 });
            if (big) {
                halftone(g, cx, cy, sat - 2.5, is, ideaFresh ? INK3 : color, ideaFresh);
                scoreText(g, cx, cy, sat, is, ideaFresh, false);
                if (!REDUCED && is > 0.2) liveRings.push({ el: rd.el, n: rd.n, s: is, key: d.id + ':ring:' + idea.id });
            }
            d.spokeTips[idea.id] = { x: cx, y: cy, a, sat };
            if (d.quizIdea === idea.id) {
                if (rd.el) rd.el.attr('fill', ACCENT);
                if (el) el.attr('fill', ACCENT);
                if (rd.el && !REDUCED) liveRings.push({ el: rd.el, n: rd.n, s: 1, key: 'quiz:' + d.id + ':' + idea.id });
            }

            // hovering a satellite explains that idea
            g.append('circle').attr('cx', cx).attr('cy', cy).attr('r', sat + 4).attr('fill', 'transparent')
                .on('mouseenter mousemove', (e) => {
                    e.stopPropagation();
                    showTip(e, '<strong>' + idea.label + '</strong>' + (idea.summary ? idea.summary + '<br>' : '') +
                        (ideaFresh ? 'not practiced yet' : tipMeter(is, idea.mastery)) +
                        '<span class="muted">key idea in ' + (d.node ? d.node.title : '') + ' · click to review it</span>');
                })
                .style('cursor', 'pointer')
                .on('click', (e) => { e.stopPropagation(); hideTip(); reviewIdea(d.id, idea.id); });

            if (d.labelSpokes) {
                const lx = cx + (sat + 10) * ca, ly = cy + (sat + 10) * sa;
                const anchor = Math.abs(ca) < 0.3 ? 'middle' : ca > 0 ? 'start' : 'end';
                const dy = Math.abs(ca) < 0.3 ? (sa > 0 ? 6 : -6) : 0;
                label(g, lx, ly + dy, idea.label, { size: 11.5, anchor });
            }
        });

        // Cell body: ring of characters + memory score in the centre
        g.append('circle').attr('r', r + 2).attr('fill', BG);
        halftone(g, 0, 0, r - 3, s, fresh ? INK3 : STATUS[d.mastery], fresh);
        const rd = ringOfDots(g, r, '·', { cx: 0, cy: 0, size: r > 26 ? 9 : 8, fill: fresh ? INK3 : STATUS[d.mastery], weight: 600, spacing: r > 26 ? 4.2 : 3.6 });
        g.node().__somaRing = rd.el && rd.el.node();
        if (!REDUCED && s > 0.2) liveRings.push({ el: rd.el, n: rd.n, s, key: d.id });
        scoreText(g, 0, 0, r, s, fresh, r >= 20);
        g.append('circle').attr('r', r + 4).attr('fill', 'transparent');
    }

    function drawNodes(layerSel, items, update) {
        const sel = layerSel.selectAll('g.anode').data(items, (d) => d.id);
        const enter = sel.enter().append('g').attr('class', 'anode')
            .attr('transform', (d) => 'translate(' + d.pos.x + ',' + d.pos.y + ')');
        const all = enter.merge(sel);
        all.each(function (d) {
            const g = d3.select(this);
            const before = g.attr('data-sig');
            const sig = d.mastery + ':' + Math.round((d.value || 0) * 100) + ':' + (d.ideas || []).map((i) => Math.round(i.strength * 20)).join('');
            g.attr('data-sig', sig);
            g.selectAll('*').remove();
            d.quizIdea = quiz && quiz.noteId === d.id ? quiz.idea : null;
            neuron(g, d);
            if (quiz && quiz.noteId === d.id && !d.quizIdea && g.node().__somaRing) d3.select(g.node().__somaRing).attr('fill', ACCENT);
            if (update && before && before !== sig) {
                g.selectAll('text').filter(function () { return this.getAttribute('font-weight') === '600'; })
                    .attr('fill-opacity', 0.35).transition().duration(900).attr('fill-opacity', 1);
            }
            const span = d.pos.soma + d.pos.L + d.pos.sat;
            g.append('circle').attr('class', 'hover-ring').attr('r', span + 8).attr('fill', 'none')
                .attr('stroke', ACCENT).attr('stroke-width', 1).attr('stroke-dasharray', '1 3').attr('opacity', 0);
            if (d.label) {
                const lo = d.labelOpts || {};
                let lx = 0, ly = span + 16, anchor = 'middle';
                if (d.labelAngle !== undefined) {
                    const ca = Math.cos(d.labelAngle), sa = Math.sin(d.labelAngle);
                    lx = (span + 12) * ca; ly = (span + 12) * sa;
                    anchor = Math.abs(ca) < 0.3 ? 'middle' : ca > 0 ? 'start' : 'end';
                    if (Math.abs(ca) < 0.3) ly += sa > 0 ? 8 : -8;
                }
                const lt = label(g, lx, ly, d.label, { ...lo, anchor });
                const t = trend(d.node || {});
                if (t) lt.append('tspan').attr('fill', STATUS.red).attr('font-weight', 600).text('  ↓' + t);
            }
            g.attr('opacity', d.dim ? 0.62 : 1);
        });
        (update ? all.transition().duration(600) : all)
            .attr('transform', (d) => 'translate(' + d.pos.x + ',' + d.pos.y + ')');
        all.style('cursor', (d) => (d.zoom ? 'zoom-in' : d.onClick ? 'pointer' : 'default'))
            .on('mouseenter', function (e, d) {
                if (d.onClick) d3.select(this).select('.hover-ring').attr('opacity', 1);
                if (d.tip) showTip(e, d.tip());
            })
            .on('mousemove', (e, d) => d.tip && showTip(e, d.tip()))
            .on('mouseleave', function () { d3.select(this).select('.hover-ring').attr('opacity', 0); hideTip(); })
            .on('click', (e, d) => { hideTip(); if (d.onClick) d.onClick(e); });
        sel.exit().remove();
    }

    // Neuron geometry at each zoom level: soma radius + spoke length
    const geo = (n, level) => {
        const s = n.mastery === 'not_started' ? 0 : n.mastery_value;
        if (level === 'map') return { soma: 11, L: 19, sat: 4 };
        if (level === 'group') return { soma: 22 + 4 * s, L: 44, sat: 7.5 };
        if (level === 'outer') return { soma: 13, L: 20, sat: 4.5 };
        return { soma: 40, L: 150, sat: 20 };
    };
    const withGeo = (p, g) => ({ x: p.x, y: p.y, soma: g.soma, L: g.L, sat: g.sat, r: g.soma + g.L + g.sat + 8 });

    // Force layout, computed once per scene and cached so refreshes don't reshuffle
    function forceLayout(key, nodes, links, extra) {
        if (layoutCache[key]) return layoutCache[key];
        const simNodes = nodes.map((n) => ({ ...n }));
        const sim = d3.forceSimulation(simNodes)
            .force('link', d3.forceLink(links.map((l) => ({ ...l }))).id((d) => d.id)
                .distance((l) => l.distance).strength((l) => l.pull))
            .force('charge', d3.forceManyBody().strength(extra.charge || -700))
            .force('collide', d3.forceCollide().radius((d) => d.r + (extra.pad || 60)))
            .stop();
        if (extra.forces) extra.forces(sim);
        for (let i = 0; i < 320; i++) sim.tick();
        const out = {};
        simNodes.forEach((n) => { out[n.id] = { x: n.x, y: n.y, r: n.r }; });
        layoutCache[key] = out;
        return out;
    }
    const angleTo = (a, b) => Math.atan2(b.y - a.y, b.x - a.x);
    const avoidFor = (id, list, pos) => list.filter((e) => e.source === id || e.target === id)
        .filter((e) => pos[e.source] && pos[e.target])
        .map((e) => angleTo(pos[id], pos[e.source === id ? e.target : e.source]));
    const opensTip = (n) => (n.ideas.length ? '<br>' + n.ideas.length + ' key ideas inside · click to open' : '');

    // ---------- Scene: map (all concepts, clustered by group) ----------
    function renderMap(update) {
        const groups = data.groups;
        const ng = groups.length;
        const centers = {};
        groups.forEach((g, i) => {
            const a = -Math.PI / 2 + (i / Math.max(ng, 1)) * Math.PI * 2 + (ng === 4 ? Math.PI / 4 : 0);
            const R = ng <= 1 ? 0 : 240 + ng * 12;
            centers[g.id] = { x: R * Math.cos(a) * 1.25, y: R * Math.sin(a) * 0.85 };
        });
        const nodes = data.nodes.map((n) => {
            const gg = geo(n, 'map');
            return { id: n.id, r: gg.soma + gg.L + gg.sat, group: n.group_id,
                x: centers[n.group_id].x + (hash(n.id) - 0.5) * 60, y: centers[n.group_id].y + (hash(n.id + 'y') - 0.5) * 60 };
        });
        const strong = data.edges.filter((e) => e.strength > 0);
        const pos = forceLayout('map', nodes, strong.map((e) => ({
            source: e.source, target: e.target, distance: 150 - 50 * e.strength, pull: 0.05 + 0.25 * e.strength,
        })), {
            charge: -420, pad: 44,
            forces: (sim) => sim
                .force('gx', d3.forceX((d) => centers[d.group].x).strength(0.22))
                .force('gy', d3.forceY((d) => centers[d.group].y).strength(0.22)),
        });
        const region = (g) => {
            const pts = g.concept_ids.map((id) => pos[id]).filter(Boolean);
            const cx = d3.mean(pts, (p) => p.x), cy = d3.mean(pts, (p) => p.y);
            const r = (d3.max(pts, (p) => Math.hypot(p.x - cx, p.y - cy) + p.r) || 40) + 78;
            return { x: cx, y: cy, r };
        };
        if (!layoutCache['map:separated']) {
            for (let iter = 0; iter < 80; iter++) {
                let moved = false;
                const regs = groups.map(region);
                for (let i = 0; i < groups.length; i++) {
                    for (let j = i + 1; j < groups.length; j++) {
                        const A = regs[i], B = regs[j];
                        const dx = B.x - A.x, dy = B.y - A.y, dist = Math.hypot(dx, dy) || 1;
                        const overlap = A.r + B.r + 110 - dist;   // room for the group titles
                        if (overlap > 0) {
                            moved = true;
                            const ox = (dx / dist) * overlap / 2, oy = (dy / dist) * overlap / 2;
                            groups[i].concept_ids.forEach((id) => { if (pos[id]) { pos[id].x -= ox; pos[id].y -= oy; } });
                            groups[j].concept_ids.forEach((id) => { if (pos[id]) { pos[id].x += ox; pos[id].y += oy; } });
                        }
                    }
                }
                if (!moved) break;
            }
            layoutCache['map:separated'] = true;
        }
        positions = {};
        groups.forEach((g) => { positions[g.id] = region(g); });
        computeBounds(Object.values(positions), 10);
        bounds.y0 -= 40;

        const regions = layer('regions').selectAll('g.region').data(groups, (d) => d.id);
        const rall = regions.enter().append('g').attr('class', 'region').style('cursor', 'zoom-in').merge(regions);
        rall.each(function (g) {
            const sel = d3.select(this);
            sel.selectAll('*').remove();
            const p = positions[g.id];
            sel.attr('transform', 'translate(' + p.x + ',' + p.y + ')');
            sel.append('circle').attr('r', p.r).attr('fill', 'rgba(35,35,33,0.018)');
            const n = Math.floor((2 * Math.PI * p.r) / 6);
            const pts = [];
            for (let i = 0; i < n; i++) { const a = (i / n) * Math.PI * 2; pts.push([p.r * Math.cos(a), p.r * Math.sin(a)]); }
            glyphRun(sel, pts, '·', { size: 7.5, fill: '#9d9d95' });
            label(sel, 0, -p.r - 34, g.name, { family: SANS, size: 15, weight: 600 });
            label(sel, 0, -p.r - 16, g.concept_ids.length + ' concepts · ' + (g.studied ? pct(g.strength) + ' avg' : 'new'),
                { size: 10, weight: 400, fill: INK3 });
        });
        rall.on('click', (e, g) => go('#/group/' + g.id))
            .on('mouseenter mousemove', (e, g) => showTip(e, '<strong>' + g.name + '</strong>' + g.concept_ids.length +
                ' concepts · ' + (g.studied ? pct(g.strength) + ' average memory' : 'not practiced yet') + '<br>click to zoom in'))
            .on('mouseleave', hideTip);
        regions.exit().remove();

        const npos = {};
        data.nodes.forEach((n) => { npos[n.id] = withGeo(pos[n.id], geo(n, 'map')); });
        drawEdges(layer('edges'), strong.map((e) => ({
            ...e, key: edgeKey(e.source, e.target), a: npos[e.source], b: npos[e.target], tip: () => edgeTip(e),
        })), update);
        drawNodes(layer('nodes'), data.nodes.map((n) => ({
            id: n.id, node: n, pos: npos[n.id], mastery: n.mastery, value: n.mastery_value, ideas: n.ideas,
            label: n.title.length > 24 ? n.title.slice(0, 23) + '…' : n.title, labelOpts: { size: 10.5 },
            avoid: avoidFor(n.id, strong, npos), zoom: n.ideas.length > 0,
            tip: () => conceptTip(n) + opensTip(n), onClick: () => go('#/concept/' + n.id),
        })), update);
    }

    // ---------- Scene: group ----------
    function renderGroup(update) {
        const group = groupById(view.groupId);
        if (!group) return go('');
        const members = group.concept_ids.map(nodeById).filter(Boolean);
        const memberSet = new Set(members.map((m) => m.id));
        const gi = Object.fromEntries(data.groups.map((g, i) => [g.id, i]));
        const ang = (gid) => -Math.PI / 2 + (gi[gid] / data.groups.length) * Math.PI * 2 + (data.groups.length === 4 ? Math.PI / 4 : 0);
        const outsiders = [];
        data.edges.forEach((e) => {
            if (e.strength <= 0) return;
            const inA = memberSet.has(e.source), inB = memberSet.has(e.target);
            if (inA === inB) return;
            const o = nodeById(inA ? e.target : e.source);
            if (!outsiders.find((x) => x.id === o.id)) outsiders.push(o);
        });
        const anchor = {};
        outsiders.forEach((x) => {
            const dir = Math.atan2(Math.sin(ang(x.group_id)) - Math.sin(ang(view.groupId)), Math.cos(ang(x.group_id)) - Math.cos(ang(view.groupId)));
            anchor[x.id] = { x: 440 * Math.cos(dir), y: 300 * Math.sin(dir) };
        });
        const nodes = members.map((m, i) => {
            const gg = geo(m, 'group');
            return { id: m.id, r: gg.soma + gg.L + gg.sat, x: 150 * Math.cos((i / members.length) * Math.PI * 2), y: 150 * Math.sin((i / members.length) * Math.PI * 2) };
        }).concat(outsiders.map((x) => {
            const gg = geo(x, 'outer');
            return { id: x.id, r: gg.soma + gg.L + gg.sat, x: anchor[x.id].x, y: anchor[x.id].y, outsider: true };
        }));
        const ids = new Set(nodes.map((n) => n.id));
        const shown = data.edges.filter((e) => ids.has(e.source) && ids.has(e.target) &&
            ((memberSet.has(e.source) && memberSet.has(e.target)) || e.strength > 0));
        const pos = forceLayout('group:' + group.id, nodes, shown.map((e) => ({
            source: e.source, target: e.target, distance: 320 - 140 * e.strength, pull: 0.08 + 0.6 * e.strength,
        })), {
            charge: -1000, pad: 70,
            forces: (sim) => sim
                .force('ax', d3.forceX((d) => (d.outsider ? anchor[d.id].x : 0)).strength((d) => (d.outsider ? 0.5 : 0.06)))
                .force('ay', d3.forceY((d) => (d.outsider ? anchor[d.id].y : 0)).strength((d) => (d.outsider ? 0.5 : 0.06))),
        });
        const npos = {};
        members.forEach((m) => { npos[m.id] = withGeo(pos[m.id], geo(m, 'group')); });
        outsiders.forEach((x) => { npos[x.id] = withGeo(pos[x.id], geo(x, 'outer')); });
        positions = {};
        members.forEach((m) => { positions[m.id] = npos[m.id]; });
        computeBounds(Object.values(npos), 20);

        drawEdges(layer('edges'), shown.map((e) => ({
            ...e, key: edgeKey(e.source, e.target), a: npos[e.source], b: npos[e.target],
            dim: !(memberSet.has(e.source) && memberSet.has(e.target)), tip: () => edgeTip(e),
        })), update);
        drawNodes(layer('nodes'), members.map((m) => ({
            id: m.id, node: m, pos: npos[m.id], mastery: m.mastery, value: m.mastery_value, ideas: m.ideas, label: m.title,
            avoid: avoidFor(m.id, shown, npos), zoom: m.ideas.length > 0,
            tip: () => conceptTip(m) + opensTip(m), onClick: () => go('#/concept/' + m.id),
        })).concat(outsiders.map((x) => ({
            id: x.id, node: x, pos: npos[x.id], mastery: x.mastery, value: x.mastery_value, ideas: x.ideas, dim: true, label: x.title,
            labelOpts: { size: 10.5, weight: 400, fill: INK2 }, avoid: avoidFor(x.id, shown, npos), zoom: x.ideas.length > 0,
            tip: () => conceptTip(x) + '<br>in ' + x.group + opensTip(x), onClick: () => go('#/concept/' + x.id),
        }))), update);
    }

    // ---------- Scene: concept ----------
    // The concept is one large neuron: each spoke is a key idea, labelled at
    // its tip with its own strength. Axons reach the connected concepts on the
    // outer ring, strongest first.
    function renderConcept(update) {
        const c = nodeById(view.conceptId);
        if (!c) return go('');
        const npos = {};
        npos[c.id] = withGeo({ x: 0, y: 0 }, geo(c, 'concept'));
        const linked = data.edges.filter((e) => e.source === c.id || e.target === c.id)
            .map((e) => ({ e, other: nodeById(e.source === c.id ? e.target : e.source) }))
            .sort((a, b) => b.e.strength - a.e.strength);
        const nl = Math.max(linked.length, 1);
        const linkAngle = {};
        linked.forEach(({ other }, i) => {
            const a = -Math.PI / 2 + (i + 0.5) * (Math.PI * 2 / nl);
            linkAngle[other.id] = a;
            npos[other.id] = withGeo({ x: 330 * Math.cos(a), y: 330 * Math.sin(a) }, geo(other, 'outer'));
        });
        positions = { [c.id]: npos[c.id] };
        linked.forEach(({ other }) => { positions[other.id] = npos[other.id]; });
        computeBounds(Object.values(npos), 30);
        bounds.x0 -= 50; bounds.x1 += 50;

        drawEdges(layer('edges'), linked.map(({ e, other }) => ({
            ...e, key: edgeKey(e.source, e.target), a: npos[c.id], b: npos[other.id], tip: () => edgeTip(e),
        })), update);

        const centre = {
            id: c.id, node: c, pos: npos[c.id], mastery: c.mastery, value: c.mastery_value, ideas: c.ideas,
            labelSpokes: true, avoid: linked.map(({ other }) => linkAngle[other.id]),
            tip: () => conceptTip(c) + '<br>click to practice', onClick: () => openDrawer(c.id),
        };
        drawNodes(layer('nodes'), [centre].concat(linked.map(({ other }) => ({
            id: other.id, node: other, pos: npos[other.id], mastery: other.mastery, value: other.mastery_value, ideas: other.ideas,
            dim: true, label: other.title, labelOpts: { size: 10.5, weight: 400, fill: INK2 }, labelAngle: linkAngle[other.id],
            avoid: [linkAngle[other.id] + Math.PI], zoom: other.ideas.length > 0,
            tip: () => conceptTip(other) + opensTip(other), onClick: () => go('#/concept/' + other.id),
        }))), update);

        // Faint chords between related key ideas, tip to tip
        const il = layer('idealinks');
        il.selectAll('*').remove();
        (c.idea_links || []).forEach(([a, b]) => {
            const ta = centre.spokeTips && centre.spokeTips[a], tb = centre.spokeTips && centre.spokeTips[b];
            if (!ta || !tb) return;
            const dx = tb.x - ta.x, dy = tb.y - ta.y, dd = Math.hypot(dx, dy) || 1;
            glyphRun(il, dotsAlong(ta.x + (dx / dd) * (ta.sat + 6), ta.y + (dy / dd) * (ta.sat + 6), tb.x - (dx / dd) * (tb.sat + 6), tb.y - (dy / dd) * (tb.sat + 6), 6), '·',
                { size: 7, fill: PALE });
        });
        il.lower();
    }

    // ---------- Motion: in-place character animation ----------
    // Nothing moves across the screen; characters change where they sit.
    //   axons   a signal runs down the dots as ● • · substitutions
    //   spokes  a wave of ● travels outward along filled dendrites
    //   rings   one bright glyph slowly orbits the cell body
    // Frequency and speed scale with strength; weak or unpractised parts stay still.
    const timers = new Map();
    let lastFrame = 0;
    function swap(base, at, head, trail) {
        const c = base.split('');
        for (let k = 0; k < trail.length + 1; k++) {
            const i = at - k;
            if (i >= 0 && i < c.length) c[i] = k === 0 ? head : trail[k - 1];
        }
        return c.join('');
    }
    function cycle(key, now, s, minGap, maxGap) {
        let t = timers.get(key);
        if (!t) { t = { next: now + hash(key) * maxGap, start: -1 }; timers.set(key, t); }
        return t;
    }
    function motion(now) {
        if (!REDUCED && !document.hidden && !transitioning && now - lastFrame > 45) {
            lastFrame = now;
            liveEdges.forEach((d) => {
                const es = d.hot ? 0.9 : d.strength;
                const t = cycle('e' + d.key, now, es, 1500, 8000);
                const n = d.shaft.base.length;
                if (t.start < 0 && now > t.next) { t.start = now; t.dur = n * (55 - 30 * es); }
                if (t.start >= 0) {
                    const p = (now - t.start) / t.dur;
                    if (p >= 1) {
                        d.shaft.el.text(d.shaft.base);
                        t.start = -1;
                        t.next = now + (8000 - 6500 * es) * (0.7 + 0.6 * hash(d.key + Math.floor(now)));
                    } else {
                        d.shaft.el.text(swap(d.shaft.base, Math.floor(p * n), '●', ['•', '•']));
                    }
                }
            });
            liveSpokes.forEach((sp) => {
                const t = cycle('s' + sp.key, now, sp.s, 2000, 9000);
                const n = sp.base.length;
                if (t.start < 0 && now > t.next) { t.start = now; t.dur = Math.max(400, n * (90 - 50 * sp.s)); }
                if (t.start >= 0) {
                    const p = (now - t.start) / t.dur;
                    if (p >= 1) {
                        sp.el.text(sp.base);
                        t.start = -1;
                        t.next = now + (9000 - 7000 * sp.s) * (0.6 + 0.8 * hash(sp.key + Math.floor(now)));
                    } else {
                        sp.el.text(swap(sp.base, Math.floor(p * (n + 1)), '●', []));
                    }
                }
            });
            liveRings.forEach((rg) => {
                const period = 14000 - 9000 * rg.s;
                const i = Math.floor(((now + hash(rg.key) * period) % period) / period * rg.n);
                const c = '·'.repeat(rg.n).split('');
                c[i] = '●';
                c[(i - 1 + rg.n) % rg.n] = '•';
                if (rg.s > 0.6) c[(i - 2 + rg.n) % rg.n] = '•';
                rg.el.text(c.join(''));
            });
        }
        requestAnimationFrame(motion);
    }

    // ---------- Render + transitions ----------
    function sceneKey() { return view.level + ':' + (view.conceptId || view.groupId || ''); }
    function draw(update) {
        liveEdges = [];
        liveSpokes = [];
        liveRings = [];
        timers.clear();
        layer('sparks').selectAll('*').remove();
        if (view.level === 'map') renderMap(update);
        else if (view.level === 'group') renderGroup(update);
        else renderConcept(update);
        layer('sparks').raise();
        layer('nodes').raise();
    }
    function settle(t, ms) {
        return Promise.race([t.end().catch(() => {}), new Promise((r) => setTimeout(r, ms + 120))]);
    }
    let routeSeq = 0;

    async function transitionTo(next, direction) {
        const seq = ++routeSeq;
        transitioning = true;
        hideTip();
        sceneWrap.interrupt();
        const o = direction === 'down' && positions[next.focus] ? positions[next.focus] : { x: 0, y: 0 };
        const out = direction === 'down' ? 'translate(' + (-o.x * 1.4) + ',' + (-o.y * 1.4) + ') scale(2.4)' : 'scale(0.6)';
        await settle(sceneWrap.transition().duration(360).ease(d3.easeCubicIn).attr('transform', out).style('opacity', 0), 360);
        if (seq !== routeSeq) return;
        sceneWrap.interrupt();
        sceneWrap.selectAll('*').remove();
        view = next;
        renderedKey = sceneKey();
        draw(false);
        updateChrome();
        fit(0);
        sceneWrap.attr('transform', direction === 'down' ? 'scale(0.7)' : 'scale(1.4)').style('opacity', 0);
        await settle(sceneWrap.transition().duration(440).ease(d3.easeCubicOut).attr('transform', 'scale(1)').style('opacity', 1), 440);
        if (seq !== routeSeq) return;
        sceneWrap.interrupt().attr('transform', null).style('opacity', 1);
        transitioning = false;
    }

    const depth = (lvl) => ({ map: 0, group: 1, concept: 2 }[lvl]);
    function parseHash() {
        const m = location.hash.match(/^#\/(group|concept)\/(.+)$/);
        if (!m) return { level: 'map', groupId: null, conceptId: null };
        if (m[1] === 'group') return { level: 'group', groupId: m[2], conceptId: null };
        const c = data && nodeById(m[2]);
        return { level: 'concept', groupId: c ? c.group_id : null, conceptId: m[2] };
    }

    async function route() {
        const next = parseHash();
        if (next.level === 'concept' && !nodeById(next.conceptId)) return go('');
        if (next.level === 'group' && !groupById(next.groupId)) return go('');
        const key = next.level + ':' + (next.conceptId || next.groupId || '');
        if (key === renderedKey) return;
        next.focus = next.conceptId || next.groupId;
        if (next.level === 'concept') root.classList.add('drawer-open');
        else root.classList.remove('drawer-open');
        if (renderedKey === null) {
            view = next;
            renderedKey = key;
            draw(false);
            updateChrome();
            fit(0);
        } else {
            await transitionTo(next, depth(next.level) >= depth(view.level) ? 'down' : 'up');
        }
        if (view.level === 'concept') openDrawer(view.conceptId);
        else closeDrawer(true);
    }

    function go(hash) {
        if (location.hash === hash || (!hash && !location.hash)) return route();
        if (hash) location.hash = hash;
        else { history.pushState('', document.title, location.pathname); route(); }
    }
    window.addEventListener('hashchange', route);
    function up() {
        if (view.level === 'concept') go('#/group/' + view.groupId);
        else if (view.level === 'group') go('');
    }

    function semanticZoom(t, ev) {
        if (transitioning) return;
        const rel = t.k / fitTransform.k;
        if (rel > 2.1 && view.level !== 'concept') {
            const r = svg.node().getBoundingClientRect();
            const [wx, wy] = t.invert([ev.clientX - r.left, ev.clientY - r.top]);
            let best = null, bestD = Infinity;
            Object.entries(positions).forEach(([id, p]) => {
                const d = Math.hypot(p.x - wx, p.y - wy) - p.r;
                if (d < bestD) { bestD = d; best = id; }
            });
            if (best && bestD < 160) go(view.level === 'map' ? '#/group/' + best : '#/concept/' + best);
        } else if (rel < 0.6 && view.level !== 'map') {
            up();
        }
    }

    // ---------- Chrome ----------
    const trailEl = document.getElementById('crumb-trail');
    const upBtn = document.getElementById('map-up');
    const levelHint = document.getElementById('level-hint');
    const practiceBtn = document.getElementById('practice-btn');
    const drawerEl = document.getElementById('drawer');
    const drawerVisible = () => drawerEl.getAttribute('aria-hidden') === 'false';

    function updateTitle() {
        const eyebrow = document.getElementById('map-eyebrow');
        const heading = document.getElementById('map-heading');
        if (view.level === 'map') {
            eyebrow.textContent = 'Mind map · ' + data.groups.length + ' groups · ' + data.nodes.length + ' concepts';
            heading.textContent = 'Everything you know';
        } else if (view.level === 'group') {
            const g = groupById(view.groupId);
            eyebrow.textContent = 'Group · ' + g.concept_ids.length + ' concepts · ' + (g.studied ? pct(g.strength) + ' average memory' : 'not practiced yet');
            heading.textContent = g.name;
        } else {
            const c = nodeById(view.conceptId);
            eyebrow.textContent = 'Concept · ' + c.group;
            heading.textContent = c.title;
        }
    }

    function updateChrome() {
        const parts = [{ label: 'Mind map', hash: '' }];
        const g = view.groupId && groupById(view.groupId);
        if (g) parts.push({ label: g.name, hash: '#/group/' + g.id });
        if (view.level === 'concept') parts.push({ label: nodeById(view.conceptId).title, hash: null });
        trailEl.innerHTML = '';
        parts.forEach((p, i) => {
            if (i) trailEl.insertAdjacentHTML('beforeend', '<span class="sep">/</span>');
            const b = document.createElement('button');
            b.type = 'button';
            const last = i === parts.length - 1;
            b.className = last ? 'is-current' : '';
            b.textContent = p.label;
            if (!last) b.addEventListener('click', () => go(p.hash));
            trailEl.appendChild(b);
        });
        upBtn.disabled = view.level === 'map';
        levelHint.textContent = { map: 'Click a group, or scroll to zoom in', group: 'Click a concept to see its key ideas', concept: 'Esc to go up a level' }[view.level];
        practiceBtn.hidden = view.level !== 'concept' || drawerVisible();
        levelHint.hidden = !practiceBtn.hidden;
        updateTitle();
        refreshToast();
    }
    upBtn.addEventListener('click', up);
    practiceBtn.addEventListener('click', () => openDrawer(view.conceptId));
    document.querySelectorAll('[data-group-link]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        go('#/group/' + a.dataset.groupLink);
    }));

    // ---------- Practice drawer ----------
    const drawerFrame = document.getElementById('drawer-frame');
    let drawerFor = null;
    function paintDrawerHead(c) {
        document.getElementById('drawer-title').textContent = c.title;
        document.getElementById('drawer-orb').className = 'orb ' + c.mastery;
        document.getElementById('drawer-sub').textContent = c.group + ' · ' +
            (c.mastery === 'not_started' ? 'not practiced yet' : pct(c.mastery_value) + ' memory strength');
        document.getElementById('drawer-note').href = '/notes/' + c.id;
    }
    // Ask the tutor for a question on one specific key idea
    let pendingReview = null;
    function reviewIdea(conceptId, ideaId) {
        const send = () => drawerFrame.contentWindow &&
            drawerFrame.contentWindow.postMessage({ type: 'nsf:review-idea', idea: ideaId }, location.origin);
        if (view.level === 'concept' && view.conceptId === conceptId && drawerFor === conceptId && drawerVisible()) {
            send();
        } else {
            pendingReview = { conceptId, ideaId };
            go('#/concept/' + conceptId);
        }
    }
    drawerFrame.addEventListener('load', () => {
        if (pendingReview && pendingReview.conceptId === drawerFor) {
            const idea = pendingReview.ideaId;
            pendingReview = null;
            setTimeout(() => drawerFrame.contentWindow.postMessage({ type: 'nsf:review-idea', idea }, location.origin), 300);
        }
    });

    function openDrawer(id) {
        const c = nodeById(id);
        if (!c) return;
        paintDrawerHead(c);
        if (drawerFor !== id) { drawerFrame.src = '/notes/' + id + '/chat?embed=1'; drawerFor = id; }
        else if (pendingReview && pendingReview.conceptId === id) {
            const idea = pendingReview.ideaId;
            pendingReview = null;
            drawerFrame.contentWindow.postMessage({ type: 'nsf:review-idea', idea }, location.origin);
        }
        const wasLaidOut = root.classList.contains('drawer-open');
        root.classList.add('drawer-open');
        drawerEl.setAttribute('aria-hidden', 'false');
        updateChrome();
        if (!wasLaidOut) fit(450);
    }
    function closeDrawer(silent) {
        if (root.classList.contains('drawer-max')) setMax(false);
        if (quiz) { quiz = null; if (renderedKey !== null) draw(true); }
        const was = drawerVisible() || root.classList.contains('drawer-open');
        root.classList.remove('drawer-open');
        drawerEl.setAttribute('aria-hidden', 'true');
        if (!was) return;
        updateChrome();
        fit(silent ? 0 : 450);
    }
    document.getElementById('drawer-close').addEventListener('click', () => closeDrawer());
    // Maximize: practice takes over the screen when the map is distracting
    const maxBtn = document.getElementById('drawer-max');
    function setMax(on) {
        root.classList.toggle('drawer-max', on);
        maxBtn.innerHTML = on ? '<i data-lucide="minimize-2"></i>' : '<i data-lucide="maximize-2"></i>';
        maxBtn.title = on ? 'Show the map again' : 'Focus on practice (hide the map)';
        window.NSF && window.NSF.icons();
    }
    maxBtn.addEventListener('click', () => setMax(!root.classList.contains('drawer-max')));

    window.addEventListener('message', async (event) => {
        if (event.origin !== location.origin) return;
        const msg = event.data || {};
        if (msg.type === 'nsf:focus') {
            if (msg.noteId !== drawerFor) return;
            quiz = { noteId: msg.noteId, idea: msg.idea, related: msg.related || [] };
            if (renderedKey !== null) draw(true);
            return;
        }
        if (msg.type !== 'nsf:update') return;
        await refresh();
        const c = nodeById(msg.noteId);
        if (c) paintDrawerHead(c);
        (msg.reinforced || []).forEach(firePulse);
    });

    // The connection that was just exercised fires immediately, in place
    function firePulse(r) {
        const d = liveEdges.find((x) => x.key === edgeKey(r.source, r.target));
        if (!d || !d.shaft) return;
        d.shaft.el.attr('fill', r.correct ? ACCENT : STATUS.red)
            .transition().delay(1200).duration(900).attr('fill', d.ink || edgeInk(d.strength));
        const t = timers.get('e' + d.key) || {};
        t.start = performance.now() + 150;
        t.dur = d.shaft.base.length * 30;
        timers.set('e' + d.key, t);
    }

    // ---------- Data ----------
    async function refresh() {
        data = await (await fetch('/api/graph-data')).json();
        if (renderedKey !== null) draw(true);
        syncSlider(data.clock_offset_days);
        if (renderedKey !== null) updateTitle();
    }

    // ---------- Time travel ----------
    const slider = document.getElementById('time-slider');
    const timeValue = document.getElementById('time-value');
    const timeHint = document.getElementById('time-hint');
    let clockTimer = null;
    function paintSlider(days) {
        days = Math.round(days);
        timeValue.textContent = days === 0 ? 'today' : '+' + days + (days === 1 ? ' day' : ' days');
        timeHint.textContent = days > 0 ? 'simulating ' + days + ' days without review' : 'drag to see what fades';
        root.classList.toggle('is-time-travel', days > 0);
        slider.style.setProperty('--fill', (days / Number(slider.max)) * 100 + '%');
    }
    function syncSlider(days) {
        if (document.activeElement === slider) return;
        slider.value = Math.round(days || 0);
        paintSlider(days || 0);
    }
    slider.addEventListener('input', () => {
        const days = Number(slider.value);
        paintSlider(days);
        clearTimeout(clockTimer);
        clockTimer = setTimeout(async () => {
            await fetch('/api/clock', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ offset_days: days }) });
            await refresh();
            if (drawerFor && drawerVisible()) {
                drawerFrame.contentWindow?.location.reload();
                const c = nodeById(drawerFor);
                if (c) paintDrawerHead(c);
            }
            refreshToast();
        }, 120);
    });

    // ---------- Unreviewed-concepts toast ----------
    const toast = document.getElementById('debt-toast');
    let debtTarget = null;
    const toastDismissed = () => { try { return !!sessionStorage.getItem('nsf-debt-dismissed'); } catch (e) { return false; } };
    async function refreshToast() {
        if (view.level !== 'map' || toastDismissed()) { toast.hidden = true; return; }
        try {
            const d = await (await fetch('/api/cognitive-debt')).json();
            if (d.debt_count > 0) {
                document.getElementById('debt-title').textContent = d.debt_count + ' saved, never recalled';
                document.getElementById('debt-message').textContent =
                    'Capturing is easy. Recalling is what makes it stick. Start with the most connected one.';
                debtTarget = d.nodes[0].note_id;
                toast.hidden = view.level !== 'map';
            } else toast.hidden = true;
        } catch (e) { toast.hidden = true; }
    }
    document.getElementById('debt-cta').addEventListener('click', () => debtTarget && go('#/concept/' + debtTarget));
    document.getElementById('debt-dismiss').addEventListener('click', () => {
        toast.hidden = true;
        try { sessionStorage.setItem('nsf-debt-dismissed', '1'); } catch (e) {}
    });

    // ---------- Legend, zoom, keys, resize ----------
    const legend = document.getElementById('legend');
    const legendBtn = document.getElementById('legend-btn');
    legendBtn.addEventListener('click', () => {
        legend.hidden = !legend.hidden;
        legendBtn.setAttribute('aria-expanded', String(!legend.hidden));
    });
    document.getElementById('zoom-in').addEventListener('click', () => svg.transition().duration(300).call(zoom.scaleBy, 1.3));
    document.getElementById('zoom-out').addEventListener('click', () => svg.transition().duration(300).call(zoom.scaleBy, 0.77));
    document.getElementById('zoom-fit').addEventListener('click', () => fit(450));
    document.addEventListener('keydown', (e) => {
        if (/INPUT|TEXTAREA/.test(document.activeElement?.tagName)) return;
        if (!document.getElementById('palette')?.hidden) return;
        if (e.key === 'Escape') {
            if (!legend.hidden) legend.hidden = true;
            else up();
        }
    });
    function resize() {
        const w = root.clientWidth, h = root.clientHeight;
        svg.attr('width', w).attr('height', h);
        bg.attr('width', w).attr('height', h);
    }
    window.addEventListener('resize', () => { resize(); fit(0); });

    window.NSFMap = { go, refresh };
    resize();
    (document.fonts ? document.fonts.ready : Promise.resolve()).then(refresh).then(route);
    requestAnimationFrame(motion);
})();

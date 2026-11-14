/*
 * Knowledge graph.
 *
 * Nodes  = topics, colored by memory strength (decayed mastery).
 * Edges  = connections between topics. Thickness, brightness and pull are
 *          driven by connection strength, which only grows when the learner
 *          retrieves two ideas *together* and fades over time without review.
 *
 * The graph re-renders in place (keyed d3 joins) so it can react live to
 * answers in the practice drawer and to the time-travel slider.
 */
document.addEventListener('DOMContentLoaded', function () {
    const container = document.getElementById('knowledge-graph');
    if (!container) return;

    const DRAWER_WIDTH = 440;
    const masteryColors = {
        green: '#34d399',
        yellow: '#fbbf24',
        red: '#f87171',
        not_started: '#4b4b4b',
    };
    const edgeColor = d3.interpolateRgb('#35505e', '#a5f3fc');
    const clusterColor = d3.scaleOrdinal()
        .range(['#34d399', '#fbbf24', '#f87171', '#60a5fa', '#a78bfa', '#f472b6', '#fb923c', '#38bdf8']);

    const edgeKey = (a, b) => [a, b].sort().join('|');
    const idOf = (end) => (typeof end === 'object' ? end.id : end);
    const nodeRadius = (d) => (d.mastery === 'not_started' ? 16 : 16 + 12 * d.mastery_value);
    const edgeWidth = (s) => (s <= 0 ? 1 : 1.5 + 7 * s);
    const edgeStroke = (s) => (s <= 0 ? '#2e2e2e' : edgeColor(Math.min(1, s * 1.15)));
    const edgeOpacity = (s) => (s <= 0 ? 0.5 : 0.35 + 0.6 * s);

    // ---------- SVG scaffolding ----------
    const svg = d3.select('#graph-svg');
    let width = container.clientWidth;
    let height = container.clientHeight;
    svg.attr('width', width).attr('height', height);

    const defs = svg.append('defs');
    const pattern = defs.append('pattern')
        .attr('id', 'dot-pattern').attr('width', 24).attr('height', 24)
        .attr('patternUnits', 'userSpaceOnUse');
    pattern.append('circle').attr('cx', 12).attr('cy', 12).attr('r', 1).attr('fill', '#2a2a2a');

    const glow = defs.append('filter').attr('id', 'edge-glow')
        .attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%');
    glow.append('feGaussianBlur').attr('stdDeviation', 3).attr('result', 'blur');
    const merge = glow.append('feMerge');
    merge.append('feMergeNode').attr('in', 'blur');
    merge.append('feMergeNode').attr('in', 'SourceGraphic');

    const bg = svg.append('rect').attr('width', width).attr('height', height)
        .attr('fill', 'url(#dot-pattern)');

    const g = svg.append('g');
    const zoom = d3.zoom().scaleExtent([0.2, 5])
        .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    const hullLayer = g.append('g').attr('class', 'graph-hulls');
    const potentialLayer = g.append('g').attr('class', 'graph-potential-links');
    const hitLayer = g.append('g').attr('class', 'graph-link-hit');
    const linkLayer = g.append('g').attr('class', 'graph-links');
    const pulseLayer = g.append('g').attr('class', 'graph-pulses').style('pointer-events', 'none');
    const nodeLayer = g.append('g').attr('class', 'graph-nodes');

    const tooltip = d3.select(container).append('div')
        .attr('class', 'graph-tooltip').style('display', 'none');

    function showTip(event, html) {
        const rect = container.getBoundingClientRect();
        tooltip.html(html).style('display', 'block')
            .style('left', (event.clientX - rect.left + 14) + 'px')
            .style('top', (event.clientY - rect.top - 10) + 'px');
    }
    const hideTip = () => tooltip.style('display', 'none');

    // ---------- State ----------
    let nodes = [];
    let edges = [];
    let potential = [];
    let clusterCenters = {};
    let selectedId = null;
    let firstLoad = true;
    let needsFit = true;

    const simulation = d3.forceSimulation()
        .force('link', d3.forceLink().id((d) => d.id)
            .distance((d) => 230 - 120 * d.strength)
            .strength((d) => 0.03 + 0.6 * d.strength))
        .force('charge', d3.forceManyBody().strength(-420))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius((d) => nodeRadius(d) + 26))
        .force('clusterX', d3.forceX((d) => (clusterCenters[d.cluster] || { x: centerX() }).x).strength(0.04))
        .force('clusterY', d3.forceY((d) => (clusterCenters[d.cluster] || { y: height / 2 }).y).strength(0.04))
        .on('tick', ticked);

    function centerX() {
        return container.classList.contains('drawer-open') ? (width - DRAWER_WIDTH) / 2 : width / 2;
    }

    function layoutClusters(names) {
        const step = (2 * Math.PI) / Math.max(names.length, 1);
        const r = Math.min(width, height) * 0.2;
        clusterCenters = {};
        names.forEach((name, i) => {
            clusterCenters[name] = {
                x: centerX() + r * Math.cos(i * step - Math.PI / 2),
                y: height / 2 + r * Math.sin(i * step - Math.PI / 2),
            };
        });
    }

    // ---------- Tooltip copy ----------
    function nodeTip(d) {
        if (d.mastery === 'not_started') {
            return '<strong>' + d.title + '</strong><br>Never practiced. Click to start.';
        }
        const last = d.days_since === null ? '' :
            '<br>Last practiced ' + (d.days_since < 1 ? 'today' : Math.round(d.days_since) + 'd ago');
        return '<strong>' + d.title + '</strong><br>Memory strength ' +
            Math.round(d.mastery_value * 100) + '% · ' + d.review_count + ' reviews' + last;
    }

    function edgeTip(d) {
        const names = d.source.title + ' ↔ ' + d.target.title;
        if (!d.review_count) {
            return '<strong>' + names + '</strong><br>Never practiced together' +
                (d.shared_tags.length ? '<br><span class="tip-muted">Shared: ' + d.shared_tags.join(', ') + '</span>' : '');
        }
        const fade = d.days_to_fade ? 'Fades in ~' + Math.round(d.days_to_fade) + 'd without review' : 'Fading. Review to rebuild';
        return '<strong>' + names + '</strong><br>Connection strength ' + Math.round(d.strength * 100) + '%' +
            '<br>Practiced together ' + d.review_count + '× · half-life ' + d.half_life + 'd' +
            '<br><span class="tip-muted">' + fade + '</span>';
    }

    // ---------- Render ----------
    function render(transition) {
        const dur = transition ? 700 : 0;

        // Suggested (similarity) links
        potentialLayer.selectAll('path')
            .data(potential, (d) => edgeKey(d.source, d.target))
            .join('path')
            .attr('stroke', '#555').attr('stroke-width', 1)
            .attr('stroke-dasharray', '3 5').attr('stroke-opacity', 0.35).attr('fill', 'none')
            .on('mouseenter mousemove', (event, d) => showTip(event,
                '<strong>Suggested link</strong><br>' + Math.round(d.similarity * 100) +
                '% similar content, but never connected'))
            .on('mouseleave', hideTip);

        // Edge hit areas (wide, invisible) for hover
        hitLayer.selectAll('path')
            .data(edges, (d) => d.key)
            .join('path')
            .attr('stroke', 'transparent').attr('stroke-width', 14).attr('fill', 'none')
            .style('cursor', 'help')
            .on('mouseenter mousemove', (event, d) => showTip(event, edgeTip(d)))
            .on('mouseleave', hideTip);

        // Visible edges
        linkLayer.selectAll('path')
            .data(edges, (d) => d.key)
            .join(
                (enter) => enter.append('path').attr('fill', 'none').attr('stroke-linecap', 'round')
                    .attr('stroke-width', 0),
                (update) => update,
                (exit) => exit.remove(),
            )
            .attr('data-key', (d) => d.key)
            .attr('filter', (d) => (d.strength > 0.5 ? 'url(#edge-glow)' : null))
            .attr('stroke-dasharray', (d) => (d.strength <= 0 ? '2 4' : null))
            .transition().duration(dur)
            .attr('stroke', (d) => edgeStroke(d.strength))
            .attr('stroke-width', (d) => edgeWidth(d.strength))
            .attr('stroke-opacity', (d) => edgeOpacity(d.strength));

        // Nodes
        const node = nodeLayer.selectAll('g.graph-node')
            .data(nodes, (d) => d.id)
            .join((enter) => {
                const n = enter.append('g').attr('class', 'graph-node').style('cursor', 'pointer');
                n.append('circle').attr('class', 'node-halo').attr('fill-opacity', 0.12);
                n.append('circle').attr('class', 'node-ring').attr('fill', 'none')
                    .attr('stroke', '#fff').attr('stroke-width', 2).attr('stroke-opacity', 0);
                n.append('circle').attr('class', 'node-core').attr('stroke-width', 2);
                n.append('text').attr('class', 'node-label').attr('text-anchor', 'middle')
                    .attr('fill', '#e8e8e8').attr('font-size', '11px')
                    .attr('font-family', "'Inter', system-ui, sans-serif")
                    .style('pointer-events', 'none');
                n.call(d3.drag().on('start', dragstarted).on('drag', dragged).on('end', dragended));
                n.on('click', (event, d) => {
                    if (event.defaultPrevented) return;
                    openNode(d.id);
                });
                n.on('mouseenter', function (event, d) {
                    d3.select(this).select('.node-core').transition().duration(150)
                        .attr('r', nodeRadius(d) + 4);
                    showTip(event, nodeTip(d));
                });
                n.on('mousemove', (event, d) => showTip(event, nodeTip(d)));
                n.on('mouseleave', function (event, d) {
                    d3.select(this).select('.node-core').transition().duration(150)
                        .attr('r', nodeRadius(d));
                    hideTip();
                });
                return n;
            });

        node.select('.node-halo').transition().duration(dur)
            .attr('r', (d) => nodeRadius(d) + 9)
            .attr('fill', (d) => masteryColors[d.mastery]);
        node.select('.node-core').transition().duration(dur)
            .attr('r', (d) => nodeRadius(d))
            .attr('fill', (d) => masteryColors[d.mastery])
            .attr('fill-opacity', (d) => (d.mastery === 'not_started' ? 0.5 : 0.9))
            .attr('stroke', (d) => masteryColors[d.mastery]);
        node.select('.node-ring')
            .attr('r', (d) => nodeRadius(d) + 6)
            .attr('stroke-opacity', (d) => (d.id === selectedId ? 0.9 : 0));
        node.select('.node-label')
            .attr('dy', (d) => nodeRadius(d) + 18)
            .text((d) => (d.title.length > 22 ? d.title.substring(0, 21) + '…' : d.title));

        applySearch();
        ticked();
    }

    function ticked() {
        const line = (s, t) => 'M' + s.x + ',' + s.y + ' L' + t.x + ',' + t.y;
        linkLayer.selectAll('path').attr('d', (d) => line(d.source, d.target));
        hitLayer.selectAll('path').attr('d', (d) => line(d.source, d.target));
        potentialLayer.selectAll('path').attr('d', (d) => line(d.sourceNode, d.targetNode));
        nodeLayer.selectAll('g.graph-node').attr('transform', (d) => 'translate(' + d.x + ',' + d.y + ')');
        updateHulls();
        if (needsFit && nodes.length && simulation.alpha() < 0.08) {
            needsFit = false;
            fitView();
        }
    }

    // Frame all nodes in the visible area (left of the drawer, above the time-travel bar)
    function fitView() {
        const pad = 70;
        const availW = container.classList.contains('drawer-open') ? width - DRAWER_WIDTH : width;
        const availH = height - 110;
        const x0 = d3.min(nodes, (d) => d.x) - pad, x1 = d3.max(nodes, (d) => d.x) + pad;
        const y0 = d3.min(nodes, (d) => d.y) - pad, y1 = d3.max(nodes, (d) => d.y) + pad;
        const k = Math.min(1.3, availW / (x1 - x0), availH / (y1 - y0));
        const t = d3.zoomIdentity
            .translate(availW / 2 - k * (x0 + x1) / 2, availH / 2 + 10 - k * (y0 + y1) / 2)
            .scale(k);
        svg.transition().duration(700).ease(d3.easeCubicInOut).call(zoom.transform, t);
    }

    function updateHulls() {
        const groups = d3.groups(nodes.filter((n) => n.x !== undefined), (n) => n.cluster)
            .filter(([, members]) => members.length >= 2)
            .map(([name, members]) => {
                const cx = d3.mean(members, (d) => d.x);
                const cy = d3.mean(members, (d) => d.y);
                const r = d3.max(members, (d) => Math.hypot(d.x - cx, d.y - cy)) + 60;
                return { name, cx, cy, r };
            });
        hullLayer.selectAll('circle').data(groups, (d) => d.name).join('circle')
            .attr('cx', (d) => d.cx).attr('cy', (d) => d.cy).attr('r', (d) => d.r)
            .attr('fill', (d) => clusterColor(d.name)).attr('fill-opacity', 0.025)
            .attr('stroke', (d) => clusterColor(d.name)).attr('stroke-opacity', 0.1)
            .style('pointer-events', 'none');
        hullLayer.selectAll('text').data(groups, (d) => d.name).join('text')
            .attr('x', (d) => d.cx).attr('y', (d) => d.cy - d.r - 8)
            .attr('text-anchor', 'middle').attr('fill', (d) => clusterColor(d.name))
            .attr('fill-opacity', 0.4).attr('font-size', '12px').attr('font-weight', 600)
            .attr('font-family', "'Inter', system-ui, sans-serif")
            .text((d) => d.name);
    }

    // ---------- Data loading ----------
    async function refresh(opts) {
        opts = opts || {};
        const res = await fetch('/api/graph-data');
        const data = await res.json();

        const previous = new Map(nodes.map((n) => [n.id, n]));
        nodes = data.nodes.map((n) => {
            const kept = previous.get(n.id);
            const fresh = Object.assign(kept || {
                x: centerX() + (Math.random() - 0.5) * 80,
                y: height / 2 + (Math.random() - 0.5) * 80,
            }, n);
            fresh.cluster = n.tags[0] || 'uncategorized';
            return fresh;
        });
        const byId = new Map(nodes.map((n) => [n.id, n]));
        edges = data.edges.map((e) => Object.assign({}, e, { key: edgeKey(e.source, e.target) }));
        potential = (data.potential_connections || []).map((p) => Object.assign({}, p, {
            sourceNode: byId.get(p.source), targetNode: byId.get(p.target),
        })).filter((p) => p.sourceNode && p.targetNode);

        if (firstLoad) layoutClusters(Object.keys(data.clusters || {}));

        simulation.nodes(nodes);
        simulation.force('link').links(edges);
        simulation.alpha(firstLoad ? 1 : (opts.gentle ? 0.08 : 0.3)).restart();

        render(!firstLoad);
        firstLoad = false;
        syncSlider(data.clock_offset_days);

        if (opts.reinforced && opts.reinforced.length) {
            opts.reinforced.forEach(firePulse);
        }
        if (opts.pulseNode) rippleNode(opts.pulseNode);
        document.dispatchEvent(new Event('nsf:graph-refreshed'));
    }

    // ---------- "Neural firing" animations ----------
    function firePulse(r) {
        const path = linkLayer.select('path[data-key="' + edgeKey(r.source, r.target) + '"]').node();
        if (!path) return;
        const color = r.correct ? '#a5f3fc' : '#f87171';
        const d = d3.select(path).datum();
        // Travel from the answered topic toward the connected one
        const forward = idOf(d.source) === r.source;
        const len = path.getTotalLength();
        for (let i = 0; i < 3; i++) {
            pulseLayer.append('circle')
                .attr('r', 5 - i).attr('fill', color).attr('filter', 'url(#edge-glow)')
                .attr('opacity', 1 - i * 0.25)
                .transition().delay(250 + i * 120).duration(900).ease(d3.easeCubicInOut)
                .attrTween('transform', () => (t) => {
                    const p = path.getPointAtLength(forward ? t * len : (1 - t) * len);
                    return 'translate(' + p.x + ',' + p.y + ')';
                })
                .remove();
        }
        rippleNode(r.target, color);
    }

    function rippleNode(id, color) {
        const n = nodes.find((x) => x.id === id);
        if (!n) return;
        pulseLayer.append('circle')
            .attr('cx', n.x).attr('cy', n.y).attr('r', nodeRadius(n))
            .attr('fill', 'none').attr('stroke', color || masteryColors[n.mastery]).attr('stroke-width', 3)
            .attr('opacity', 0.9)
            .transition().delay(color ? 1100 : 0).duration(900).ease(d3.easeCubicOut)
            .attr('r', nodeRadius(n) + 34).attr('opacity', 0)
            .remove();
    }

    // ---------- Practice drawer ----------
    const drawer = document.getElementById('chat-drawer');
    const frame = document.getElementById('chat-drawer-frame');
    const drawerTitle = document.getElementById('chat-drawer-title');
    const drawerDot = document.getElementById('chat-drawer-dot');
    const drawerOpen = document.getElementById('chat-drawer-open');

    function openNode(id) {
        const n = nodes.find((x) => x.id === id);
        if (!n || !drawer) {
            window.location.href = '/notes/' + id + '/chat';
            return;
        }
        selectedId = id;
        drawerTitle.textContent = n.title;
        drawerDot.style.background = masteryColors[n.mastery];
        drawerOpen.href = '/notes/' + id + '/chat';
        frame.src = '/notes/' + id + '/chat?embed=1';
        container.classList.add('drawer-open');
        drawer.setAttribute('aria-hidden', 'false');
        recenter();
        render(false);
    }

    function closeDrawer() {
        selectedId = null;
        container.classList.remove('drawer-open');
        drawer.setAttribute('aria-hidden', 'true');
        frame.src = 'about:blank';
        recenter();
        render(false);
    }

    function recenter() {
        needsFit = true;
        layoutClusters(Object.keys(clusterCenters));
        simulation.force('center', d3.forceCenter(centerX(), height / 2));
        simulation.alpha(0.3).restart();
    }

    document.getElementById('chat-drawer-close')?.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && container.classList.contains('drawer-open')) closeDrawer();
    });

    window.addEventListener('message', (event) => {
        if (event.origin !== window.location.origin) return;
        const msg = event.data || {};
        if (msg.type !== 'nsf:update') return;
        refresh({ reinforced: msg.reinforced, pulseNode: msg.noteId }).then(() => {
            const n = nodes.find((x) => x.id === msg.noteId);
            if (n && drawerDot) drawerDot.style.background = masteryColors[n.mastery];
        });
    });

    // ---------- Time travel ----------
    const slider = document.getElementById('time-travel-slider');
    const sliderValue = document.getElementById('time-travel-value');
    const sliderHint = document.getElementById('time-travel-hint');
    let clockTimer = null;

    function labelFor(days) {
        days = Math.round(days);
        if (days === 0) return 'Today';
        return '+' + days + (days === 1 ? ' day' : ' days');
    }

    function syncSlider(days) {
        if (!slider || document.activeElement === slider) return;
        slider.value = Math.round(days || 0);
        paintSlider(days || 0);
    }

    function paintSlider(days) {
        sliderValue.textContent = labelFor(days);
        container.classList.toggle('is-time-travel', days > 0);
        sliderHint.textContent = days > 0
            ? 'Simulating ' + Math.round(days) + ' days without review'
            : 'Drag to see what fades without review';
        slider.style.setProperty('--fill', (days / slider.max * 100) + '%');
    }

    if (slider) {
        slider.addEventListener('input', () => {
            const days = Number(slider.value);
            paintSlider(days);
            clearTimeout(clockTimer);
            clockTimer = setTimeout(async () => {
                await fetch('/api/clock', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ offset_days: days }),
                });
                await refresh({ gentle: true });
                // Reload the drawer so its mastery bar reflects the new date
                if (selectedId) frame.contentWindow?.location.reload();
            }, 120);
        });
    }

    document.getElementById('demo-reset')?.addEventListener('click', async () => {
        if (!confirm('Reset the demo? This restores the sample notes and review history and clears chats.')) return;
        await fetch('/api/demo/reset', { method: 'POST' });
        if (selectedId) closeDrawer();
        slider.value = 0;
        paintSlider(0);
        await refresh();
    });

    // ---------- Search ----------
    const searchInput = document.getElementById('graph-search');
    function applySearch() {
        const q = (searchInput?.value || '').trim().toLowerCase();
        const match = (d) => !q || d.title.toLowerCase().includes(q) ||
            d.tags.some((t) => t.toLowerCase().includes(q));
        nodeLayer.selectAll('g.graph-node').style('opacity', (d) => (match(d) ? 1 : 0.12));
        linkLayer.selectAll('path').style('opacity', (d) =>
            (!q || match(d.source) || match(d.target) ? null : 0.05));
    }
    searchInput?.addEventListener('input', applySearch);

    // ---------- Export ----------
    document.getElementById('graph-export-btn')?.addEventListener('click', () => {
        const exportData = {
            nodes: nodes.map((n) => ({ id: n.id, title: n.title, mastery: n.mastery,
                mastery_value: n.mastery_value, tags: n.tags })),
            edges: edges.map((e) => ({ source: idOf(e.source), target: idOf(e.target),
                strength: e.strength, review_count: e.review_count, shared_tags: e.shared_tags })),
            exported_at: new Date().toISOString(),
        };
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'knowledge-graph-export.json';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    });

    // ---------- Drag / zoom / resize ----------
    function dragstarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
    }
    function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
    function dragended(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null; d.fy = null;
    }

    document.getElementById('graph-zoom-in')?.addEventListener('click', () =>
        svg.transition().duration(300).call(zoom.scaleBy, 1.4));
    document.getElementById('graph-zoom-out')?.addEventListener('click', () =>
        svg.transition().duration(300).call(zoom.scaleBy, 0.7));

    window.addEventListener('resize', () => {
        width = container.clientWidth;
        height = container.clientHeight;
        svg.attr('width', width).attr('height', height);
        bg.attr('width', width).attr('height', height);
        recenter();
    });

    window.NSFGraph = { openNode, refresh };
    refresh();
});

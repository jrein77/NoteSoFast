document.addEventListener('DOMContentLoaded', async function () {
    const container = document.getElementById('knowledge-graph');
    if (!container) return;

    // Fetch graph data
    const response = await fetch('/api/graph-data');
    const data = await response.json();

    // Setup SVG
    const svg = d3.select('#graph-svg');
    let width = container.clientWidth;
    let height = container.clientHeight;
    svg.attr('width', width).attr('height', height);

    // Dotted background pattern
    const defs = svg.append('defs');
    const pattern = defs.append('pattern')
        .attr('id', 'dot-pattern')
        .attr('width', 24)
        .attr('height', 24)
        .attr('patternUnits', 'userSpaceOnUse');
    pattern.append('circle')
        .attr('cx', 12)
        .attr('cy', 12)
        .attr('r', 1)
        .attr('fill', '#333');

    // Background rect with dot pattern
    const bg = svg.append('rect')
        .attr('width', width)
        .attr('height', height)
        .attr('fill', 'url(#dot-pattern)');

    // Zoomable group
    const g = svg.append('g');

    // Zoom behavior
    const zoom = d3.zoom()
        .scaleExtent([0.2, 5])
        .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    // Mastery color map
    const masteryColors = {
        green: '#34d399',
        yellow: '#fbbf24',
        red: '#f87171',
        not_started: '#555555',
    };

    // Cluster colors
    const clusterColorScale = d3.scaleOrdinal()
        .range(['#34d399', '#fbbf24', '#f87171', '#60a5fa', '#a78bfa', '#f472b6', '#fb923c', '#38bdf8']);

    // Build cluster centers
    const clusterNames = Object.keys(data.clusters || {});
    const angleStep = (2 * Math.PI) / Math.max(clusterNames.length, 1);
    const clusterRadius = Math.min(width, height) * 0.2;
    const clusterCenters = {};
    clusterNames.forEach((name, i) => {
        clusterCenters[name] = {
            x: width / 2 + clusterRadius * Math.cos(i * angleStep - Math.PI / 2),
            y: height / 2 + clusterRadius * Math.sin(i * angleStep - Math.PI / 2),
        };
    });

    // Assign cluster to each node
    data.nodes.forEach(n => {
        n.cluster = n.tags[0] || 'uncategorized';
    });

    // Build node lookup
    const nodeById = {};
    data.nodes.forEach(n => { nodeById[n.id] = n; });

    // Resolve potential connections
    const potentialLinks = (data.potential_connections || []).map(pl => ({
        ...pl,
        sourceNode: nodeById[pl.source],
        targetNode: nodeById[pl.target],
    })).filter(pl => pl.sourceNode && pl.targetNode);

    // Force simulation
    const simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.edges).id(d => d.id).distance(160))
        .force('charge', d3.forceManyBody().strength(-400))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(50))
        .force('clusterX', d3.forceX(d => clusterCenters[d.cluster]?.x || width / 2).strength(0.04))
        .force('clusterY', d3.forceY(d => clusterCenters[d.cluster]?.y || height / 2).strength(0.04));

    // ===== Draw cluster hulls =====
    const hullGroup = g.append('g').attr('class', 'graph-hulls');

    function updateHulls() {
        hullGroup.selectAll('circle.cluster-circle').remove();
        clusterNames.forEach(name => {
            const clusterNodes = data.nodes.filter(n => n.cluster === name);
            if (clusterNodes.length >= 2) {
                const cx = d3.mean(clusterNodes, d => d.x);
                const cy = d3.mean(clusterNodes, d => d.y);
                // Calculate radius as max distance from centroid + padding
                let maxDist = 0;
                clusterNodes.forEach(n => {
                    const dist = Math.sqrt((n.x - cx) ** 2 + (n.y - cy) ** 2);
                    if (dist > maxDist) maxDist = dist;
                });
                const radius = maxDist + 60; // padding around outermost node
                hullGroup.append('circle')
                    .attr('class', 'cluster-circle')
                    .attr('cx', cx)
                    .attr('cy', cy)
                    .attr('r', radius)
                    .attr('fill', clusterColorScale(name))
                    .attr('fill-opacity', 0.03)
                    .attr('stroke', clusterColorScale(name))
                    .attr('stroke-opacity', 0.12)
                    .attr('stroke-width', 1)
                    .style('pointer-events', 'none');
            }
        });

        // Cluster labels
        hullGroup.selectAll('text').remove();
        clusterNames.forEach(name => {
            const clusterNodes = data.nodes.filter(n => n.cluster === name);
            if (clusterNodes.length > 0) {
                const cx = d3.mean(clusterNodes, d => d.x);
                const cy = d3.mean(clusterNodes, d => d.y);
                // Calculate radius for label positioning above circle
                let maxDist = 0;
                clusterNodes.forEach(n => {
                    const dist = Math.sqrt((n.x - cx) ** 2 + (n.y - cy) ** 2);
                    if (dist > maxDist) maxDist = dist;
                });
                const labelY = cy - (maxDist + 70);
                hullGroup.append('text')
                    .attr('x', cx)
                    .attr('y', labelY)
                    .attr('text-anchor', 'middle')
                    .attr('fill', clusterColorScale(name))
                    .attr('fill-opacity', 0.35)
                    .attr('font-size', '12px')
                    .attr('font-weight', '600')
                    .attr('font-family', "'Inter', system-ui, sans-serif")
                    .attr('class', 'cluster-label')
                    .text(name);
            }
        });
    }

    // ===== Draw potential connection lines (dotted) =====
    const potentialLinkGroup = g.append('g').attr('class', 'graph-potential-links');
    const potentialLink = potentialLinkGroup.selectAll('path')
        .data(potentialLinks)
        .join('path')
        .attr('stroke', '#444')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '4 4')
        .attr('stroke-opacity', 0.25)
        .attr('fill', 'none');

    // ===== Draw edges (as paths for animation) =====
    // Invisible hit areas for hover
    const linkHitArea = g.append('g')
        .attr('class', 'graph-link-hit')
        .selectAll('path')
        .data(data.edges)
        .join('path')
        .attr('stroke', 'transparent')
        .attr('stroke-width', 14)
        .attr('fill', 'none')
        .style('cursor', 'pointer');

    const link = g.append('g')
        .attr('class', 'graph-links')
        .selectAll('path')
        .data(data.edges)
        .join('path')
        .attr('stroke', d => masteryColors[d.mastery] || '#555')
        .attr('stroke-width', 2)
        .attr('stroke-opacity', 0.6)
        .attr('fill', 'none')
        .attr('class', d => 'graph-edge graph-edge--' + d.mastery);

    // Edge labels removed for cleaner graph readability (hover tooltips remain)

    // ===== Tooltip =====
    const tooltip = d3.select('#knowledge-graph')
        .append('div')
        .attr('class', 'graph-tooltip')
        .style('display', 'none');

    // Edge tooltip handlers (on hit areas)
    linkHitArea.on('mouseenter', function (event, d) {
        tooltip.html(
            '<strong>' + d.shared_tags.join(', ') + '</strong><br>' +
            d.reason
        )
            .style('display', 'block')
            .style('left', (event.offsetX + 12) + 'px')
            .style('top', (event.offsetY - 12) + 'px');
    })
        .on('mousemove', function (event) {
            tooltip
                .style('left', (event.offsetX + 12) + 'px')
                .style('top', (event.offsetY - 12) + 'px');
        })
        .on('mouseleave', function () {
            tooltip.style('display', 'none');
        });

    // Potential link tooltips
    potentialLink.on('mouseenter', function (event, d) {
        tooltip.html(
            '<strong>Potential Connection</strong><br>' +
            'Similarity: ' + Math.round(d.similarity * 100) + '%'
        )
            .style('display', 'block')
            .style('left', (event.offsetX + 12) + 'px')
            .style('top', (event.offsetY - 12) + 'px');
    })
        .on('mousemove', function (event) {
            tooltip
                .style('left', (event.offsetX + 12) + 'px')
                .style('top', (event.offsetY - 12) + 'px');
        })
        .on('mouseleave', function () {
            tooltip.style('display', 'none');
        });

    // ===== Draw nodes (groups) =====
    const node = g.append('g')
        .attr('class', 'graph-nodes')
        .selectAll('g')
        .data(data.nodes)
        .join('g')
        .style('cursor', 'pointer')
        .call(d3.drag()
            .on('start', dragstarted)
            .on('drag', dragged)
            .on('end', dragended));

    // Node outer glow
    node.append('circle')
        .attr('r', 32)
        .attr('fill', d => masteryColors[d.mastery] || '#555')
        .attr('fill-opacity', 0.1)
        .attr('stroke', 'none');

    // Node circle
    node.append('circle')
        .attr('r', 24)
        .attr('fill', d => masteryColors[d.mastery] || '#555')
        .attr('fill-opacity', 0.85)
        .attr('stroke', d => masteryColors[d.mastery] || '#555')
        .attr('stroke-width', 2);

    // Inner white icon circle
    node.append('circle')
        .attr('r', 10)
        .attr('fill', 'none')
        .attr('stroke', 'rgba(255,255,255,0.3)')
        .attr('stroke-width', 1);

    // Node title label
    node.append('text')
        .text(d => d.title.length > 18 ? d.title.substring(0, 18) + '...' : d.title)
        .attr('text-anchor', 'middle')
        .attr('dy', 44)
        .attr('fill', '#e8e8e8')
        .attr('font-size', '11px')
        .attr('font-family', "'Inter', system-ui, sans-serif")
        .style('pointer-events', 'none');

    // Tag labels removed for cleaner graph readability

    // Click -> navigate to chat
    node.on('click', (event, d) => {
        if (event.defaultPrevented) return;
        window.location.href = '/notes/' + d.id + '/chat';
    });

    // Hover effects
    node.on('mouseenter', function (event, d) {
        d3.select(this).select('circle:nth-child(2)')
            .transition().duration(150)
            .attr('r', 28)
            .attr('fill-opacity', 1);
    });
    node.on('mouseleave', function (event, d) {
        d3.select(this).select('circle:nth-child(2)')
            .transition().duration(150)
            .attr('r', 24)
            .attr('fill-opacity', 0.85);
    });

    // ===== Tick =====
    simulation.on('tick', () => {
        // Edges (paths)
        link.attr('d', d => 'M' + d.source.x + ',' + d.source.y + ' L' + d.target.x + ',' + d.target.y);
        linkHitArea.attr('d', d => 'M' + d.source.x + ',' + d.source.y + ' L' + d.target.x + ',' + d.target.y);

        // Potential connection lines
        potentialLink.attr('d', d =>
            'M' + d.sourceNode.x + ',' + d.sourceNode.y + ' L' + d.targetNode.x + ',' + d.targetNode.y
        );

        // Nodes
        node.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');

        // Update cluster hulls
        updateHulls();
    });

    // ===== Search functionality =====
    const searchInput = document.getElementById('graph-search');
    if (searchInput) {
        searchInput.addEventListener('input', function () {
            const query = this.value.trim().toLowerCase();
            node.each(function (d) {
                const matches = !query ||
                    d.title.toLowerCase().includes(query) ||
                    d.tags.some(t => t.toLowerCase().includes(query));
                d3.select(this).style('opacity', matches ? 1 : 0.12);
            });
            link.style('opacity', d => {
                if (!query) return 0.6;
                const srcMatch = d.source.title.toLowerCase().includes(query) ||
                    d.source.tags.some(t => t.toLowerCase().includes(query));
                const tgtMatch = d.target.title.toLowerCase().includes(query) ||
                    d.target.tags.some(t => t.toLowerCase().includes(query));
                return (srcMatch || tgtMatch) ? 0.6 : 0.05;
            });
        });
    }

    // ===== Export functionality =====
    const exportBtn = document.getElementById('graph-export-btn');
    if (exportBtn) {
        exportBtn.addEventListener('click', function () {
            const exportData = {
                nodes: data.nodes.map(n => ({
                    id: n.id,
                    title: n.title,
                    mastery: n.mastery,
                    tags: n.tags,
                    cluster: n.cluster,
                })),
                edges: data.edges.map(e => ({
                    source: typeof e.source === 'object' ? e.source.id : e.source,
                    target: typeof e.target === 'object' ? e.target.id : e.target,
                    shared_tags: e.shared_tags,
                    mastery: e.mastery,
                    reason: e.reason,
                })),
                potential_connections: data.potential_connections || [],
                clusters: data.clusters || {},
                exported_at: new Date().toISOString(),
            };
            const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'knowledge-graph-export.json';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    }

    // ===== Drag functions =====
    function dragstarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }

    function dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }

    function dragended(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }

    // ===== Zoom buttons =====
    const zoomInBtn = document.getElementById('graph-zoom-in');
    const zoomOutBtn = document.getElementById('graph-zoom-out');
    if (zoomInBtn) {
        zoomInBtn.addEventListener('click', () => {
            svg.transition().duration(300).call(zoom.scaleBy, 1.4);
        });
    }
    if (zoomOutBtn) {
        zoomOutBtn.addEventListener('click', () => {
            svg.transition().duration(300).call(zoom.scaleBy, 0.7);
        });
    }

    // ===== Resize handler =====
    window.addEventListener('resize', () => {
        width = container.clientWidth;
        height = container.clientHeight;
        svg.attr('width', width).attr('height', height);
        bg.attr('width', width).attr('height', height);
        simulation.force('center', d3.forceCenter(width / 2, height / 2));
        simulation.alpha(0.1).restart();
    });
});

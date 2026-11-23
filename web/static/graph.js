// The connection map of the detail view: the titles connected to the shown one (see _connectionGraph in server.py) as a layered
// diagram with time running downward -- the main line of sequels, spin-offs, remakes and versions beside and below it.
// ConnectionGraph.render(container, graph, hooks) draws it; hooks = {width, fontFamily, labels, linkFor(node)}.
(function () {
	const SVG_NS = 'http://www.w3.org/2000/svg';
	const PAD = 10, GAP = 14, ROW_GAP = 30, LINE_H = 15, MAXLINES = 3, DUMMY_W = 12;
	const COLLAPSE_MIN = 6; // this many titles that are not in the library and hang off one title the same way become one node
	const SYMMETRIC = ['version_of', 'alternate_language_version_of'];
	const SENTENCES = {
		follows: 'follows',
		spin_off_from: 'is a spin-off of',
		remake_of: 'is a remake of',
		version_of: 'is a version of',
		alternate_language_version_of: 'is an alternate-language version of'
	};
	// the dash of a connection type; "follows" is the solid main line
	const DASH = { follows: '', spin_off_from: '5 4', remake_of: '8 3 2 3', version_of: '2 3', alternate_language_version_of: '2 3' };

	function svgEl(tag, attrs) {
		const el = document.createElementNS(SVG_NS, tag);
		if (attrs) Object.keys(attrs).forEach(k => el.setAttribute(k, attrs[k]));
		return el;
	}

	// ------------------------------------------------------------------------------------------------------ layout

	function layout(graph, width, fontFamily) {
		const W = width, boxW = Math.max(96, Math.min(132, Math.floor((W - 2 * PAD - 2 * GAP) / 3)));
		const ctx = document.createElement('canvas').getContext('2d');
		ctx.font = '12px ' + fontFamily;
		const textWidth = s => ctx.measureText(s).width;

		const nodes = new Map(graph.nodes.map(n => [n.id, { ...n, sortYear: n.year || 0 }]));
		let edges = graph.edges.map(e => ({ ...e }));

		// 1. titles that are not in the library and hang off the same title the same way become one node
		const degree = new Map();
		edges.forEach(e => { degree.set(e.a, (degree.get(e.a) || 0) + 1); degree.set(e.b, (degree.get(e.b) || 0) + 1); });
		const leaves = new Map();
		edges.forEach(e => {
			[[e.a, e.b, 'a'], [e.b, e.a, 'b']].forEach(([leaf, other, side]) => {
				const n = nodes.get(leaf);
				if (n.owned || leaf === graph.start || degree.get(leaf) !== 1) return;
				const key = other + '|' + e.type + '|' + (SYMMETRIC.includes(e.type) ? '*' : side);
				if (!leaves.has(key)) leaves.set(key, []);
				leaves.get(key).push({ leaf, edge: e, other });
			});
		});
		leaves.forEach((members, key) => {
			if (members.length < COLLAPSE_MIN) return;
			const years = members.map(m => nodes.get(m.leaf).year).filter(Boolean);
			const lo = Math.min(...years), hi = Math.max(...years);
			const id = 'cluster:' + key, side = key.split('|')[2], e0 = members[0].edge;
			nodes.set(id, {
				id, kind: 'cluster', title: members.length + ' titles', year: years.length ? lo : null, sortYear: years.length ? lo : 0,
				yearText: !years.length ? '' : lo === hi ? String(lo) : lo + '–' + hi, owned: false,
				members: members.map(m => nodes.get(m.leaf))
			});
			const gone = new Set(members.map(m => m.edge));
			edges = edges.filter(e => !gone.has(e));
			edges.push(side === '*' ? { a: id, b: members[0].other, type: e0.type } : side === 'a' ? { a: id, b: e0.b, type: e0.type } : { a: e0.a, b: id, type: e0.type });
			members.forEach(m => nodes.delete(m.leaf));
		});
		const realEdges = edges.filter(e => !e.assumed); // what the data says, for the highlighting and the texts

		// 2. "follows" is drawn as the direct sequence: a connection another chain of connections already implies is left out
		const succ = new Map();
		edges.filter(e => e.type === 'follows').forEach(e => { if (!succ.has(e.a)) succ.set(e.a, []); succ.get(e.a).push(e.b); });
		const reaches = (from, target) => {
			const seen = new Set(), stack = (succ.get(from) || []).filter(x => x !== target);
			while (stack.length) {
				const x = stack.pop();
				if (x === target) return true;
				if (seen.has(x)) continue;
				seen.add(x);
				(succ.get(x) || []).forEach(y => stack.push(y));
			}
			return false;
		};
		const hidden = edges.filter(e => e.type === 'follows' && reaches(e.a, e.b));
		const hiddenSet = new Set(hidden);
		edges = edges.filter(e => !hiddenSet.has(e));

		// 3. rows: the longest chain of "earlier -> later" connections above a title; a row that would be wider than the
		// drawing lets its latest titles move down to the next row
		const directed = edges.map(e => {
			if (!SYMMETRIC.includes(e.type)) return { from: e.b, to: e.a, e };
			const a = nodes.get(e.a), b = nodes.get(e.b);
			return (a.sortYear < b.sortYear || (a.sortYear === b.sortYear && String(e.a) < String(e.b))) ? { from: e.a, to: e.b, e } : { from: e.b, to: e.a, e };
		});
		const rank = new Map([...nodes.keys()].map(id => [id, 0]));
		const relax = () => {
			for (let i = 0; i < nodes.size + 2; i++) {
				let changed = false;
				directed.forEach(d => { if (rank.get(d.to) < rank.get(d.from) + 1) { rank.set(d.to, rank.get(d.from) + 1); changed = true; } });
				if (!changed) break;
			}
		};
		relax();
		for (let guard = 0; guard < 500; guard++) {
			const maxRank = Math.max(...rank.values());
			const real = Array.from({ length: maxRank + 2 }, () => []), dummies = new Array(maxRank + 2).fill(0);
			rank.forEach((r, id) => real[r].push(id));
			directed.forEach(d => { for (let r = rank.get(d.from) + 1; r < rank.get(d.to); r++) dummies[r]++; });
			const need = (r, nReal) => nReal * boxW + dummies[r] * DUMMY_W + Math.max(0, nReal + dummies[r] - 1) * GAP;
			const over = real.findIndex((ids, r) => ids.length > 1 && need(r, ids.length) > W - 2 * PAD);
			if (over < 0) break;
			const latest = real[over].filter(id => id !== graph.start)
				.sort((x, y) => (nodes.get(y).sortYear - nodes.get(x).sortYear) || String(y).localeCompare(String(x)))[0];
			rank.set(latest, over + 1);
			relax();
		}

		// 4. long connections get an invisible stop in every row they cross, so the rows can make room for them
		const items = new Map();
		nodes.forEach((n, id) => items.set(id, { id, node: n, row: rank.get(id) }));
		const links = [];
		directed.forEach(d => {
			const chain = [d.from];
			for (let r = rank.get(d.from) + 1; r < rank.get(d.to); r++) {
				const id = 'dummy:' + links.length + ':' + r;
				items.set(id, { id, node: null, row: r });
				chain.push(id);
			}
			chain.push(d.to);
			links.push({ type: d.e.type, chain, edge: d.e });
		});

		// 5. box sizes from the wrapped text
		const rowCount = Math.max(...[...items.values()].map(i => i.row)) + 1;
		const rows = Array.from({ length: rowCount }, () => []);
		items.forEach(i => rows[i.row].push(i));
		const wrap = n => {
			const words = (n.title + (n.yearText ? ' · ' + n.yearText : '')).split(' ');
			const lines = [''];
			words.forEach(w => {
				const cur = lines[lines.length - 1], trial = cur ? cur + ' ' + w : w;
				if (textWidth(trial) <= boxW - 14 || !cur) lines[lines.length - 1] = trial;
				else lines.push(w);
			});
			if (lines.length > MAXLINES) { lines.length = MAXLINES; lines[MAXLINES - 1] = lines[MAXLINES - 1].replace(/.{0,3}$/, '') + '…'; }
			return lines;
		};
		items.forEach(i => {
			if (i.node) { i.lines = wrap(i.node); i.w = boxW; i.h = i.lines.length * LINE_H + 12; } else { i.w = DUMMY_W; i.h = 0; }
		});

		// 6. order within the rows: repeated sweeps that put each item at the average position of its neighbours
		const up = new Map(), down = new Map();
		links.forEach(l => {
			for (let k = 0; k + 1 < l.chain.length; k++) {
				const a = l.chain[k], b = l.chain[k + 1];
				if (!down.has(a)) down.set(a, []);
				down.get(a).push(b);
				if (!up.has(b)) up.set(b, []);
				up.get(b).push(a);
			}
		});
		rows.forEach(r => r.sort((a, b) => ((a.node ? a.node.sortYear : 1e9) - (b.node ? b.node.sortYear : 1e9)) || String(a.id).localeCompare(String(b.id))));
		const posOf = () => { const m = new Map(); rows.forEach(r => r.forEach((it, idx) => m.set(it.id, r.length > 1 ? idx / (r.length - 1) : 0.5))); return m; };
		for (let sweep = 0; sweep < 14; sweep++) {
			const goingDown = sweep % 2 === 0;
			const order = goingDown ? rows.map((_, i) => i) : rows.map((_, i) => rows.length - 1 - i);
			order.forEach(r => {
				const pos = posOf(), nb = goingDown ? up : down;
				const key = it => { const ns = nb.get(it.id); return ns && ns.length ? ns.reduce((s, n) => s + pos.get(n), 0) / ns.length : pos.get(it.id); };
				const keys = new Map(rows[r].map(it => [it.id, key(it)]));
				rows[r].sort((a, b) => keys.get(a.id) - keys.get(b.id));
			});
		}

		// 7. horizontal positions: centred rows first, then pulled towards the neighbours without leaving their order
		rows.forEach(r => {
			const total = r.reduce((s, it) => s + it.w, 0) + (r.length - 1) * GAP;
			let x = (W - total) / 2;
			r.forEach(it => { it.x = x; x += it.w + GAP; });
		});
		const centre = it => it.x + it.w / 2;
		for (let pass = 0; pass < 24; pass++) {
			const goingDown = pass % 2 === 0;
			const order = goingDown ? rows.map((_, i) => i) : rows.map((_, i) => rows.length - 1 - i);
			order.forEach(r => {
				const row = rows[r], nb = goingDown ? up : down;
				row.forEach(it => {
					const ns = nb.get(it.id);
					it.x = ns && ns.length ? ns.reduce((s, n) => s + centre(items.get(n)), 0) / ns.length - it.w / 2 : it.x;
				});
				for (let i = 0; i < row.length; i++) {
					row[i].x = Math.max(PAD, row[i].x);
					if (i) row[i].x = Math.max(row[i].x, row[i - 1].x + row[i - 1].w + GAP);
				}
				const last = row.length - 1;
				row[last].x = Math.min(row[last].x, W - PAD - row[last].w);
				for (let i = last - 1; i >= 0; i--) row[i].x = Math.min(row[i].x, row[i + 1].x - GAP - row[i].w);
				row.forEach(it => { it.x = Math.max(PAD, it.x); });
			});
		}

		// 8. vertical positions
		let y = PAD;
		rows.forEach(r => {
			const h = Math.max(0, ...r.map(it => it.h));
			r.forEach(it => { it.y = y; });
			y += h + ROW_GAP;
		});
		return { items, links, hidden, realEdges, nodes, width: W, height: y - ROW_GAP + PAD, start: graph.start };
	}

	// --------------------------------------------------------------------------------------------------------- drawing

	function curve(points) {
		let d = 'M' + points[0].x.toFixed(1) + ' ' + points[0].yBottom.toFixed(1);
		for (let k = 1; k < points.length; k++) {
			const p = points[k - 1], q = points[k], y1 = p.yBottom, y2 = q.yTop - (k === points.length - 1 ? 2 : 0), mid = (y1 + y2) / 2;
			d += ' C' + p.x.toFixed(1) + ' ' + mid.toFixed(1) + ' ' + q.x.toFixed(1) + ' ' + mid.toFixed(1) + ' ' + q.x.toFixed(1) + ' ' + y2.toFixed(1);
			if (k < points.length - 1) d += ' L' + q.x.toFixed(1) + ' ' + q.yBottom.toFixed(1);
		}
		return d;
	}

	function label(n) {
		return n.title + (n.yearText ? ' (' + n.yearText + ')' : '');
	}

	function render(container, graph, hooks) {
		container.replaceChildren();
		const L = layout(graph, hooks.width, hooks.fontFamily);
		const svg = svgEl('svg', { viewBox: '0 0 ' + L.width + ' ' + Math.ceil(L.height), role: 'group', 'aria-label': 'Connection map' });
		const defs = svgEl('defs');
		const marker = svgEl('marker', { id: 'graphArrow', viewBox: '0 0 10 10', refX: '8', refY: '5', markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse' });
		marker.appendChild(svgEl('path', { d: 'M2 1L8 5L2 9', fill: 'none', stroke: 'context-stroke', 'stroke-width': '1.5', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
		defs.appendChild(marker);
		svg.appendChild(defs);

		const edgeLayer = svgEl('g'), overlay = svgEl('g'), nodeLayer = svgEl('g');
		svg.append(edgeLayer, overlay, nodeLayer);
		const edgeEls = [], nodeEls = new Map();
		const pointOf = id => { const it = L.items.get(id); const cx = it.x + it.w / 2; return it.node ? { x: cx, yTop: it.y, yBottom: it.y + it.h } : { x: cx, yTop: it.y, yBottom: it.y }; };

		L.links.forEach(l => {
			const path = svgEl('path', { d: curve(l.chain.map(pointOf)), class: 'graphEdge graphEdge--' + l.type });
			if (l.type !== 'version_of' && l.type !== 'alternate_language_version_of') path.setAttribute('marker-end', 'url(#graphArrow)');
			if (DASH[l.type]) path.setAttribute('stroke-dasharray', DASH[l.type]);
			edgeLayer.appendChild(path);
			edgeEls.push({ el: path, edge: l.edge });
		});

		// what a title is connected to, in words, for the hover text
		const relationLines = id => {
			const byLabel = new Map();
			L.realEdges.forEach(e => {
				if (e.a !== id && e.b !== id) return;
				const other = L.nodes.get(e.a === id ? e.b : e.a), mine = e.a === id;
				const key = { follows: mine ? 'follows' : 'followed_by', spin_off_from: mine ? 'spin_off_from' : 'spin_off', remake_of: mine ? 'remake_of' : 'remade_as',
					version_of: 'version_of', alternate_language_version_of: 'alternate_language_version_of' }[e.type];
				const text = label(other) + (e.via ? ' (' + e.via + ')' : '');
				if (!byLabel.has(key)) byLabel.set(key, []);
				byLabel.get(key).push(text);
			});
			return [...byLabel].map(([key, texts]) => (hooks.labels[key] || key) + ': ' + texts.join(', '));
		};

		const clusterBox = document.createElement('div');
		clusterBox.className = 'graphClusterList';
		clusterBox.hidden = true;
		let openCluster = null;
		function toggleCluster(node, el) {
			const wasOpen = openCluster === el;
			if (openCluster) { openCluster.setAttribute('aria-expanded', 'false'); openCluster.classList.remove('graphOpen'); openCluster = null; }
			clusterBox.hidden = true;
			if (wasOpen) return;
			clusterBox.replaceChildren();
			const heading = document.createElement('div');
			heading.className = 'graphClusterHeading';
			heading.textContent = node.title + (node.yearText ? ' · ' + node.yearText : '');
			clusterBox.appendChild(heading);
			const list = document.createElement('div');
			list.className = 'graphClusterItems';
			node.members.slice().sort((a, b) => (a.year || 0) - (b.year || 0) || a.title.localeCompare(b.title)).forEach(m => {
				const link = document.createElement('a');
				link.textContent = label(m);
				const target = hooks.linkFor(m);
				link.href = target.href;
				link.title = target.title;
				if (target.external) { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
				else link.addEventListener('click', e => { if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return; e.preventDefault(); target.open(); });
				list.appendChild(link);
			});
			clusterBox.appendChild(list);
			clusterBox.hidden = false;
			el.setAttribute('aria-expanded', 'true');
			el.classList.add('graphOpen');
			openCluster = el;
		}

		function highlight(id) {
			const lit = new Set([id]);
			L.realEdges.forEach(e => { if (e.a === id) lit.add(e.b); else if (e.b === id) lit.add(e.a); });
			svg.classList.add('graphFocus');
			nodeEls.forEach((el, nid) => el.classList.toggle('graphLit', lit.has(nid)));
			edgeEls.forEach(({ el, edge }) => el.classList.toggle('graphLit', !edge.assumed && (edge.a === id || edge.b === id)));
			// the direct connections the drawing leaves out because a chain implies them
			L.hidden.filter(e => !e.assumed && (e.a === id || e.b === id)).forEach(e => {
				const from = pointOf(e.b), to = pointOf(e.a);
				overlay.appendChild(svgEl('path', { d: curve([from, to]), class: 'graphHidden', 'marker-end': 'url(#graphArrow)' }));
			});
		}
		function unhighlight() {
			svg.classList.remove('graphFocus');
			nodeEls.forEach(el => el.classList.remove('graphLit'));
			edgeEls.forEach(({ el }) => el.classList.remove('graphLit'));
			overlay.replaceChildren();
		}

		L.items.forEach(it => {
			if (!it.node) return;
			const n = it.node, current = n.id === L.start, cluster = n.kind === 'cluster';
			const target = current || cluster ? null : hooks.linkFor(n);
			const el = svgEl(target ? 'a' : 'g', { class: 'graphNode' + (n.owned ? ' graphNode--owned' : '') + (current ? ' graphNode--current' : '') + (cluster ? ' graphNode--cluster' : '') });
			if (target) {
				el.setAttribute('href', target.href);
				if (target.external) { el.setAttribute('target', '_blank'); el.setAttribute('rel', 'noopener noreferrer'); }
				else el.addEventListener('click', e => { if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return; e.preventDefault(); target.open(); });
			}
			if (cluster) {
				el.setAttribute('role', 'button');
				el.setAttribute('tabindex', '0');
				el.setAttribute('aria-expanded', 'false');
				el.addEventListener('click', () => toggleCluster(n, el));
				el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleCluster(n, el); } });
			}
			el.appendChild(svgEl('rect', { x: it.x.toFixed(1), y: it.y.toFixed(1), width: it.w, height: it.h, rx: 6 }));
			it.lines.forEach((line, k) => {
				const text = svgEl('text', { x: (it.x + it.w / 2).toFixed(1), y: (it.y + 13.5 + k * LINE_H).toFixed(1), 'text-anchor': 'middle', 'dominant-baseline': 'central' });
				text.textContent = line;
				el.appendChild(text);
			});
			const tip = svgEl('title');
			tip.textContent = [label(n) + (cluster ? ' – click for the list' : target ? (target.external ? ' – not in the library' : '') : ' – this title')].concat(relationLines(n.id)).join('\n');
			el.appendChild(tip);
			el.addEventListener('mouseenter', () => highlight(n.id));
			el.addEventListener('mouseleave', unhighlight);
			el.addEventListener('focus', () => highlight(n.id));
			el.addEventListener('blur', unhighlight);
			nodeLayer.appendChild(el);
			nodeEls.set(n.id, el);
		});

		container.appendChild(svg);
		container.appendChild(clusterBox);

		// legend: what the node styles and the lines of this map mean
		const legend = document.createElement('div');
		legend.className = 'graphLegend';
		const swatch = (cls, text) => {
			const item = document.createElement('span');
			const s = svgEl('svg', { width: 22, height: 14, viewBox: '0 0 22 14', 'aria-hidden': 'true' });
			const wrapG = svgEl('g', { class: 'graphNode ' + cls });
			wrapG.appendChild(svgEl('rect', { x: 0.5, y: 0.5, width: 21, height: 13, rx: 3 }));
			s.appendChild(wrapG);
			item.append(s, document.createTextNode(text));
			return item;
		};
		const line = (type, text) => {
			const item = document.createElement('span');
			const s = svgEl('svg', { width: 30, height: 14, viewBox: '0 0 30 14', 'aria-hidden': 'true' });
			const path = svgEl('path', { d: 'M1 7 H27', class: 'graphEdge graphEdge--' + type });
			if (type !== 'version_of') path.setAttribute('marker-end', 'url(#graphArrow)');
			if (DASH[type]) path.setAttribute('stroke-dasharray', DASH[type]);
			s.appendChild(path);
			item.append(s, document.createTextNode(text));
			return item;
		};
		legend.append(swatch('graphNode--owned', 'In the library'), swatch('', 'Not in the library'), swatch('graphNode--owned graphNode--current', 'This title'));
		const present = new Set(L.links.map(l => l.type === 'alternate_language_version_of' ? 'version_of' : l.type));
		[['follows', 'Followed by'], ['spin_off_from', 'Spin-off'], ['remake_of', 'Remake'], ['version_of', 'Version of']].forEach(([type, text]) => { if (present.has(type)) legend.appendChild(line(type, text)); });
		container.appendChild(legend);

		// the same connections as plain sentences, for screen readers
		const sentences = document.createElement('ul');
		sentences.className = 'srOnly';
		L.realEdges.forEach(e => {
			const item = document.createElement('li');
			item.textContent = label(L.nodes.get(e.a)) + ' ' + SENTENCES[e.type] + ' ' + label(L.nodes.get(e.b)) + (e.via ? ' (' + e.via + ')' : '');
			sentences.appendChild(item);
		});
		container.appendChild(sentences);
	}

	window.ConnectionGraph = { render };
})();

// The connection map of the detail view: the titles connected to the shown one (see _connectionGraph in server.py) as a
// timeline -- every release year one step of it, the main line of sequels with spin-offs, remakes and versions beside it --
// that runs from left to right when its steps fit the width and downward otherwise, with the years on an axis.
// ConnectionGraph.render(container, graph, hooks) draws it; hooks = {width, fontFamily, labels, linkFor(node)}.
(function () {
	const SVG_NS = 'http://www.w3.org/2000/svg';
	const PAD = 10, GAP = 14, LINE_H = 15, MAXLINES = 3, DUMMY_W = 12;
	const ROW_GAP = 30, COLUMN_GAP = 28; // between two steps of the timeline: running downward / to the right
	const BOX_MIN = 90; // the narrowest a box gets in a horizontal map; a map whose steps need narrower ones runs downward
	const AXIS_V = 52, AXIS_H = 26; // room for the years: left of a downward map / below a horizontal one
	const MIDDLE_PULL = 0.15; // the weight of that pull, against 1 for a connection that is not a "follows"
	const BOX_PRIORITY = 8; // how much more a box resists being moved aside than the stop of a long connection
	const MAIN_LINE_PULL = 4; // the weight of a "follows" connection
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

	// Terms: a "step" is one position along the timeline (a row of a downward map, a column of a horizontal one); a "lane" is
	// the position across it. An item is a box or the invisible stop of a long connection in a step it crosses.
	// horizontal: the steps run left to right; the result is null when they do not fit the width.
	function layout(graph, W, fontFamily, horizontal) {
		const ctx = document.createElement('canvas').getContext('2d');
		ctx.font = '12px ' + fontFamily;
		const textWidth = s => ctx.measureText(s).width;
		const axisV = horizontal ? 0 : AXIS_V;
		let boxW = Math.max(96, Math.min(132, Math.floor((W - axisV - 2 * PAD - 2 * GAP) / 3)));

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

		// 3. steps: every release year is one step, in order. Titles of one year that are connected follow each other in extra
		// steps (the year is written once, over all of them); a connection that runs against the years -- rare -- pushes its
		// later title down until it follows.
		const directed = edges.map(e => {
			if (!SYMMETRIC.includes(e.type)) return { from: e.b, to: e.a, e };
			const a = nodes.get(e.a), b = nodes.get(e.b);
			return (a.sortYear < b.sortYear || (a.sortYear === b.sortYear && String(e.a) < String(e.b))) ? { from: e.a, to: e.b, e } : { from: e.b, to: e.a, e };
		});
		const rank = new Map();
		let step = 0;
		[...new Set([...nodes.values()].map(n => n.sortYear))].sort((a, b) => a - b).forEach(year => {
			const ids = [...nodes.keys()].filter(id => nodes.get(id).sortYear === year), sub = new Map(ids.map(id => [id, 0]));
			for (let i = 0; i <= ids.length; i++) {
				let changed = false;
				directed.forEach(d => { if (sub.has(d.from) && sub.has(d.to) && sub.get(d.to) < sub.get(d.from) + 1) { sub.set(d.to, sub.get(d.from) + 1); changed = true; } });
				if (!changed) break;
			}
			ids.forEach(id => rank.set(id, step + sub.get(id)));
			step += Math.max(...sub.values()) + 1;
		});
		for (let i = 0; i < nodes.size + 2; i++) {
			let changed = false;
			directed.forEach(d => { if (rank.get(d.to) <= rank.get(d.from)) { rank.set(d.to, rank.get(d.from) + 1); changed = true; } });
			if (!changed) break;
		}
		const used = [...new Set(rank.values())].sort((a, b) => a - b);
		rank.forEach((r, id) => rank.set(id, used.indexOf(r)));
		if (!horizontal) {
			// a step that is wider than the drawing is split in two, one half below the other (the year stays over both)
			for (let guard = 0; guard < 200; guard++) {
				const last = Math.max(...rank.values());
				const real = Array.from({ length: last + 1 }, () => []), dummies = new Array(last + 1).fill(0);
				rank.forEach((r, id) => real[r].push(id));
				directed.forEach(d => { for (let r = rank.get(d.from) + 1; r < rank.get(d.to); r++) dummies[r]++; });
				const need = (r, count) => count * boxW + dummies[r] * DUMMY_W + Math.max(0, count + dummies[r] - 1) * GAP;
				const over = real.findIndex((ids, r) => ids.length > 1 && need(r, ids.length) > W - axisV - 2 * PAD);
				if (over < 0) break;
				const ids = real[over].slice().sort((x, y) => String(x).localeCompare(String(y)));
				rank.forEach((r, id) => { if (r > over) rank.set(id, r + 1); });
				ids.slice(Math.ceil(ids.length / 2)).forEach(id => rank.set(id, over + 1));
			}
		}
		const stepCount = Math.max(...rank.values()) + 1;
		if (horizontal) {
			boxW = Math.min(132, Math.floor((W - 2 * PAD - (stepCount - 1) * COLUMN_GAP) / stepCount));
			if (boxW < BOX_MIN) return null;
		}

		// 4. long connections get an invisible stop in every step they cross, so the steps can make room for them
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

		// 5. box sizes from the wrapped text; "lane" is the extent across the steps, "lev" the extent along them. The year is
		// on the axis, so a box names it only when it covers several (folded titles, a group of episodes)
		const rows = Array.from({ length: stepCount }, () => []);
		items.forEach(i => rows[i.row].push(i));
		const wrap = n => {
			const words = (n.title + (/–/.test(n.yearText || '') ? ' · ' + n.yearText : '')).split(' ');
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
			if (i.node) {
				i.lines = wrap(i.node);
				i.w = boxW; i.h = i.lines.length * LINE_H + 12;
				i.lane = horizontal ? i.h : i.w; i.lev = horizontal ? i.w : i.h;
			} else { i.lane = DUMMY_W; i.lev = 0; i.w = DUMMY_W; i.h = 0; }
		});

		// 6. order within the steps: sweeps that put each item at the average position of its neighbours, with swaps of
		// neighbours wherever that saves a crossing; the order with the fewest crossings wins
		const up = new Map(), down = new Map(), pull = new Map(); // pull: how strongly two items joined by a connection want to be in line
		links.forEach(l => {
			for (let k = 0; k + 1 < l.chain.length; k++) {
				const a = l.chain[k], b = l.chain[k + 1];
				if (!down.has(a)) down.set(a, []);
				down.get(a).push(b);
				if (!up.has(b)) up.set(b, []);
				up.get(b).push(a);
				// the main line of sequels runs straightest; a stop of a long connection counts double, so long ones run straight too
				const w = (l.type === 'follows' ? MAIN_LINE_PULL : 1) * (items.get(a).node ? 1 : 2) * (items.get(b).node ? 1 : 2);
				pull.set(a + '|' + b, (pull.get(a + '|' + b) || 0) + w);
				pull.set(b + '|' + a, (pull.get(b + '|' + a) || 0) + w);
			}
		});
		rows.forEach(r => r.sort((a, b) => ((a.node ? a.node.sortYear : 1e9) - (b.node ? b.node.sortYear : 1e9)) || String(a.id).localeCompare(String(b.id))));
		const crossingsBelow = r => { // crossings between step r and the one after it
			if (r < 0 || r + 1 >= rows.length) return 0;
			const lower = new Map(rows[r + 1].map((it, i) => [it.id, i])), segs = [];
			rows[r].forEach((it, i) => (down.get(it.id) || []).forEach(n => { if (lower.has(n)) segs.push([i, lower.get(n)]); }));
			let count = 0;
			for (let i = 0; i < segs.length; i++) for (let j = i + 1; j < segs.length; j++) if ((segs[i][0] - segs[j][0]) * (segs[i][1] - segs[j][1]) < 0) count++;
			return count;
		};
		const totalCrossings = () => rows.reduce((s, _, r) => s + crossingsBelow(r), 0);
		const transpose = () => {
			for (let round = 0; round < 8; round++) {
				let improved = false;
				rows.forEach((row, r) => {
					for (let i = 0; i + 1 < row.length; i++) {
						const before = crossingsBelow(r - 1) + crossingsBelow(r);
						[row[i], row[i + 1]] = [row[i + 1], row[i]];
						if (crossingsBelow(r - 1) + crossingsBelow(r) < before) improved = true;
						else [row[i], row[i + 1]] = [row[i + 1], row[i]];
					}
				});
				if (!improved) break;
			}
		};
		const posOf = () => { const m = new Map(); rows.forEach(r => r.forEach((it, idx) => m.set(it.id, r.length > 1 ? idx / (r.length - 1) : 0.5))); return m; };
		let best = rows.map(r => r.slice()), bestCount = totalCrossings();
		for (let sweep = 0; sweep < 24 && bestCount > 0; sweep++) {
			const goingDown = sweep % 2 === 0;
			const order = goingDown ? rows.map((_, i) => i) : rows.map((_, i) => rows.length - 1 - i);
			order.forEach(r => {
				const pos = posOf(), nb = goingDown ? up : down;
				const key = it => { const ns = nb.get(it.id); return ns && ns.length ? ns.reduce((s, n) => s + pos.get(n), 0) / ns.length : pos.get(it.id); };
				const keys = new Map(rows[r].map(it => [it.id, key(it)]));
				rows[r].sort((a, b) => keys.get(a.id) - keys.get(b.id));
			});
			transpose();
			const count = totalCrossings();
			if (count < bestCount) { bestCount = count; best = rows.map(r => r.slice()); }
		}
		best.forEach((r, i) => { rows[i] = r; });

		// 7. position across the steps: every item is pulled towards its neighbours on both sides (a connection through a
		// stop counts more, so long ones run straight), and each step is then set as close to those wishes as its order and
		// the room the boxes need allow -- chains come out straight and a fan sits centred over what it hangs off
		const laneW = W - axisV, minC = horizontal ? -Infinity : PAD, maxC = horizontal ? Infinity : laneW - PAD;
		rows.forEach(r => {
			const total = r.reduce((s, it) => s + it.lane, 0) + (r.length - 1) * GAP;
			let c = (horizontal ? 0 : laneW / 2) - total / 2;
			r.forEach(it => { it.c = c; c += it.lane + GAP; });
		});
		const centre = it => it.c + it.lane / 2, middle = horizontal ? 0 : laneW / 2;
		for (let pass = 0; pass < 120; pass++) {
			const order = pass % 2 === 0 ? rows.map((_, i) => i) : rows.map((_, i) => rows.length - 1 - i);
			order.forEach(r => {
				const row = rows[r], offset = [];
				let acc = 0;
				row.forEach(it => { offset.push(acc); acc += it.lane + GAP; });
				// wishes, shifted by the room taken by the items before them: they must come out in the same order
				const wish = row.map((it, i) => {
					const ns = [...new Set((up.get(it.id) || []).concat(down.get(it.id) || []))];
					if (!ns.length) return { q: it.c - offset[i], w: 0.01 };
					// a faint pull towards the middle: without it a chain may run along any slanted line
					let sw = MIDDLE_PULL, sc = MIDDLE_PULL * middle;
					ns.forEach(n => { const k = pull.get(it.id + '|' + n); sw += k; sc += k * centre(items.get(n)); });
					return { q: sc / sw - it.lane / 2 - offset[i], w: it.node ? sw * BOX_PRIORITY : sw }; // when they get in each other's way, boxes give way less than stops
				});
				// the closest non-decreasing fit (pool adjacent violators)
				const blocks = [];
				wish.forEach((x, i) => {
					blocks.push({ sw: x.w, sq: x.w * x.q, n: 1 });
					while (blocks.length > 1 && blocks[blocks.length - 2].sq / blocks[blocks.length - 2].sw > blocks[blocks.length - 1].sq / blocks[blocks.length - 1].sw) {
						const b = blocks.pop(), a = blocks.pop();
						blocks.push({ sw: a.sw + b.sw, sq: a.sq + b.sq, n: a.n + b.n });
					}
				});
				let i = 0;
				blocks.forEach(b => { for (let k = 0; k < b.n; k++, i++) row[i].c = b.sq / b.sw + offset[i]; });
				const shift = Math.max(0, minC - row[0].c);
				row.forEach(it => { it.c += shift; });
				const over = row[row.length - 1].c + row[row.length - 1].lane - maxC;
				if (over > 0) row.forEach(it => { it.c = Math.max(minC, it.c - over); });
			});
		}
		let laneExtent = laneW;
		{
			const all = [...items.values()];
			const lo = Math.min(...all.map(i => i.c)), hi = Math.max(...all.map(i => i.c + i.lane));
			const shift = horizontal ? PAD - lo : Math.max(minC - lo, Math.min(maxC - hi, (minC + maxC) / 2 - (lo + hi) / 2));
			all.forEach(i => { i.c += shift; });
			if (horizontal) laneExtent = hi - lo + 2 * PAD;
		}

		// 8. position along the steps
		const gap = horizontal ? COLUMN_GAP : ROW_GAP;
		let p = PAD;
		const levPos = [], levSize = [];
		rows.forEach((r, k) => {
			levPos[k] = p; levSize[k] = Math.max(0, ...r.map(it => it.lev));
			r.forEach(it => { it.l = p; });
			p += levSize[k] + gap;
		});
		const levEnd = p - gap + PAD;

		// 9. the axis: the year of every step; steps of one year share one label with a bracket over all of them
		const yearsOf = r => new Set(rows[r].filter(it => it.node && it.node.sortYear).map(it => it.node.sortYear));
		const axis = [];
		for (let k = 0; k < stepCount; k++) {
			const ys = yearsOf(k);
			if (!ys.size) continue;
			if (ys.size === 1) {
				const [y] = ys;
				let last = k;
				while (last + 1 < stepCount && yearsOf(last + 1).size === 1 && yearsOf(last + 1).has(y)) last++;
				axis.push({ text: String(y), from: levPos[k], to: levPos[last] + levSize[last], multi: last > k });
				k = last;
			} else {
				axis.push({ text: Math.min(...ys) + '–' + Math.max(...ys), from: levPos[k], to: levPos[k] + levSize[k], multi: false });
			}
		}
		const width = horizontal ? levEnd : W, height = horizontal ? laneExtent + (axis.length ? AXIS_H : 0) : levEnd;
		return { items, links, hidden, realEdges, nodes, width, height, start: graph.start, horizontal, axisV, axis, levSize, laneExtent };
	}

	// the map runs left to right when its steps fit the width and that is not taller than downward, otherwise downward
	function bestLayout(graph, W, fontFamily) {
		const downward = layout(graph, W, fontFamily, false), across = layout(graph, W, fontFamily, true);
		return across && across.height <= downward.height ? across : downward;
	}

	// --------------------------------------------------------------------------------------------------------- drawing

	function label(n) {
		return n.title + (n.yearText ? ' (' + n.yearText + ')' : '');
	}

	function render(container, graph, hooks) {
		container.replaceChildren();
		const L = bestLayout(graph, hooks.width, hooks.fontFamily);
		const svg = svgEl('svg', { viewBox: '0 0 ' + Math.ceil(L.width) + ' ' + Math.ceil(L.height), role: 'group', 'aria-label': 'Connection map' });
		svg.style.width = Math.ceil(L.width) + 'px';
		svg.style.maxWidth = '100%';
		const defs = svgEl('defs');
		const marker = svgEl('marker', { id: 'graphArrow', viewBox: '0 0 10 10', refX: '8', refY: '5', markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse' });
		marker.appendChild(svgEl('path', { d: 'M2 1L8 5L2 9', fill: 'none', stroke: 'context-stroke', 'stroke-width': '1.5', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
		defs.appendChild(marker);
		svg.appendChild(defs);

		// (lane position, position along the steps) -> x, y
		const XY = (c, l) => L.horizontal ? [l, c] : [c + L.axisV, l];
		const f = n => n.toFixed(1);

		// the years
		if (L.axis.length) {
			const g = svgEl('g', { class: 'graphAxis' });
			const first = L.axis[0].from, last = L.axis[L.axis.length - 1].to;
			if (L.horizontal) {
				const y = L.laneExtent + 4;
				g.appendChild(svgEl('path', { d: 'M' + f(first) + ' ' + y + ' H' + f(last), class: 'graphAxisLine' }));
				L.axis.forEach(a => {
					g.appendChild(svgEl('path', { d: a.multi ? 'M' + f(a.from) + ' ' + (y + 4) + ' V' + y + ' H' + f(a.to) + ' V' + (y + 4) : 'M' + f((a.from + a.to) / 2) + ' ' + y + ' v4', class: 'graphAxisLine' }));
					const text = svgEl('text', { x: f((a.from + a.to) / 2), y: y + 17, 'text-anchor': 'middle' });
					text.textContent = a.text;
					g.appendChild(text);
				});
			} else {
				const x = L.axisV - 8;
				g.appendChild(svgEl('path', { d: 'M' + x + ' ' + f(first) + ' V' + f(last), class: 'graphAxisLine' }));
				L.axis.forEach(a => {
					g.appendChild(svgEl('path', { d: a.multi ? 'M' + (x - 4) + ' ' + f(a.from) + ' H' + x + ' V' + f(a.to) + ' H' + (x - 4) : 'M' + x + ' ' + f((a.from + a.to) / 2) + ' h-4', class: 'graphAxisLine' }));
					const text = svgEl('text', { x: x - 8, y: f((a.from + a.to) / 2), 'text-anchor': 'end', 'dominant-baseline': 'central' });
					text.textContent = a.text;
					g.appendChild(text);
				});
			}
			svg.appendChild(g);
		}

		const edgeLayer = svgEl('g'), overlay = svgEl('g'), nodeLayer = svgEl('g');
		svg.append(edgeLayer, overlay, nodeLayer);
		const edgeEls = [], nodeEls = new Map();
		// where a connection leaves / enters an item: its lane position and the extent along the steps (a stop is passed straight through)
		const pointOf = id => { const it = L.items.get(id); return { c: it.c + it.lane / 2, s: it.l, e: it.node ? it.l + it.lev : it.l + L.levSize[it.row] }; };
		const curve = points => {
			const start = XY(points[0].c, points[0].e);
			let d = 'M' + f(start[0]) + ' ' + f(start[1]);
			for (let k = 1; k < points.length; k++) {
				const p = points[k - 1], q = points[k], s1 = p.e, s2 = q.s - (k === points.length - 1 ? 2 : 0), mid = (s1 + s2) / 2;
				const a = XY(p.c, mid), b = XY(q.c, mid), end = XY(q.c, s2);
				d += ' C' + f(a[0]) + ' ' + f(a[1]) + ' ' + f(b[0]) + ' ' + f(b[1]) + ' ' + f(end[0]) + ' ' + f(end[1]);
				if (k < points.length - 1) { const through = XY(q.c, q.e); d += ' L' + f(through[0]) + ' ' + f(through[1]); }
			}
			return d;
		};

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
				overlay.appendChild(svgEl('path', { d: curve([pointOf(e.b), pointOf(e.a)]), class: 'graphHidden', 'marker-end': 'url(#graphArrow)' }));
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
			const [x, y] = XY(it.c, it.l);
			el.appendChild(svgEl('rect', { x: f(x), y: f(y), width: it.w, height: it.h, rx: 6 }));
			it.lines.forEach((line, k) => {
				const text = svgEl('text', { x: f(x + it.w / 2), y: f(y + 13.5 + k * LINE_H), 'text-anchor': 'middle', 'dominant-baseline': 'central' });
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

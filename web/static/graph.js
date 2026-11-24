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
	let fades = 0; // the gradients of the shadows of running series, numbered across all maps so that no id is used twice
	const RUNNING_TAIL = 40; // how far the shadow of a series that is still running goes on past the last step, fading out
	const MARKER_STEP = 10; // the width of the slim step of the year a series ended in, when no box stands in that year
	const STACK_STEP = 4; // the layers behind the box of a series (two) or a miniseries (one), each this far offset
	const GROUP_WEIGHT = 6000; // how firmly the box of a series and its shadow stay together, against 1 for a connection
	const CROOKED_COST = 6, MAIN_LINE_COST = 3, STRAIGHTEN_REACH = 160; // see straighten: the fixed cost of a connection that is not straight, how much more the main line counts, how far a connection may be off and still be straightened (px)
	const COLLAPSE_MIN = 6; // this many titles that are not in the library and hang off one title the same way become one node
	const SYMMETRIC = ['version_of', 'alternate_language_version_of'];
	const SENTENCES = {
		follows: 'follows',
		spin_off_from: 'is a spin-off of',
		remake_of: 'is a remake of',
		version_of: 'is a version of',
		alternate_language_version_of: 'is an alternate-language version of'
	};
	// how a connection type is drawn: "follows" is the solid main line; the colour of each type is in the stylesheet. The
	// arrowhead is a marker (below); a version has none, as it reads the same in both directions.
	const DASH = { follows: '', spin_off_from: '7 4', remake_of: '10 3 2 3', version_of: '2 3.5', alternate_language_version_of: '2 3.5' };
	const ARROW = { follows: 'graphArrow', spin_off_from: 'graphArrowSpinOff', remake_of: 'graphArrowRemake' };

	function svgEl(tag, attrs) {
		const el = document.createElementNS(SVG_NS, tag);
		if (attrs) Object.keys(attrs).forEach(k => el.setAttribute(k, attrs[k]));
		return el;
	}

	// ------------------------------------------------------------------------------------------------------ layout

	// Straightening, the last step of the placement: where a connection is off a straight line, the boxes that are already in
	// line with each other are moved together until it is straight -- when there is room, and the drawing as a whole gets
	// better: a crooked connection costs a fixed amount plus its offset, one of the main line of sequels three times that. A
	// stop of a long connection that is in the way is moved along with its line; a box, or the shadow of a series, is never pushed aside.
	function straighten(rows, links, minC, maxC) {
		const segs = [];
		links.forEach(l => { for (let k = 0; k + 1 < l.chain.length; k++) segs.push({ a: l.chain[k], b: l.chain[k + 1], w: l.type === 'follows' || l.type === 'span' ? MAIN_LINE_COST : 1 }); });
		const itemOf = new Map(), incident = new Map();
		rows.forEach(r => r.forEach(it => itemOf.set(it.id, it)));
		segs.forEach(s => { [s.a, s.b].forEach(id => { if (!incident.has(id)) incident.set(id, []); incident.get(id).push(s); }); });
		const mid = id => { const it = itemOf.get(id); return it.c + it.lane / 2; };
		const offset = s => mid(s.b) - mid(s.a);
		const cost = (s, da, db) => { const dx = Math.abs(offset(s) + db - da); return dx < 0.5 ? 0 : s.w * (CROOKED_COST + dx); };
		// the items in line with this one: connected to it by exactly straight connections
		const lineOf = id => {
			const seen = new Set([id]), stack = [id];
			while (stack.length) {
				const x = stack.pop();
				(incident.get(x) || []).forEach(s => {
					if (Math.abs(offset(s)) >= 0.5) return;
					const y = s.a === x ? s.b : s.a;
					if (!seen.has(y)) { seen.add(y); stack.push(y); }
				});
			}
			return seen;
		};
		const tryMove = (start, delta) => {
			const members = new Set(start);
			for (let attempt = 0; ; attempt++) {
				let blocker = null;
				for (const id of members) {
					const it = itemOf.get(id), c = it.c + delta;
					if (c < minC - 1e-6 || c + it.lane > maxC + 1e-6) return false;
					const row = rows[it.row], i = row.indexOf(it), left = row[i - 1], right = row[i + 1];
					if (left && !members.has(left.id) && c < left.c + left.lane + GAP - 1e-6) { blocker = left; break; }
					if (right && !members.has(right.id) && c + it.lane + GAP > right.c + 1e-6) { blocker = right; break; }
				}
				if (!blocker) break;
				if (blocker.node || blocker.shadowOf || attempt > 12) return false;
				lineOf(blocker.id).forEach(x => members.add(x));
			}
			let before = 0, after = 0;
			const counted = new Set();
			members.forEach(id => (incident.get(id) || []).forEach(s => {
				if (counted.has(s)) return;
				counted.add(s);
				before += cost(s, 0, 0);
				after += cost(s, members.has(s.a) ? delta : 0, members.has(s.b) ? delta : 0);
			}));
			if (after >= before - 1e-6) return false;
			members.forEach(id => { itemOf.get(id).c += delta; });
			return true;
		};
		for (let pass = 0; pass < 40; pass++) {
			let changed = false;
			segs.slice().sort((p, q) => q.w - p.w || Math.abs(offset(p)) - Math.abs(offset(q))).forEach(s => {
				const dx = offset(s);
				if (Math.abs(dx) < 0.5 || Math.abs(dx) > STRAIGHTEN_REACH) return;
				if (tryMove(lineOf(s.b), -dx) || tryMove(lineOf(s.a), dx)) changed = true;
			});
			if (!changed) break;
		}
	}

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
				if (n.owned || n.current || degree.get(leaf) !== 1) return;
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
		// steps (the year is written once, over all of them). The years decide: a connection that runs against them (a remake
		// of a title that came out later, say) is drawn backwards, from the later title to the earlier one.
		const directed = edges.map(e => {
			if (!SYMMETRIC.includes(e.type)) return { from: e.b, to: e.a, e };
			const a = nodes.get(e.a), b = nodes.get(e.b);
			return (a.sortYear < b.sortYear || (a.sortYear === b.sortYear && String(e.a) < String(e.b))) ? { from: e.a, to: e.b, e } : { from: e.b, to: e.a, e };
		});
		const rank = new Map();
		let step = 0;
		// a series has a shadow that runs along the timeline to the year it ended in, a step of its own if no box stands in it
		const seriesNodes = [...nodes.values()].filter(n => n.isSeries && n.year);
		const tail = seriesNodes.some(n => !n.endYear) ? RUNNING_TAIL : 0; // room beyond the last step for a shadow that fades out there
		const endYears = new Set(seriesNodes.filter(n => n.endYear && n.endYear > n.sortYear).map(n => n.endYear));
		const lastStepOf = new Map();
		[...new Set([...nodes.values()].map(n => n.sortYear).concat([...endYears]))].sort((a, b) => a - b).forEach(year => {
			const ids = [...nodes.keys()].filter(id => nodes.get(id).sortYear === year), sub = new Map(ids.map(id => [id, 0]));
			for (let i = 0; i <= ids.length; i++) {
				let changed = false;
				directed.forEach(d => { if (sub.has(d.from) && sub.has(d.to) && sub.get(d.to) < sub.get(d.from) + 1) { sub.set(d.to, sub.get(d.from) + 1); changed = true; } });
				if (!changed) break;
			}
			ids.forEach(id => rank.set(id, step + sub.get(id)));
			step += ids.length ? Math.max(...sub.values()) + 1 : 1;
			lastStepOf.set(year, step - 1);
		});
		seriesNodes.forEach(n => { if (n.endYear && n.endYear > n.sortYear) rank.set('end:' + n.id, lastStepOf.get(n.endYear)); });
		// the steps a connection crosses, between its two ends
		const crossed = d => { const a = rank.get(d.from), b = rank.get(d.to); return [Math.min(a, b) + 1, Math.max(a, b)]; };
		if (!horizontal) {
			// a step that is wider than the drawing is split in two, one half below the other (the year stays over both)
			for (let guard = 0; guard < 200; guard++) {
				const last = Math.max(...rank.values());
				const real = Array.from({ length: last + 1 }, () => []), dummies = new Array(last + 1).fill(0);
				rank.forEach((r, id) => { if (!String(id).startsWith('end:')) real[r].push(id); });
				// a shadow takes the room of a box in every step it covers
				const shadows = new Array(last + 1).fill(0);
				seriesNodes.forEach(n => {
					const r0 = rank.get(n.id), r1 = rank.has('end:' + n.id) ? rank.get('end:' + n.id) : (n.endYear ? r0 : last);
					for (let r = r0 + 1; r <= r1; r++) shadows[r]++;
				});
				directed.forEach(d => { const [first, end] = crossed(d); for (let r = first; r < end; r++) dummies[r]++; });
				const need = (r, count) => (count + shadows[r]) * boxW + dummies[r] * DUMMY_W + Math.max(0, count + shadows[r] + dummies[r] - 1) * GAP;
				const over = real.findIndex((ids, r) => ids.length > 1 && need(r, ids.length) > W - axisV - 2 * PAD);
				if (over < 0) break;
				const ids = real[over].slice().sort((x, y) => String(x).localeCompare(String(y)));
				rank.forEach((r, id) => { if (r > over) rank.set(id, r + 1); });
				ids.slice(Math.ceil(ids.length / 2)).forEach(id => rank.set(id, over + 1));
			}
		}
		const stepCount = Math.max(...rank.values()) + 1;
		if (horizontal) {
			const boxSteps = new Set();
			nodes.forEach((n, id) => boxSteps.add(rank.get(id)));
			boxW = Math.min(132, Math.floor((W - 2 * PAD - (stepCount - 1) * COLUMN_GAP - (stepCount - boxSteps.size) * MARKER_STEP - tail) / boxSteps.size));
			if (boxW < BOX_MIN) return null;
		}

		// 4. long connections get an invisible stop in every step they cross, so the steps can make room for them
		const items = new Map();
		nodes.forEach((n, id) => items.set(id, { id, node: n, row: rank.get(id) }));
		const links = [];
		directed.forEach(d => {
			// the chain runs along the steps; one that runs against the years is drawn from its last item back to its first
			const backward = rank.get(d.to) < rank.get(d.from), [early, late] = backward ? [d.to, d.from] : [d.from, d.to];
			const chain = [early];
			for (let r = rank.get(early) + 1; r < rank.get(late); r++) {
				const id = 'dummy:' + links.length + ':' + r;
				items.set(id, { id, node: null, row: r });
				chain.push(id);
			}
			chain.push(late);
			links.push({ type: d.e.type, chain, edge: d.e, backward });
		});

		// the shadow of a series: an item as wide as its box in every step up to the one of its last year (a marker in that one);
		// a series without an end year has one to the last step
		seriesNodes.forEach(n => {
			const r0 = rank.get(n.id), chain = [n.id];
			const shadow = r => { const id = 'shadow:' + n.id + ':' + r; items.set(id, { id, node: null, row: r, shadowOf: n.id }); chain.push(id); };
			if (n.endYear && n.endYear > n.sortYear) {
				const endId = 'end:' + n.id;
				for (let r = r0 + 1; r < rank.get(endId); r++) shadow(r);
				items.set(endId, { id: endId, node: null, row: rank.get(endId), marker: true, markerYear: n.endYear, shadowOf: n.id });
				chain.push(endId);
				links.push({ type: 'span', chain, edge: { a: n.id, b: n.id, type: 'span' }, span: { id: n.id, ended: true } });
			} else if (!n.endYear) {
				for (let r = r0 + 1; r < stepCount; r++) shadow(r);
				links.push({ type: 'span', chain, edge: { a: n.id, b: n.id, type: 'span' }, span: { id: n.id, running: true } });
			}
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
			} else { i.lane = DUMMY_W; i.lev = i.marker ? MARKER_STEP : 0; i.w = DUMMY_W; i.h = 0; }
		});
		// the box of a series and its shadow are one group, which keeps one position across the steps
		items.forEach(i => { if (i.shadowOf) { i.lane = items.get(i.shadowOf).lane; i.group = i.shadowOf; } });
		links.forEach(l => { if (l.type === 'span') items.get(l.chain[0]).group = l.chain[0]; });

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
				const w = (l.type === 'follows' || l.type === 'span' ? MAIN_LINE_PULL : 1) * (items.get(a).node ? 1 : 2) * (items.get(b).node ? 1 : 2);
				pull.set(a + '|' + b, (pull.get(a + '|' + b) || 0) + w);
				pull.set(b + '|' + a, (pull.get(b + '|' + a) || 0) + w);
			}
		});
		// among items that want the same place a shadow comes first, so the lines of its series run beside it
		rows.forEach(r => r.sort((a, b) => ((a.node ? a.node.sortYear : 1e9) - (b.node ? b.node.sortYear : 1e9)) || ((b.shadowOf ? 1 : 0) - (a.shadowOf ? 1 : 0)) || String(a.id).localeCompare(String(b.id))));
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
				const keys = new Map(rows[r].map(it => [it.id, key(it) - (it.shadowOf ? 1e-4 : 0)]));
				rows[r].sort((a, b) => keys.get(a.id) - keys.get(b.id));
			});
			transpose();
			const count = totalCrossings();
			if (count < bestCount) { bestCount = count; best = rows.map(r => r.slice()); }
		}
		best.forEach((r, i) => { rows[i] = r; });

		// 7. position across the steps: every item is pulled towards its neighbours on both sides (the main line of sequels
		// and the stops of long connections count more), and each step is then set as close to those wishes as its order and
		// the room the boxes need allow -- a fan sits centred over what it hangs off. Connections that are only a little off
		// a straight line are then straightened
		const laneW = W - axisV, minC = horizontal ? -Infinity : PAD, maxC = horizontal ? Infinity : laneW - PAD;
		rows.forEach(r => {
			const total = r.reduce((s, it) => s + it.lane, 0) + (r.length - 1) * GAP;
			let c = (horizontal ? 0 : laneW / 2) - total / 2;
			r.forEach(it => { it.c = c; c += it.lane + GAP; });
		});
		const centre = it => it.c + it.lane / 2, middle = horizontal ? 0 : laneW / 2;
		for (let pass = 0; pass < 120; pass++) {
			const order = pass % 2 === 0 ? rows.map((_, i) => i) : rows.map((_, i) => rows.length - 1 - i);
			// a series box and its shadow are one thing. At first it wants to be where the connections of the box pull it; later
			// where the members of the group actually are on average, so that they agree even where a step has to make room
			const pulls = new Map(), where = new Map(), targets = new Map();
			rows.forEach(r => r.forEach(it => {
				if (!it.group) return;
				const w = where.get(it.group) || { sum: 0, n: 0 };
				w.sum += centre(it); w.n++; where.set(it.group, w);
				const a = pulls.get(it.group) || { sw: MIDDLE_PULL, sc: MIDDLE_PULL * middle };
				[...new Set((up.get(it.id) || []).concat(down.get(it.id) || []))].forEach(n => {
					if (items.get(n).group === it.group) return;
					const k = pull.get(it.id + '|' + n);
					a.sw += k; a.sc += k * centre(items.get(n));
				});
				pulls.set(it.group, a);
			}));
			pulls.forEach((a, g) => { const own = a.sc / a.sw, mean = where.get(g).sum / where.get(g).n; targets.set(g, pass < 15 ? own : pass < 30 ? (own + mean) / 2 : mean); });
			order.forEach(r => {
				const row = rows[r], offset = [];
				let acc = 0;
				row.forEach(it => { offset.push(acc); acc += it.lane + GAP; });
				// wishes, shifted by the room taken by the items before them: they must come out in the same order
				const wish = row.map((it, i) => {
					if (it.group) return { q: targets.get(it.group) - it.lane / 2 - offset[i], w: GROUP_WEIGHT };
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
		straighten(rows, links, minC, maxC);
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
		const levEnd = p - gap + PAD + tail;

		// 9. the axis: the year of every step; steps of one year share one label with a bracket over all of them
		const yearsOf = r => new Set(rows[r].filter(it => (it.node && it.node.sortYear) || it.marker).map(it => it.node ? it.node.sortYear : it.markerYear));
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
		return { items, links, hidden, realEdges, nodes, width, height, horizontal, axisV, axis, levSize, laneExtent };
	}

	// the map runs left to right when its steps fit the width and that is not taller than downward, otherwise downward
	function bestLayout(graph, W, fontFamily) {
		const downward = layout(graph, W, fontFamily, false), across = layout(graph, W, fontFamily, true);
		return across && across.height <= downward.height ? across : downward;
	}

	// --------------------------------------------------------------------------------------------------------- drawing

	// the layers behind the box of a series, from the back (a miniseries has one, a series two)
	function stackOf(n) {
		return !n.isSeries ? [] : n.mini ? [STACK_STEP] : [2 * STACK_STEP, STACK_STEP];
	}

	// the years a series ran: "2011–2013", "2011–" (no end year known), "2014" (one year)
	function runtime(n) {
		if (!n.startYear) return '';
		return n.endYear == null ? n.startYear + '–' : n.endYear === n.startYear ? String(n.startYear) : n.startYear + '–' + n.endYear;
	}

	function label(n) {
		const years = n.isSeries ? runtime(n) : n.yearText;
		return n.title + (years ? ' (' + years + ')' : '');
	}

	function render(container, graph, hooks) {
		container.replaceChildren();
		const L = bestLayout(graph, hooks.width, hooks.fontFamily);
		const svg = svgEl('svg', { viewBox: '0 0 ' + Math.ceil(L.width) + ' ' + Math.ceil(L.height), role: 'group', 'aria-label': 'Connection map' });
		svg.style.width = Math.ceil(L.width) + 'px';
		svg.style.maxWidth = '100%';
		const defs = svgEl('defs');
		// the arrowheads, in the colour of their line: an open chevron (followed by), a filled triangle (spin-off) and a
		// diamond (remake) that is open, i.e. filled with the colour of the panel the map is on
		const chevron = svgEl('marker', { id: 'graphArrow', viewBox: '0 0 10 10', refX: '8', refY: '5', markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse' });
		chevron.appendChild(svgEl('path', { d: 'M2 1L8 5L2 9', fill: 'none', stroke: 'context-stroke', 'stroke-width': '1.5', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
		const triangle = svgEl('marker', { id: 'graphArrowSpinOff', viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse' });
		triangle.appendChild(svgEl('path', { d: 'M1 1.2L9.5 5L1 8.8Z', fill: 'context-stroke', stroke: 'context-stroke', 'stroke-width': '1', 'stroke-linejoin': 'round' }));
		const diamond = svgEl('marker', { id: 'graphArrowRemake', viewBox: '0 0 12 12', refX: '11', refY: '6', markerWidth: '8', markerHeight: '8', orient: 'auto-start-reverse' });
		diamond.appendChild(svgEl('path', { d: 'M1 6L6 2L11 6L6 10Z', class: 'graphDiamond', stroke: 'context-stroke', 'stroke-width': '1.4', 'stroke-linejoin': 'round' }));
		defs.append(chevron, triangle, diamond);
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

		const shadowLayer = svgEl('g'), stackLayer = svgEl('g'), edgeLayer = svgEl('g'), overlay = svgEl('g'), nodeLayer = svgEl('g');
		svg.append(shadowLayer, stackLayer, edgeLayer, overlay, nodeLayer); // the layers behind a series box are beneath the lines
		const edgeEls = [], nodeEls = new Map();
		// where a connection leaves / enters an item: its lane position and the extent along the steps (a stop is passed straight through)
		const pointOf = id => { const it = L.items.get(id); return { c: it.c + it.lane / 2, s: it.l, e: it.node ? it.l + it.lev : it.l + L.levSize[it.row] }; };
		// backward: the points run against the steps, so a connection leaves an item on its early side and enters the next on its late side
		const curve = (points, backward) => {
			const exit = p => backward ? p.s : p.e, entry = (q, last) => backward ? q.e + (last ? 2 : 0) : q.s - (last ? 2 : 0);
			const start = XY(points[0].c, exit(points[0]));
			let d = 'M' + f(start[0]) + ' ' + f(start[1]);
			for (let k = 1; k < points.length; k++) {
				const p = points[k - 1], q = points[k], s1 = exit(p), s2 = entry(q, k === points.length - 1), mid = (s1 + s2) / 2;
				const a = XY(p.c, mid), b = XY(q.c, mid), end = XY(q.c, s2);
				d += ' C' + f(a[0]) + ' ' + f(a[1]) + ' ' + f(b[0]) + ' ' + f(b[1]) + ' ' + f(end[0]) + ' ' + f(end[1]);
				if (k < points.length - 1) { const through = XY(q.c, backward ? q.s : q.e); d += ' L' + f(through[0]) + ' ' + f(through[1]); }
			}
			return d;
		};

		L.links.forEach(l => {
			if (l.type === 'span') { drawShadow(l); return; }
			const points = l.chain.map(pointOf);
			if (l.backward) points.reverse();
			const path = svgEl('path', { d: curve(points, l.backward), class: 'graphEdge graphEdge--' + l.type });
			if (ARROW[l.type]) path.setAttribute('marker-end', 'url(#' + ARROW[l.type] + ')');
			if (DASH[l.type]) path.setAttribute('stroke-dasharray', DASH[l.type]);
			edgeLayer.appendChild(path);
			edgeEls.push({ el: path, edge: l.edge });
		});

		// the shadow of a series: its box's silhouette, layers included, stretched along the timeline from where the box ends to
		// the middle of the step of its last year; one that is still running fades out. Square where it starts, behind the layers.
		function drawShadow(l) {
			const box = L.items.get(l.chain[0]), tint = box.node.owned ? 'owned' : 'other';
			const depth = Math.max(0, ...stackOf(box.node)), start = box.l + depth + 6;
			const alongOf = it => it.l + (it.node ? it.lev : L.levSize[it.row]) / 2; // the middle of its step
			const lastItem = L.items.get(l.chain[l.chain.length - 1]);
			const end = l.span.ended ? alongOf(lastItem) : (l.chain.length > 1 ? lastItem.l + L.levSize[lastItem.row] : box.l + box.lev) + RUNNING_TAIL;
			const pieces = []; // a piece for every stretch in the same lane (normally one)
			let from = start;
			for (let k = 1; k < l.chain.length; k++) {
				const it = L.items.get(l.chain[k]), to = k === l.chain.length - 1 ? end : alongOf(it), prev = pieces[pieces.length - 1];
				const c = Math.abs(it.c - box.c) < 12 ? box.c : it.c;
				if (prev && Math.abs(prev.c - c) < 0.5) prev.to = to; else pieces.push({ c, from, to });
				from = to;
			}
			if (l.chain.length === 1) pieces.push({ c: box.c, from: start, to: end });
			pieces.forEach((p, k) => {
				const [X, Y] = XY(p.c, p.from), along = p.to - p.from, last = k === pieces.length - 1;
				const w = L.horizontal ? along : box.lane + depth, h = L.horizontal ? box.lane + depth : along, r = last && !l.span.running ? 6 : 0;
				// no outline along its start; rounded only at its far end
				const d = L.horizontal
					? 'M' + f(X) + ' ' + f(Y) + ' H' + f(X + w - r) + (r ? ' Q' + f(X + w) + ' ' + f(Y) + ' ' + f(X + w) + ' ' + f(Y + r) : '') + ' V' + f(Y + h - r) + (r ? ' Q' + f(X + w) + ' ' + f(Y + h) + ' ' + f(X + w - r) + ' ' + f(Y + h) : '') + ' H' + f(X)
					: 'M' + f(X + w) + ' ' + f(Y) + ' V' + f(Y + h - r) + (r ? ' Q' + f(X + w) + ' ' + f(Y + h) + ' ' + f(X + w - r) + ' ' + f(Y + h) : '') + ' H' + f(X + r) + (r ? ' Q' + f(X) + ' ' + f(Y + h) + ' ' + f(X) + ' ' + f(Y + h - r) : '') + ' V' + f(Y);
				const path = svgEl('path', { d, class: 'graphShadow graphShadow--' + tint });
				if (l.span.running && last) { // fill and outline fade out over the last part of it
					// a series in the last step has only its stub to fade out in; a longer shadow fades over its last part
					const fade = l.chain.length === 1 ? Math.min(0.9, RUNNING_TAIL / along) : Math.min(0.6, Math.max(0.25, 70 / along));
					const gradient = (rgb, alpha) => {
						const id = 'graphFade' + (++fades);
						const g = svgEl('linearGradient', { id, gradientUnits: 'userSpaceOnUse', x1: f(L.horizontal ? X : 0), y1: f(L.horizontal ? 0 : Y), x2: f(L.horizontal ? X + along : 0), y2: f(L.horizontal ? 0 : Y + along) });
						g.append(svgEl('stop', { offset: 0, 'stop-color': rgb, 'stop-opacity': alpha }), svgEl('stop', { offset: 1 - fade, 'stop-color': rgb, 'stop-opacity': alpha }), svgEl('stop', { offset: 1, 'stop-color': rgb, 'stop-opacity': 0 }));
						defs.appendChild(g);
						return 'url(#' + id + ')';
					};
					path.style.fill = tint === 'owned' ? gradient('rgb(56,142,60)', 0.16) : gradient('rgb(255,255,255)', 0.06);
					path.style.stroke = tint === 'owned' ? gradient('rgb(130,200,135)', 0.40) : gradient('rgb(255,255,255)', 0.28);
				}
				shadowLayer.appendChild(path);
			});
		}

		// what a title is connected to, in words, for the hover text
		const relationLines = id => {
			const byLabel = new Map();
			L.realEdges.forEach(e => {
				if (e.a !== id && e.b !== id) return;
				const other = L.nodes.get(e.a === id ? e.b : e.a), mine = e.a === id;
				const key = { follows: mine ? 'follows' : 'followed_by', spin_off_from: mine ? 'spin_off_from' : 'spin_off', remake_of: mine ? 'remake_of' : 'remade_as',
					version_of: 'version_of', alternate_language_version_of: 'alternate_language_version_of' }[e.type];
				const text = label(other);
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
			const n = it.node, current = !!n.current, cluster = n.kind === 'cluster';
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
			// a series is a stack of cards: the layers behind it solid and beneath the lines, the front one solid as well, so
			// nothing shows through it
			const card = (parent, offset) => {
				const base = svgEl('rect', { x: f(x + offset), y: f(y + offset), width: it.w, height: it.h, rx: 6 });
				base.style.fill = 'var(--detailBg, #2a2b30)';
				base.style.stroke = 'none';
				parent.appendChild(base);
				return svgEl('rect', { x: f(x + offset), y: f(y + offset), width: it.w, height: it.h, rx: 6 });
			};
			stackOf(n).forEach(offset => {
				const layer = svgEl('g', { class: 'graphNode' + (n.owned ? ' graphNode--owned' : '') });
				layer.appendChild(card(layer, offset));
				stackLayer.appendChild(layer);
			});
			el.appendChild(n.isSeries ? card(el, 0) : svgEl('rect', { x: f(x), y: f(y), width: it.w, height: it.h, rx: 6 }));
			it.lines.forEach((line, k) => {
				const text = svgEl('text', { x: f(x + it.w / 2), y: f(y + 13.5 + k * LINE_H), 'text-anchor': 'middle', 'dominant-baseline': 'central' });
				text.textContent = line;
				el.appendChild(text);
			});
			const tip = svgEl('title');
			tip.textContent = [label(n) + (cluster ? ' – click for the list' : target ? (target.external ? ' – not in the library' : '') : n.kind === 'title' ? ' – this title' : ' – an episode of this series')].concat(relationLines(n.id)).join('\n');
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
			if (ARROW[type]) path.setAttribute('marker-end', 'url(#' + ARROW[type] + ')');
			if (DASH[type]) path.setAttribute('stroke-dasharray', DASH[type]);
			s.appendChild(path);
			item.append(s, document.createTextNode(text));
			return item;
		};
		// the boxes of the title shown: itself, or for a series its episodes and, if it has connections of its own, the series
		const mine = [...L.nodes.values()].filter(n => n.current);
		const ownText = mine.some(n => n.kind !== 'title') ? (mine.some(n => n.kind === 'title') ? 'This series and its episodes' : 'Episodes of this series') : 'This title';
		// series and miniseries: the same stack of cards as on the map
		const stackSwatch = (layers, text) => {
			const item = document.createElement('span');
			const sv = svgEl('svg', { width: 28, height: 16, viewBox: '0 0 28 16', 'aria-hidden': 'true' });
			const g = svgEl('g', { class: 'graphNode' });
			[...layers.map(o => o / 1.6), 0].forEach(off => {
				const base = svgEl('rect', { x: 0.5 + off, y: 0.5 + off, width: 19, height: 10, rx: 3 });
				base.style.fill = 'var(--detailBg, #2a2b30)';
				base.style.stroke = 'none';
				g.append(base, svgEl('rect', { x: 0.5 + off, y: 0.5 + off, width: 19, height: 10, rx: 3 }));
			});
			sv.appendChild(g);
			item.append(sv, document.createTextNode(text));
			return item;
		};
		const hasSeries = [...L.nodes.values()].some(n => n.isSeries && !n.mini), hasMini = [...L.nodes.values()].some(n => n.isSeries && n.mini);
		legend.append(swatch('graphNode--owned', 'In the library'), swatch('', 'Not in the library'), swatch('graphNode--owned graphNode--current', ownText));
		if (hasSeries) legend.appendChild(stackSwatch([8, 4], 'Series'));
		if (hasMini) legend.appendChild(stackSwatch([4], 'Miniseries'));
		const present = new Set(L.links.map(l => l.type === 'alternate_language_version_of' ? 'version_of' : l.type));
		[['follows', 'Followed by'], ['spin_off_from', 'Spin-off'], ['remake_of', 'Remake'], ['version_of', 'Version of']].forEach(([type, text]) => { if (present.has(type)) legend.appendChild(line(type, text)); });
		container.appendChild(legend);

		// the same connections as plain sentences, for screen readers
		const sentences = document.createElement('ul');
		sentences.className = 'srOnly';
		L.realEdges.forEach(e => {
			const item = document.createElement('li');
			item.textContent = label(L.nodes.get(e.a)) + ' ' + SENTENCES[e.type] + ' ' + label(L.nodes.get(e.b));
			sentences.appendChild(item);
		});
		container.appendChild(sentences);
	}

	window.ConnectionGraph = { render };
})();

// prevent the browser from auto-restoring the previous scroll offset on reload -- combined with
// resetFilters() being called on every load below (rather than fetchResults('') directly), a plain
// page reload should always come back to a clean, default state, never whatever was left over from
// before the reload (this is pure browser behavior, unrelated to and unaffected by server restarts)
if ('scrollRestoration' in history) {
	history.scrollRestoration = 'manual';
}

document.addEventListener('DOMContentLoaded', () => {
	const resetButton = document.getElementById('resetButton');

    const input = document.getElementById('searchInput');
    const results = document.getElementById('results');
	const errorBanner = document.getElementById('errorBanner');
	const sortSelect = document.getElementById('sortSelect');
	const orderButton = document.getElementById('orderButton');
	
	const yearFrom = document.getElementById('yearFrom');
    const yearTo = document.getElementById('yearTo');
    const ratingFrom = document.getElementById('ratingFrom');
    const ratingTo = document.getElementById('ratingTo');
    const votesFrom = document.getElementById('votesFrom');
    const votesTo = document.getElementById('votesTo');
	
	const moviesCheckbox = document.getElementById('moviesCheckbox');
	const seriesCheckbox = document.getElementById('seriesCheckbox');

	const languageRadios = document.querySelectorAll('.languageRadio');
	const genreCheckboxes = document.querySelectorAll('.genreCheckbox');
	const interestCheckboxes = document.querySelectorAll('.interestCheckbox');
	const interestSearchInput = document.getElementById('interestSearchInput');
	const interestGroupEls = document.querySelectorAll('.interest-group');

	function filterInterests() {
		const query = interestSearchInput.value.trim().toLowerCase();

		interestGroupEls.forEach(group => {
			let anyVisible = false;

			group.querySelectorAll('.interestLabel').forEach(label => {
				const match = label.dataset.search.includes(query);
				label.classList.toggle('hidden', !match);
				if (match) anyVisible = true;
			});

			group.classList.toggle('hidden', !anyVisible);
		});
	}

	let viewMode = "grid";

	const listViewBtn = document.getElementById('listViewBtn');
	const gridViewBtn = document.getElementById('gridViewBtn');
	gridViewBtn.classList.add("activeView");

	listViewBtn.addEventListener('click', () => {
		viewMode = "list";
		
		listViewBtn.classList.add("activeView");
		gridViewBtn.classList.remove("activeView");
		
		resetAndSearch();
	});

	gridViewBtn.addEventListener('click', () => {
		viewMode = "grid";
		
		gridViewBtn.classList.add("activeView");
		listViewBtn.classList.remove("activeView");
		
		resetAndSearch();
	});
	
	let debounceTimer;
	let currentOrder = 'desc';
	
	const PAGE_SIZE = 50; // must match the page size (limit) server.py's /search returns
	// "random" sort: a fresh seed is drawn each time that option is SELECTED (see the sortSelect change
	// handler), and the same seed is sent with every request for as long as it stays selected -- so
	// adding or changing filters, paging and infinite scroll all keep the same order (the server derives
	// a title's position from its id and this seed only, see server.py's _randomKey)
	let randomSeed = 0;
	let currentPage = 1;
	let isLoading = false;
	let allLoaded = false;
	let currentSearchController = null;
	
	function formatYearRange(startYear, endYear, isSeries) {
		if (!isSeries) return startYear ?? '—';
		if (endYear === startYear) return String(startYear);
		return startYear + ' -' + (endYear ? ' ' + endYear : '');
	}

	function formatNumVotes(num) {
		if (num < 1000) {
			return num.toString();
		} else if (num < 10000) {
			return (num / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
		} else if (num < 1000000) {
			return Math.round(num / 1000) + 'k';
		} else {
			return (num / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
		}
	}
	
	const toggleBtn = document.getElementById('toggleSidebarBtn');
	const sidebar = document.querySelector('.sidebar');
	const content = document.querySelector('.content');

	let sidebarCollapsed = false;

	toggleBtn.addEventListener('click', () => {
		sidebarCollapsed = !sidebarCollapsed;

		sidebar.classList.toggle('collapsed');
		content.classList.toggle('collapsed');

		// rotates the chevron icon via CSS instead of swapping text
		toggleBtn.classList.toggle('collapsed', sidebarCollapsed);
	});

	// ---- title detail overlay ----
	const detailBackdrop = document.getElementById('detailBackdrop');
	const detailCover = document.getElementById('detailCover');
	const detailTitle = document.getElementById('detailTitle');
	const detailMeta = document.getElementById('detailMeta');
	const detailChips = document.getElementById('detailChips');
	const detailBody = document.getElementById('detailBody');
	const coverLightbox = document.getElementById('coverLightbox');
	const coverLightboxImg = document.getElementById('coverLightboxImg');

	const CONNECTION_LABELS = {
		follows: 'Follows',
		followed_by: 'Followed by',
		remake_of: 'Remake of',
		remade_as: 'Remade as',
		spin_off: 'Spin-off',
		spin_off_from: 'Spin-off from',
		version_of: 'Version of',
		alternate_language_version_of: 'Alternate-language version of'
	};
	const VISIBLE_CAST_COUNT = 10;

	let detailRequestId = 0;

	function idString(imdb_id) {
		return 'tt' + String(imdb_id).padStart(7, '0');
	}

	function makeEl(tag, className, text) {
		const el = document.createElement(tag);
		if (className) el.className = className;
		if (text !== undefined) el.textContent = text;
		return el;
	}

	// plain left-click opens the overlay; ctrl/cmd/middle-click still follow the link's own IMDb href
	function attachDetailOpen(element, imdb_id) {
		element.addEventListener('click', e => {
			if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
			e.preventDefault();
			openDetail(imdb_id);
		});
	}

	function nameList(people, showDetails) {
		const wrap = makeEl('span', 'detailNames');
		people.forEach(p => {
			const span = makeEl('span', '', p.name);
			if (p.birthYear) span.title = 'b. ' + p.birthYear + (p.deathYear ? ', d. ' + p.deathYear : '');
			if (showDetails && p.details) span.appendChild(makeEl('span', 'muted', ' (' + p.details + ')'));
			wrap.appendChild(span);
		});
		return wrap;
	}

	function castList(actors) {
		const wrap = makeEl('span', 'detailNames');
		const first = nameList(actors.slice(0, VISIBLE_CAST_COUNT), true);
		wrap.appendChild(first);
		if (actors.length > VISIBLE_CAST_COUNT) {
			const rest = nameList(actors.slice(VISIBLE_CAST_COUNT), true);
			rest.style.display = 'none';
			const more = makeEl('button', 'detailMore', '+ ' + (actors.length - VISIBLE_CAST_COUNT) + ' more');
			more.type = 'button';
			more.addEventListener('click', () => {
				rest.style.display = 'flex';
				more.remove();
			});
			wrap.appendChild(more);
			wrap.appendChild(rest);
		}
		return wrap;
	}

	function renderDetail(d) {
		detailTitle.textContent = d.title;

		const rating = d.rating ? d.rating.toFixed(1) : '—';
		const votes = d.votes ? formatNumVotes(d.votes) : '—';
		let meta = formatYearRange(d.startYear, d.endYear, d.isSeries) + ' · ★ ' + rating + ' (' + votes + ' votes)';
		if (d.primaryTitle && d.primaryTitle !== d.title) meta += ' · also known as ' + d.primaryTitle;
		detailMeta.textContent = meta;

		detailChips.replaceChildren();
		d.interests.forEach(i => detailChips.appendChild(makeEl('span', 'detailChip' + (i.isGenre ? ' detailChip--genre' : ''), i.name)));
		const imdbLink = makeEl('a', 'imdbLink', 'IMDb ↗');
		imdbLink.href = 'https://www.imdb.com/title/' + idString(d.imdbId) + '/';
		imdbLink.target = '_blank';
		imdbLink.rel = 'noopener noreferrer';
		detailChips.appendChild(imdbLink);

		detailBody.replaceChildren();
		if (d.plotSummary) detailBody.appendChild(makeEl('p', 'plot', d.plotSummary));

		if (d.directors.length || d.writers.length || d.actors.length) {
			detailBody.appendChild(makeEl('h3', '', 'Cast & crew'));
			const grid = makeEl('div', 'detailGrid');
			[['Directed by', d.directors ? nameList(d.directors, false) : null, d.directors.length],
			 ['Written by', nameList(d.writers, false), d.writers.length],
			 ['Cast', castList(d.actors), d.actors.length]].forEach(([label, content, count]) => {
				if (!count) return;
				grid.appendChild(makeEl('span', 'label', label));
				grid.appendChild(content);
			});
			detailBody.appendChild(grid);
		}

		if (d.connections.length) {
			detailBody.appendChild(makeEl('h3', '', 'Connections'));
			const grid = makeEl('div', 'detailGrid');
			const byType = new Map();
			d.connections.forEach(c => {
				if (!byType.has(c.type)) byType.set(c.type, []);
				byType.get(c.type).push(c);
			});
			byType.forEach((targets, type) => {
				grid.appendChild(makeEl('span', 'label', CONNECTION_LABELS[type] || type));
				const cell = makeEl('span');
				targets.forEach(t => {
					const row = makeEl('span', 'connTarget');
					row.appendChild(makeEl('span', 'connDot' + (t.owned ? ' owned' : '')));
					const link = makeEl('a', '', t.title + (t.year ? ' (' + t.year + ')' : ''));
					if (t.owned) {
						link.href = '#' + idString(t.imdbId);
						link.title = 'in your library -- open';
						attachDetailOpen(link, t.imdbId);
					} else {
						link.href = 'https://www.imdb.com/title/' + idString(t.imdbId) + '/';
						link.title = 'not in your library -- open on IMDb';
						link.target = '_blank';
						link.rel = 'noopener noreferrer';
					}
					row.appendChild(link);
					cell.appendChild(row);
				});
				grid.appendChild(cell);
			});
			detailBody.appendChild(grid);
		}

		detailBody.scrollTop = 0;

		detailCover.classList.remove('noCover');
		detailCover.alt = d.title;
		const coverUrl = '/cover/' + idString(d.imdbId) + '.jpg';
		detailCoverId = d.imdbId;
		if (detailCover.getAttribute('src') !== coverUrl || !detailCover.complete) {
			detailCover.classList.add('loading'); // the previous title's poster must not linger meanwhile
			detailCover.src = coverUrl; // the tint follows from its load event (the previous one fades over meanwhile)
		} else {
			applyCoverTint(d.imdbId); // same cover already loaded (title reopened) -- no load event will fire
		}
	}

	// ---- cover-tinted overlay: the details panel and the poster pane take a dark, muted version of
	// the cover's dominant colour (CSS: --detailBg/--detailPaneBg on #detailPanel). The cover is
	// served from this same origin, so its pixels can be read through a canvas. Titles without a
	// usable colour (black-and-white poster, unreadable cover) get no tint and keep the neutral
	// charcoal. Results are cached per title for the life of the page.
	const TINT_MAX_SATURATION = 0.40;
	const TINT_PANEL_LIGHTNESS = 0.24, TINT_PANE_LIGHTNESS = 0.15;
	// upper limits on perceived brightness (WCAG relative luminance), so light text and the gray
	// labels stay readable even on bright hues (yellow/orange are much brighter than blue at the
	// same HSL lightness) -- the panel is darkened further until it fits under its limit
	const TINT_PANEL_MAX_LUMINANCE = 0.035, TINT_PANE_MAX_LUMINANCE = 0.015;
	const coverTintCache = new Map(); // imdb_id -> {panel, pane} or null
	let detailCoverId = null;

	function rgbToHsl(r, g, b) { // all 0..1
		const max = Math.max(r, g, b), min = Math.min(r, g, b);
		const l = (max + min) / 2;
		if (max === min) return [0, 0, l];
		const d = max - min;
		const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
		let h;
		if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
		else if (max === g) h = (b - r) / d + 2;
		else h = (r - g) / d + 4;
		return [h / 6, s, l];
	}

	function hslToRgb(h, s, l) {
		if (s === 0) return [l, l, l];
		const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
		const channel = t => {
			t = (t + 1) % 1;
			if (t < 1 / 6) return p + (q - p) * 6 * t;
			if (t < 1 / 2) return q;
			if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
			return p;
		};
		return [channel(h + 1 / 3), channel(h), channel(h - 1 / 3)];
	}

	function relativeLuminance(r, g, b) {
		const lin = c => c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
		return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
	}

	function mutedShade(h, s, lightness, maxLuminance) {
		let l = lightness, rgb;
		for (let i = 0; i < 30; i++) {
			rgb = hslToRgb(h, Math.min(s, TINT_MAX_SATURATION), l);
			if (relativeLuminance(...rgb) <= maxLuminance) break;
			l -= 0.01;
		}
		return 'rgb(' + rgb.map(c => Math.round(c * 255)).join(', ') + ')';
	}

	// dominant colour: pixels are bucketed by hue (24 buckets) and weighted by how vivid they are, so
	// a poster's black border, white credits and gray backgrounds don't count; the heaviest bucket's
	// weighted average wins. null if nothing colourful is left.
	function coverTint(img) {
		try {
			const w = 32, h = 48;
			const canvas = document.createElement('canvas');
			canvas.width = w;
			canvas.height = h;
			const ctx = canvas.getContext('2d', { willReadFrequently: true });
			ctx.imageSmoothingQuality = 'high';
			ctx.drawImage(img, 0, 0, w, h);
			const px = ctx.getImageData(0, 0, w, h).data;
			const buckets = new Map(); // hue bucket -> [weight, r*weight, g*weight, b*weight]
			for (let i = 0; i < px.length; i += 4) {
				if (px[i + 3] < 128) continue;
				const r = px[i] / 255, g = px[i + 1] / 255, b = px[i + 2] / 255;
				const [ph, ps, pl] = rgbToHsl(r, g, b);
				if (pl < 0.10 || pl > 0.92 || ps < 0.18) continue;
				const key = Math.floor(ph * 24) % 24;
				const weight = ps * (1 - Math.abs(2 * pl - 1));
				const e = buckets.get(key) || [0, 0, 0, 0];
				e[0] += weight; e[1] += r * weight; e[2] += g * weight; e[3] += b * weight;
				buckets.set(key, e);
			}
			if (buckets.size === 0) return null;
			const best = [...buckets.values()].reduce((a, b) => b[0] > a[0] ? b : a);
			const [hue, sat] = rgbToHsl(best[1] / best[0], best[2] / best[0], best[3] / best[0]);
			return {
				panel: mutedShade(hue, sat, TINT_PANEL_LIGHTNESS, TINT_PANEL_MAX_LUMINANCE),
				pane: mutedShade(hue, sat, TINT_PANE_LIGHTNESS, TINT_PANE_MAX_LUMINANCE)
			};
		} catch (e) {
			return null; // e.g. a tainted canvas -- just no tint
		}
	}

	function setCoverTint(tint) {
		const panel = document.getElementById('detailPanel');
		if (tint) {
			panel.style.setProperty('--detailBg', tint.panel);
			panel.style.setProperty('--detailPaneBg', tint.pane);
		} else {
			panel.style.removeProperty('--detailBg');
			panel.style.removeProperty('--detailPaneBg');
		}
	}

	function applyCoverTint(imdb_id) {
		let tint = coverTintCache.get(imdb_id);
		if (tint === undefined) {
			tint = coverTint(detailCover);
			coverTintCache.set(imdb_id, tint);
		}
		setCoverTint(tint);
	}

	// The tint is taken from the cover's THUMBNAIL rather than the full-size cover: the thumbnail is
	// what the result grid already loaded (so it's normally in the browser cache), it's small, and its
	// dominant colour matches the full cover's for practically every title. That lets openDetail have
	// the tint ready by the time the details arrive, so the overlay opens already in its final colour
	// instead of changing it once a possibly huge full-size cover has downloaded and decoded (the
	// cover's own load event remains the fallback, see applyCoverTint). Resolves -- never rejects --
	// to the tint, null for a title without a usable colour, or undefined if the thumbnail couldn't
	// be read (nothing cached then, so the full cover gets its chance).
	function tintFromThumbnail(imdb_id) {
		if (coverTintCache.has(imdb_id)) return Promise.resolve(coverTintCache.get(imdb_id));
		return new Promise(resolve => {
			const img = new Image();
			img.onload = () => {
				const tint = coverTint(img);
				coverTintCache.set(imdb_id, tint);
				resolve(tint);
			};
			img.onerror = () => resolve(undefined);
			img.src = '/cover_small/' + idString(imdb_id) + '.webp';
		});
	}

	detailCover.addEventListener('load', () => {
		detailCover.classList.remove('loading');
		applyCoverTint(detailCoverId);
	});
	detailCover.addEventListener('error', () => {
		detailCover.classList.remove('loading');
		detailCover.classList.add('noCover');
		setCoverTint(null);
	});

	function openCoverLightbox() {
		if (detailCover.classList.contains('noCover')) return;
		coverLightboxImg.src = detailCover.src;
		coverLightbox.classList.remove('hidden');
	}

	function closeCoverLightbox() {
		coverLightbox.classList.add('hidden');
	}

	detailCover.addEventListener('click', openCoverLightbox);
	coverLightbox.addEventListener('click', closeCoverLightbox);

	function showDetailShell() {
		detailBackdrop.classList.remove('hidden');
		document.body.style.overflow = 'hidden';
		document.getElementById('detailClose').focus();
	}

	function hideDetail() {
		detailRequestId++; // anything still loading must not pop the overlay back open
		closeCoverLightbox();
		detailBackdrop.classList.add('hidden');
		document.body.style.overflow = '';
	}

	function openDetail(imdb_id, pushHistory = true) {
		const requestId = ++detailRequestId;
		const wasOpen = !detailBackdrop.classList.contains('hidden');
		new Image().src = '/cover/' + idString(imdb_id) + '.jpg'; // preload alongside the details request
		const tintReady = tintFromThumbnail(imdb_id); // likewise, see tintFromThumbnail
		fetch('/detail/' + imdb_id)
			.then(response => {
				if (!response.ok) {
					const err = new Error('detail request failed with status ' + response.status);
					err.status = response.status;
					throw err;
				}
				return response.json();
			})
			.then(d => tintReady.then(tint => [d, tint]))
			.then(([d, tint]) => {
				if (requestId !== detailRequestId) return; // superseded by a newer click, or closed meanwhile
				// set before the shell is shown, so a freshly opened overlay is already in its final colour;
				// if the thumbnail couldn't be read (undefined), start neutral rather than on the
				// previous title's colour -- the full cover's load event applies the real one
				setCoverTint(tint === undefined ? null : tint);
				renderDetail(d);
				showDetailShell();
				if (pushHistory) {
					const url = '#' + idString(imdb_id);
					if (wasOpen) history.replaceState({ detail: imdb_id }, '', url);
					else history.pushState({ detail: imdb_id }, '', url);
				}
			})
			.catch(err => {
				if (requestId !== detailRequestId) return;
				detailTitle.textContent = "Couldn't load details";
				detailMeta.textContent = '';
				detailChips.replaceChildren();
				detailBody.replaceChildren(makeEl('div', 'detailError', err.status === 404
					? "This title isn't in your library."
					: 'The database may be temporarily busy -- close this and try again in a moment.'));
				detailCover.classList.add('noCover');
				setCoverTint(null);
				showDetailShell();
			});
	}

	function closeDetail() {
		if (history.state && history.state.detail) {
			history.back(); // popstate below does the actual hiding, keeping URL and overlay in sync
		} else {
			hideDetail();
			if (location.hash) history.replaceState(null, '', location.pathname + location.search);
		}
	}

	function syncDetailWithHash() {
		const match = /^#tt(\d+)$/.exec(location.hash);
		if (match) {
			openDetail(parseInt(match[1], 10), false);
		} else {
			hideDetail();
		}
	}

	window.addEventListener('popstate', syncDetailWithHash);
	document.getElementById('detailClose').addEventListener('click', closeDetail);
	detailBackdrop.addEventListener('click', e => {
		if (e.target === detailBackdrop) closeDetail();
	});
	document.addEventListener('keydown', e => {
		if (e.key !== 'Escape') return;
		if (!coverLightbox.classList.contains('hidden')) {
			closeCoverLightbox();
		} else if (!detailBackdrop.classList.contains('hidden')) {
			closeDetail();
		}
	});

	function resetFilters() {
		input.value = '';

		sortSelect.value = 'year';
		orderButton.disabled = false;

		currentOrder = 'desc';
		orderButton.textContent = '↓ Descending';

		yearFrom.value = '';
		yearTo.value = '';
		ratingFrom.value = '';
		ratingTo.value = '';
		votesFrom.value = '';
		votesTo.value = '';

		moviesCheckbox.checked = true;
		seriesCheckbox.checked = false;

		document.querySelector('.languageRadio[value=""]').checked = true;

		genreCheckboxes.forEach(cb => cb.checked = false);
		interestCheckboxes.forEach(cb => cb.checked = false);
		interestSearchInput.value = '';
		filterInterests();

		currentPage = 1;
		allLoaded = false;

		fetchResults('', false);
	}
	
	function resetAndSearch() {
		currentPage = 1;
		allLoaded = false;
		fetchResults(input.value, false);
	}

    function fetchResults(query, append=false) {
		if (append && (isLoading || allLoaded)) return;

		// a fresh (non-append) search always supersedes whatever's still in flight -- fast filter
		// clicks would otherwise either get silently dropped by the isLoading guard above, or race
		// an older, slower response into overwriting newer results once it finally resolves
		if (currentSearchController) {
			currentSearchController.abort();
		}
		const thisSearchController = new AbortController();
		currentSearchController = thisSearchController;

		isLoading = true;

		const params = new URLSearchParams({
            q: query,
            sort: sortSelect.value,
            order: currentOrder,
            seed: randomSeed,
            year_from: yearFrom.value,
            year_to: yearTo.value,
            rating_from: ratingFrom.value,
            rating_to: ratingTo.value,
            votes_from: votesFrom.value,
            votes_to: votesTo.value,
            language: document.querySelector('.languageRadio:checked').value,
			movies: moviesCheckbox.checked ? '1' : '0',
			series: seriesCheckbox.checked ? '1' : '0',
			page: currentPage
        });

		genreCheckboxes.forEach(cb => {
			if (cb.checked) {
				params.append('genres[]', cb.value);
			}
		});

		interestCheckboxes.forEach(cb => {
			if (cb.checked) {
				params.append('interests[]', cb.value);
			}
		});

        fetch(`/search?${params.toString()}`, { signal: thisSearchController.signal })
            .then(response => {
                if (!response.ok) {
                    throw new Error('search request failed with status ' + response.status);
                }
                return response.json();
            })
            .then(data => {
				errorBanner.classList.add('hidden');

                if (!append) {
					results.innerHTML = '';
					
					if (viewMode === "grid") {
						results.classList.add("gridView");
					} else {
						results.classList.remove("gridView");
					}
				}
				
                if (data.length === 0) {
                    allLoaded = true;
                } else {
                    data.forEach(([imdb_id, originalTitle, startYear, endYear, rating_mul10, numVotes, genres, totalEpisodes, ownedEpisodes, isSeries]) => {
						const img = document.createElement('img');
						const isPartialSeries = totalEpisodes > 0 && ownedEpisodes < totalEpisodes;
						const isFullSeries = totalEpisodes > 0 && ownedEpisodes === totalEpisodes;

						const paddedId = String(imdb_id).padStart(7, '0');
						img.src = `/cover_small/tt${paddedId}.webp`;

						img.alt = originalTitle;
						// eager, not lazy: a chunk is now fetched a couple of screens before it's needed (see
						// loadMoreIfNearBottom), so its covers should start loading as soon as it's appended --
						// lazy loading would only start each one once layout has put it near the viewport,
						// which is exactly the late-covers gap this avoids. Async decoding keeps decoding a
						// whole chunk's covers off the main thread.
						img.loading = "eager";
						img.decoding = "async";
						img.classList.add("coverImage");
						
                        const titleElem = document.createElement('h2');
						const linkElem = document.createElement('a');
						linkElem.href = "https://www.imdb.com/title/tt" + String(imdb_id).padStart(7, "0") + "/";
						linkElem.target = "_blank";
						linkElem.rel = "noopener noreferrer";
						attachDetailOpen(linkElem, imdb_id);
						
                        const ratingsElem = document.createElement('div');
						const safeYear = formatYearRange(startYear, endYear, isSeries);
						const safeRating = rating_mul10 ? (rating_mul10 / 10).toFixed(1) : '—';
						const safeVotes = numVotes ? formatNumVotes(numVotes) : '—';
                        ratingsElem.textContent = safeRating + " (" + safeVotes + " votes)";
						
						const genresElem = document.createElement('div');
						genresElem.textContent = `${genres ?? '—'}`;

						if (viewMode === "list") {
							linkElem.classList.add("titleLink");
							linkElem.textContent = originalTitle + " (" + safeYear + ")";
							titleElem.appendChild(linkElem);

							if (isPartialSeries || isFullSeries) {
								const badge = document.createElement('span');
								badge.classList.add("ownershipBadge");
								if (isFullSeries) badge.classList.add("ownershipBadge--complete");
								badge.textContent = `${ownedEpisodes} / ${totalEpisodes}`;
								titleElem.appendChild(badge);
							}

							const wrapper = document.createElement('div');
							wrapper.classList.add("resultItem");

							img.style.cursor = "pointer";
							attachDetailOpen(img, imdb_id);
							wrapper.appendChild(img);

							const textBlock = document.createElement('div');
							textBlock.appendChild(titleElem);
							textBlock.appendChild(ratingsElem);
							textBlock.appendChild(genresElem);

							wrapper.appendChild(textBlock);

							results.appendChild(wrapper);
							results.appendChild(document.createElement('hr'));
						} else {
							const gridItem = document.createElement('div');
							gridItem.classList.add("gridItem");

							const imgWrapper = document.createElement('div');
							imgWrapper.classList.add("imgWrapper");

							const overlay = document.createElement('div');
							overlay.classList.add("overlay");
							
							const line1 = document.createElement('div');
							line1.textContent = `${safeYear} | ⭐ ${safeRating}`;

							const line2 = document.createElement('div');
							line2.textContent = `Votes: ${safeVotes}`;

							overlay.appendChild(line1);
							overlay.appendChild(line2);

							imgWrapper.appendChild(img);
							imgWrapper.appendChild(overlay);

							if (isPartialSeries || isFullSeries) {
								const badge = document.createElement('span');
								badge.classList.add("ownershipBadge", "ownershipBadge--grid");
								if (isFullSeries) badge.classList.add("ownershipBadge--complete");
								badge.textContent = `${ownedEpisodes} / ${totalEpisodes}`;
								imgWrapper.appendChild(badge);
							}

							linkElem.appendChild(imgWrapper);
							gridItem.appendChild(linkElem);

							results.appendChild(gridItem);
						}
                    });
					
					currentPage++;
					if (data.length < PAGE_SIZE) allLoaded = true; // a short page is the last one -- saves a pointless empty request
                }

				isLoading = false;
				// the page may still be within the prefetch distance of its end (a tall window, or a
				// chunk that's short in pixels), in which case no further scroll event is coming to
				// trigger the next chunk
				loadMoreIfNearBottom();
            })
			.catch((err) => {
				if (err.name === 'AbortError') return; // superseded by a newer search, not a real failure
				errorBanner.classList.remove('hidden');
				isLoading = false;
            });
    }
	
	function debounceSearch(query) {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            resetAndSearch(query);
        }, 300); // wait 300ms after last input
    }
	
	resetButton.addEventListener('click', resetFilters);
	
	orderButton.addEventListener('click', () => {
        if (currentOrder === 'desc') {
            currentOrder = 'asc';
            orderButton.textContent = '↑ Ascending';
        } else {
            currentOrder = 'desc';
            orderButton.textContent = '↓ Descending';
        }
        resetAndSearch(input.value);
    });

    input.addEventListener('input', () => {
        debounceSearch(input.value);
    });
	
	sortSelect.addEventListener('change', () => {
		if (sortSelect.value === 'random') {
			// a new random order every time the option is selected; it then stays the same until the
			// user picks another sort (filters etc. don't touch randomSeed)
			randomSeed = 1 + Math.floor(Math.random() * 2147483646);
		}
		orderButton.disabled = sortSelect.value === 'random'; // ascending/descending means nothing for a random order
        resetAndSearch(input.value);
    });

	languageRadios.forEach(radio => {
		radio.addEventListener('change', () => resetAndSearch(input.value));
	});

	moviesCheckbox.addEventListener('change', () => resetAndSearch(input.value));
	seriesCheckbox.addEventListener('change', () => resetAndSearch(input.value));

    [yearFrom, yearTo, ratingFrom, ratingTo, votesFrom, votesTo].forEach(el => {
        el.addEventListener('input', () => debounceSearch(input.value));
    });
	
	genreCheckboxes.forEach(cb => {
		cb.addEventListener('change', () => resetAndSearch(input.value));
	});

	interestCheckboxes.forEach(cb => {
		cb.addEventListener('change', () => resetAndSearch(input.value));
	});

	interestSearchInput.addEventListener('input', filterInterests);

	// Infinite scroll: the next chunk is fetched while the user is still PREFETCH_SCREENS screen heights
	// away from the end of the list, so it's already in place by the time they get there. (It used to
	// be a fixed 300px, i.e. less than one row of covers: fast scrolling reached the end of the chunk
	// before the next one had been fetched, appended and its covers loaded.) A chunk is ~50 covers,
	// only a few screens tall in a wide window, so this stays well within one chunk of lookahead.
	const PREFETCH_SCREENS = 2;

	function loadMoreIfNearBottom() {
		if (allLoaded || isLoading) return;
		if (window.innerHeight + window.scrollY >= document.body.offsetHeight - PREFETCH_SCREENS * window.innerHeight) {
			fetchResults(input.value, true);
		}
	}

	window.addEventListener('scroll', loadMoreIfNearBottom);
	
	// initially: show everything, via resetFilters() rather than fetchResults('') directly -- this
	// also forces every filter control back to its default, undoing whatever the browser may have
	// restored into them on this reload (see the scrollRestoration comment above)
    resetFilters();
	if (/^#tt\d+$/.test(location.hash)) syncDetailWithHash(); // a linked/reloaded title opens straight away
});
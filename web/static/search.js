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

	// the person filter (see index.html): the person the list is filtered by -- {id, name, roles: {kind: titles}} as
	// /person answers -- and the checkboxes of the kinds of credit that count
	const personInput = document.getElementById('personInput');
	const personSuggestions = document.getElementById('personSuggestions');
	const personFilterEl = document.getElementById('personFilter');
	const personChipName = document.getElementById('personChipName');
	const personRoleCheckboxes = [...document.querySelectorAll('.personRoleCheckbox')];
	let currentPerson = null;
    const results = document.getElementById('results');
    const resultCount = document.getElementById('resultCount');
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
	// narrow the SERIES that are shown (movies are unaffected); only available while Series is ticked
	const seriesMiniCheckbox = document.getElementById('seriesMiniCheckbox');
	const seriesEndedCheckbox = document.getElementById('seriesEndedCheckbox');
	const seriesFullCheckbox = document.getElementById('seriesFullCheckbox');

	function updateSeriesOptions() {
		const enabled = seriesCheckbox.checked;
		[seriesMiniCheckbox, seriesEndedCheckbox, seriesFullCheckbox].forEach(cb => {
			const label = cb.closest('label');
			if (!enabled) {
				cb.checked = false;
				label.classList.remove('excluded'); // see the NOT filter setup further down
			}
			cb.disabled = !enabled;
			label.classList.toggle('disabled', !enabled);
		});
	}

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
	const detailCoverPane = document.getElementById('detailCoverPane');
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
	// the title types the overview can list (Media.movieTitleTypes + Media.seriesTitleTypes), as shown in the detail view
	const TITLE_TYPE_LABELS = {
		movie: 'Movie',
		video: 'Video',
		short: 'Short',
		tvMovie: 'TV movie',
		tvSpecial: 'TV special',
		tvShort: 'TV short',
		tvSeries: 'TV series',
		tvMiniSeries: 'Mini series'
	};
	const VISIBLE_CAST_COUNT = 10;
	const VISIBLE_SEASON_COUNT = 12;

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
	// focus ({season, episode}, optional): a series' overlay then opens on that episode, see seasonsSection
	function attachDetailOpen(element, imdb_id, titleHint = '', focus = null) {
		element.addEventListener('click', e => {
			if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
			e.preventDefault();
			openDetail(imdb_id, true, titleHint, focus);
		});
	}

	// showDetails: the credit's details (a character name, a source credit's wording) behind each name
	// "S01E05" (with the given text before/after it) -- nothing for an episode IMDb gives no number
	function episodeCode(season, episode, before = '', after = '') {
		if (season === null || episode === null) return '';
		return before + 'S' + String(season).padStart(2, '0') + 'E' + String(episode).padStart(2, '0') + after;
	}

	function nameList(people, showDetails) {
		const wrap = makeEl('span', 'detailNames');
		people.forEach(p => {
			const span = makeEl('span');
			// with a person filter set, that person's credits on this title stand out (see collapsibleList for the rest)
			if (currentPerson && p.personId === currentPerson.id) span.classList.add('personHit');
			// a plain click shows the person's titles in the library; ctrl/cmd/middle-click follows the link to IMDb
			const link = makeEl('a', 'personLink', p.name);
			link.href = 'https://www.imdb.com/name/nm' + String(p.personId).padStart(7, '0') + '/';
			const tooltip = [];
			if (p.birthYear) tooltip.push('b. ' + p.birthYear + (p.deathYear ? ', d. ' + p.deathYear : ''));
			tooltip.push(countText(p.titleCount, 'title') + ' in the library');
			link.title = tooltip.join(' \u00B7 ');
			link.addEventListener('click', e => {
				if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
				e.preventDefault();
				showTitlesOfPerson(p.personId);
			});
			span.appendChild(link);
			if (showDetails && p.details) span.appendChild(makeEl('span', 'muted', ' (' + p.details + ')'));
			wrap.appendChild(span);
		});
		return wrap;
	}

	function countText(n, noun) {
		return n + ' ' + noun + (n === 1 ? '' : 's');
	}

	// the first VISIBLE_CAST_COUNT people, the rest behind a "+ N more" button
	function collapsibleList(people, showDetails) {
		// one wrapping list for all of them (the extra names merely hidden, the button standing in their place), so
		// that expanding continues the same line instead of starting a new block below it
		const wrap = nameList(people, showDetails);
		if (people.length > VISIBLE_CAST_COUNT) {
			const rest = [...wrap.children].slice(VISIBLE_CAST_COUNT);
			// a list that has the filtered person among the collapsed names opens expanded, so they are in sight
			if (!rest.some(el => el.classList.contains('personHit'))) {
				rest.forEach(el => { el.style.display = 'none'; });
				const more = makeEl('button', 'detailMore', '+ ' + rest.length + ' more');
				more.type = 'button';
				more.addEventListener('click', () => {
					rest.forEach(el => { el.style.display = ''; });
					more.remove();
				});
				wrap.insertBefore(more, rest[0]);
			}
		}
		return wrap;
	}

	// A series' seasons as tiles: "owned/total" episodes, all owned (green), some (progress bar) or none (dimmed).
	// The first VISIBLE_SEASON_COUNT numbered seasons show at once, the rest sit behind a "+ N more" tile; the
	// episodes without a season number get a last tile of their own.
	// focus ({season, episode}, optional): returns a reveal() to call once the section is on screen, which brings that
	// episode's season into view -- the "+ N more" tile expanded if the season sits behind it, a partly owned season
	// opened with the episode's row marked, a fully owned season's tile marked
	function seasonsSection(seasons, focus) {
		const section = document.createDocumentFragment();
		const owned = seasons.reduce((sum, s) => sum + s.owned, 0);
		const total = seasons.reduce((sum, s) => sum + s.total, 0);
		const heading = makeEl('h3', '', 'Seasons');
		heading.appendChild(makeEl('span', 'seasonsSummary', owned + ' of ' + total + ' episodes available'));
		section.appendChild(heading);

		// a partly owned season's tile opens a list of the episodes that are owned, below the tiles
		const episodes = makeEl('div', 'seasonEpisodes');
		episodes.hidden = true;
		let openTile = null;

		function toggleEpisodes(el, s) {
			const wasOpen = openTile === el;
			if (openTile) {
				openTile.classList.remove('open');
				openTile.setAttribute('aria-expanded', 'false');
				openTile.querySelector('.seasonChevron').textContent = '▾';
				openTile = null;
			}
			episodes.hidden = true;
			if (wasOpen) return;
			episodes.replaceChildren();
			s.ownedEpisodes.forEach(e => {
				const row = makeEl('div', 'seasonEpisode');
				row.dataset.episode = e.number === null ? '' : String(e.number);
				row.appendChild(makeEl('span', 'seasonEpisodeNumber', e.number === null ? '' : 'E' + e.number));
				// the episode's IMDb page (an episode has no page of its own here)
				const link = makeEl('a', 'seasonEpisodeLink', e.title);
				link.href = 'https://www.imdb.com/title/' + idString(e.imdbId) + '/';
				link.title = 'open on IMDb';
				link.target = '_blank';
				link.rel = 'noopener noreferrer';
				link.appendChild(makeEl('span', 'seasonEpisodeArrow', ' \u2197'));
				row.appendChild(link);
				episodes.appendChild(row);
			});
			el.classList.add('open');
			el.setAttribute('aria-expanded', 'true');
			el.querySelector('.seasonChevron').textContent = '▴';
			episodes.hidden = false;
			openTile = el;
		}

		const tileOf = new Map(); // season number (null: unnumbered) -> {el, s}

		function tile(s) {
			const state = s.owned === s.total ? 'full' : s.owned === 0 ? 'none' : 'part';
			const el = makeEl(state === 'part' ? 'button' : 'div', 'seasonTile seasonTile--' + state);
			el.title = s.owned + ' of ' + s.total + ' episodes available';
			el.appendChild(makeEl('span', 'seasonLabel', s.season === null ? 'Unnumbered' : s.season === 0 ? 'Specials' : 'Season ' + s.season));
			el.appendChild(makeEl('span', 'seasonCount', s.owned + '/' + s.total));
			// the year(s) the season came out: its first to its last episode's
			el.appendChild(makeEl('span', 'seasonYears', s.firstYear === s.lastYear ? String(s.firstYear) : s.firstYear + '\u2013' + s.lastYear));
			if (state === 'part') {
				const bar = makeEl('span', 'seasonBar');
				bar.appendChild(makeEl('span', 'seasonBarFill'));
				bar.firstChild.style.width = Math.round(100 * s.owned / s.total) + '%';
				el.appendChild(bar);
				if (s.ownedEpisodes) {
					el.type = 'button';
					el.setAttribute('aria-expanded', 'false');
					el.appendChild(makeEl('span', 'seasonChevron', '▾'));
					el.addEventListener('click', () => toggleEpisodes(el, s));
				}
			}
			tileOf.set(s.season, { el, s });
			return el;
		}

		const grid = makeEl('div', 'seasonGrid');
		const numbered = seasons.filter(s => s.season !== null);
		const unnumbered = seasons.filter(s => s.season === null);
		const hiddenTiles = [];
		numbered.forEach((s, i) => {
			const el = tile(s);
			if (i >= VISIBLE_SEASON_COUNT) {
				el.style.display = 'none';
				hiddenTiles.push(el);
			}
			grid.appendChild(el);
		});
		let moreTile = null;
		function expandAll() {
			hiddenTiles.forEach(el => { el.style.display = ''; });
			if (moreTile) moreTile.remove();
			moreTile = null;
		}
		if (hiddenTiles.length) {
			moreTile = makeEl('button', 'seasonTile seasonTile--none seasonMore', '');
			moreTile.type = 'button';
			moreTile.appendChild(makeEl('span', 'seasonLabel', '…'));
			moreTile.appendChild(makeEl('span', 'seasonCount', '+ ' + hiddenTiles.length + ' more'));
			moreTile.addEventListener('click', expandAll);
			grid.appendChild(moreTile);
		}
		unnumbered.forEach(s => grid.appendChild(tile(s)));
		const block = makeEl('div', 'seasonsBlock');
		block.appendChild(grid);
		block.appendChild(episodes);
		section.appendChild(block);

		function reveal() {
			const found = focus && tileOf.get(focus.season);
			if (!found) return;
			expandAll();
			found.el.classList.add('seasonTile--focus');
			let target = found.el;
			if (found.s.ownedEpisodes) {
				if (openTile !== found.el) toggleEpisodes(found.el, found.s);
				const row = [...episodes.children].find(r => r.dataset.episode === String(focus.episode));
				if (row) {
					row.classList.add('seasonEpisode--focus');
					target = row;
				}
			}
			target.scrollIntoView({ block: 'center' });
		}

		return { section, reveal };
	}

	function renderDetail(d, focus = null) {
		let reveal = null; // see seasonsSection
		detailTitle.textContent = d.title;

		const rating = d.rating ? d.rating.toFixed(1) : '—';
		const votes = d.votes ? formatNumVotes(d.votes) : '—';
		let meta = (TITLE_TYPE_LABELS[d.titleType] ? TITLE_TYPE_LABELS[d.titleType] + ' · ' : '') +
			formatYearRange(d.startYear, d.endYear, d.isSeries) + ' · ★ ' + rating + ' (' + votes + ' votes)';
		if (d.primaryTitle && d.primaryTitle !== d.title) meta += ' · also known as ' + d.primaryTitle;
		detailMeta.textContent = meta;

		detailChips.replaceChildren();
		// a genre/subgenre chip shows the titles with it (see showTitlesOfInterest)
		d.interests.forEach(i => {
			const chip = makeEl('a', 'detailChip' + (i.isGenre ? ' detailChip--genre' : ''), i.name);
			chip.href = '#';
			chip.title = 'show the titles with ' + i.name;
			chip.addEventListener('click', e => {
				e.preventDefault();
				showTitlesOfInterest(i.id);
			});
			detailChips.appendChild(chip);
		});
		const imdbLink = makeEl('a', 'imdbLink', 'IMDb ↗');
		imdbLink.href = 'https://www.imdb.com/title/' + idString(d.imdbId) + '/';
		imdbLink.target = '_blank';
		imdbLink.rel = 'noopener noreferrer';
		detailChips.appendChild(imdbLink);

		detailBody.replaceChildren();
		if (d.plotSummary) detailBody.appendChild(makeEl('p', 'plot', d.plotSummary));

		// the primary language (only that one: IMDb's further spoken languages are no help here) and the production
		// countries, the first one first
		const facts = [[d.languages.slice(0, 1), 'Language', 'Languages'], [d.countries, 'Country', 'Countries']].filter(([names]) => names.length);
		if (facts.length) {
			const grid = makeEl('div', 'detailGrid');
			facts.forEach(([names, singular, plural]) => {
				grid.appendChild(makeEl('span', 'label', names.length === 1 ? singular : plural));
				grid.appendChild(makeEl('span', '', names.join(' · '))); // not commas: ISO names have some ("Korea, Republic of")
			});
			detailBody.appendChild(grid);
		}

		if (d.isSeries && d.seasons.length) {
			const seasons = seasonsSection(d.seasons, focus);
			detailBody.appendChild(seasons.section);
			reveal = focus ? seasons.reveal : null;
		}

		if (d.creators.length || d.directors.length || d.writers.length || d.sources.length || d.actors.length) {
			detailBody.appendChild(makeEl('h3', '', 'Cast & crew'));
			// a series' lists are compiled from its episodes, ranked, and can get long: all of them collapse;
			// the note is only there when episodes are missing, i.e. when the lists are based on part of the series
			if (d.isSeries && !d.allEpisodesOwned) detailBody.appendChild(makeEl('div', 'detailNote', 'Compiled from the available episodes'));
			const crewList = people => d.isSeries ? collapsibleList(people, false) : nameList(people, false);
			const grid = makeEl('div', 'detailGrid');
			[['Created by', d.creators, crewList],
			 ['Directed by', d.directors, crewList],
			 ['Written by', d.writers, crewList],
			 // the source material's authors, each with their credit ("based on the novel")
			 ['Based on', d.sources, people => d.isSeries ? collapsibleList(people, true) : nameList(people, true)],
			 ['Cast', d.actors, people => collapsibleList(people, true)]].forEach(([label, people, render]) => {
				if (!people.length) return;
				grid.appendChild(makeEl('span', 'label', label));
				grid.appendChild(render(people));
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
					const text = makeEl('span');
					const link = makeEl('a', '', t.title + (t.year ? ' (' + t.year + ')' : ''));
					if (t.owned && t.seriesId) {
						// an episode has no overlay of its own: open its series, on that episode
						link.href = '#' + idString(t.seriesId);
						link.title = 'in the library -- open the series';
						attachDetailOpen(link, t.seriesId, t.seriesTitle, { season: t.season, episode: t.episode });
					} else if (t.owned) {
						link.href = '#' + idString(t.imdbId);
						link.title = 'in the library -- open';
						attachDetailOpen(link, t.imdbId, t.title);
					} else {
						link.href = 'https://www.imdb.com/title/' + idString(t.imdbId) + '/';
						link.title = 'not in the library -- open on IMDb';
						link.target = '_blank';
						link.rel = 'noopener noreferrer';
					}
					text.appendChild(link);
					// a target that is an episode: where it sits, e.g. " – Disneyland S28E19"
					if (t.seriesTitle) {
						text.appendChild(makeEl('span', 'connNote', ' – ' + t.seriesTitle + episodeCode(t.season, t.episode, ' ')));
					}
					// a series' connection that comes from its episodes: the first two of them, all in the hover text
					if (t.origins.length) {
						const label = o => episodeCode(o.season, o.episode, '', ' ') + o.title;
						const note = makeEl('span', 'connNote', ' · ' + t.origins.slice(0, 2).map(label).join(', '));
						note.title = t.origins.map(label).join('\n');
						text.appendChild(note);
					}
					row.appendChild(text);
					cell.appendChild(row);
				});
				grid.appendChild(cell);
			});
			detailBody.appendChild(grid);
		}

		detailBody.scrollTop = 0;

		// a series opened on an episode: reveal it now if the overlay is on screen (scrolling needs that), else as it opens
		if (reveal) {
			if (detailBackdrop.classList.contains('hidden')) {
				pendingReveal = reveal;
			} else {
				reveal();
			}
		}

		detailCover.alt = d.title; // the cover itself was started by showDetailLoading, long before the details arrived
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
		detailCover.classList.add('revealed');
		detailCoverPane.classList.remove('coverLoading');
		applyCoverTint(detailCoverId);
	});
	detailCover.addEventListener('error', () => {
		detailCover.classList.remove('loading');
		detailCover.classList.add('noCover');
		detailCoverPane.classList.remove('coverLoading');
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

	// what to do once the overlay is on screen and its content is there (scrolling needs a visible overlay): a
	// series opened on an episode reveals it, see seasonsSection -- set by renderDetail when it ran before the overlay opened
	let pendingReveal = null;

	function showDetailShell() {
		detailBackdrop.classList.remove('hidden');
		document.body.style.overflow = 'hidden';
		document.getElementById('detailClose').focus();
		if (pendingReveal) {
			const reveal = pendingReveal;
			pendingReveal = null;
			reveal();
		}
	}

	function hideDetail() {
		detailRequestId++; // anything still loading must not pop the overlay back open
		closeCoverLightbox();
		detailBackdrop.classList.add('hidden');
		document.body.style.overflow = '';
	}

	// What the overlay shows for a title whose details are still on their way: its title if the click knew it, a
	// "Loading..." note (it only fades in after a moment, so a quick response never flashes it) and the cover, which
	// starts loading right now instead of once the details are in -- until it arrives, a shimmer takes its place.
	function showDetailLoading(imdb_id, titleHint) {
		detailTitle.textContent = titleHint;
		detailMeta.textContent = '';
		detailChips.replaceChildren();
		detailBody.replaceChildren(makeEl('div', 'detailLoading', 'Loading\u2026'));
		detailBody.scrollTop = 0;

		const coverUrl = '/cover/' + idString(imdb_id) + '.jpg';
		const sameCover = detailCover.getAttribute('src') === coverUrl;
		detailCoverId = imdb_id;
		detailCover.alt = titleHint;
		detailCover.classList.remove('noCover', 'revealed');
		if (sameCover && detailCover.complete && detailCover.naturalWidth > 0) {
			detailCoverPane.classList.remove('coverLoading');
			applyCoverTint(imdb_id); // same cover already loaded (title reopened) -- no load event will fire
		} else {
			detailCover.classList.add('loading'); // the previous title's poster must not linger meanwhile
			detailCoverPane.classList.add('coverLoading');
			if (!sameCover || detailCover.complete) detailCover.src = coverUrl; // same cover still loading: leave it be
		}
	}

	function openDetail(imdb_id, pushHistory = true, titleHint = '', focus = null) {
		const requestId = ++detailRequestId;
		pendingReveal = null;
		const wasOpen = !detailBackdrop.classList.contains('hidden');
		new Image().src = '/cover/' + idString(imdb_id) + '.jpg'; // preload alongside the details request
		const tintReady = tintFromThumbnail(imdb_id); // likewise, see tintFromThumbnail
		showDetailLoading(imdb_id, titleHint);

		// The overlay opens at once, not when the details are in: it only waits a moment (120 ms at most) for the
		// thumbnail's tint, normally cached already, so that it opens in its final colour.
		Promise.race([tintReady, new Promise(resolve => setTimeout(resolve, 120))]).then(tint => {
			if (requestId !== detailRequestId) return; // superseded by a newer click, or closed meanwhile
			// if the thumbnail couldn't be read (undefined), start neutral rather than on the previous title's colour
			// -- the full cover's load event applies the real one (unless that has happened already)
			if (tint !== undefined) setCoverTint(tint);
			else if (detailCoverPane.classList.contains('coverLoading')) setCoverTint(null);
			showDetailShell();
			if (pushHistory) {
				const url = '#' + idString(imdb_id);
				if (wasOpen) history.replaceState({ detail: imdb_id }, '', url);
				else history.pushState({ detail: imdb_id }, '', url);
			}
		});

		fetch('/detail/' + imdb_id)
			.then(response => {
				if (!response.ok) {
					const err = new Error('detail request failed with status ' + response.status);
					err.status = response.status;
					throw err;
				}
				return response.json();
			})
			.then(d => {
				if (requestId !== detailRequestId) return; // superseded by a newer click, or closed meanwhile
				if (d.episodeOf) {
					// an episode has no overlay of its own (a link or history entry from before): open its series on it
					// instead, and make the address say so. Only a history entry that already is an overlay one stays one.
					const e = d.episodeOf;
					history.replaceState(history.state && history.state.detail ? { detail: e.seriesId } : null, '', '#' + idString(e.seriesId));
					openDetail(e.seriesId, false, '', { season: e.season, episode: e.episode });
					return;
				}
				renderDetail(d, focus);
			})
			.catch(err => {
				if (requestId !== detailRequestId) return;
				detailTitle.textContent = "Couldn't load details";
				detailMeta.textContent = '';
				detailChips.replaceChildren();
				detailBody.replaceChildren(makeEl('div', 'detailError', err.status === 404
					? "This title isn't in the library."
					: 'The database may be temporarily busy -- close this and try again in a moment.'));
				detailCover.classList.add('noCover');
				detailCoverPane.classList.remove('coverLoading');
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

	// the "x" button inside a field (see .search-field in index.html): visible while the field has content
	// (a half-typed number counts, though its value is still empty), clears it and then runs onCleared
	const clearButtonUpdaters = [];
	function setupClearButton(field, onCleared) {
		const button = field.parentElement.querySelector('.search-field-clear');
		const update = () => button.classList.toggle('visible', field.value.length > 0 || field.validity.badInput);
		field.addEventListener('input', update);
		button.addEventListener('click', () => {
			field.value = '';
			update();
			field.focus();
			onCleared();
		});
		clearButtonUpdaters.push(update);
	}

	function refreshClearButtons() {
		clearButtonUpdaters.forEach(update => update());
	}

	// ---- person filter

	// filters the list by a person (and shows the sidebar's chip with the kinds of credit the person has, all ticked)
	function setPerson(personId) {
		fetch('/person/' + personId)
			.then(response => {
				if (!response.ok) throw new Error('person request failed with status ' + response.status);
				return response.json();
			})
			.then(p => {
				currentPerson = p;
				personChipName.textContent = p.name;
				personChipName.title = (p.birthYear ? 'b. ' + p.birthYear + (p.deathYear ? ', d. ' + p.deathYear : '') + ' \u00B7 ' : '') +
					countText(p.titles, 'title') + ' in the library';
				personRoleCheckboxes.forEach(cb => {
					const count = p.roles[cb.value];
					const label = cb.closest('label');
					label.querySelector('.roleCount').textContent = count;
					cb.disabled = count === 0; // a kind the person has no credit of can't be ticked
					cb.checked = count > 0;
					label.classList.toggle('disabled', count === 0);
				});
				personFilterEl.hidden = false;
				if (sidebarCollapsed) toggleBtn.click(); // the chip must be visible
				resetAndSearch();
			})
			.catch(err => {
				console.error(err);
				errorBanner.classList.remove('hidden');
			});
	}

	function clearPerson() {
		currentPerson = null;
		personFilterEl.hidden = true;
		resetAndSearch();
	}

	// a name was clicked in a title's cast & crew: close the overlay and show that person's titles
	// all other filters are reset first: the person's titles are what's wanted, not those that also match what happened
	// to be set (setPerson runs the search)
	function showTitlesOfPerson(personId) {
		closeDetail();
		clearOtherFilters();
		setPerson(personId);
	}

	document.getElementById('personChipClear').addEventListener('click', clearPerson);
	personRoleCheckboxes.forEach(cb => cb.addEventListener('change', () => resetAndSearch()));

	// name search: suggestions drop down while typing (two characters on), the arrow keys and Enter pick one
	let personSearchTimer = null;
	let personSearchId = 0;
	let activeSuggestion = -1;

	function hideSuggestions() {
		clearTimeout(personSearchTimer);
		personSearchId++; // a response still on its way must not reopen the list
		personSuggestions.hidden = true;
		personSuggestions.replaceChildren();
		activeSuggestion = -1;
	}

	function chooseSuggestion(person) {
		hideSuggestions();
		personInput.value = '';
		refreshClearButtons();
		setPerson(person.id);
	}

	function showSuggestions(people) {
		personSuggestions.replaceChildren();
		activeSuggestion = -1;
		if (!people.length) {
			personSuggestions.appendChild(makeEl('div', 'empty', 'No matching people'));
		}
		people.forEach(person => {
			const item = makeEl('button', '', person.name);
			item.type = 'button';
			item.appendChild(makeEl('span', 'muted', ' ' + (person.birthYear ? '(b. ' + person.birthYear + ') ' : '') + '\u00B7 ' + countText(person.titles, 'title')));
			item.addEventListener('mousedown', e => e.preventDefault()); // keeps the field focused until the click lands
			item.addEventListener('click', () => chooseSuggestion(person));
			item.suggestion = person;
			personSuggestions.appendChild(item);
		});
		personSuggestions.hidden = false;
	}

	function moveSuggestion(step) {
		const items = [...personSuggestions.querySelectorAll('button')];
		if (!items.length) return;
		if (items[activeSuggestion]) items[activeSuggestion].classList.remove('active');
		activeSuggestion = (activeSuggestion + step + items.length) % items.length;
		items[activeSuggestion].classList.add('active');
	}

	personInput.addEventListener('input', () => {
		clearTimeout(personSearchTimer);
		const q = personInput.value.trim();
		if (q.length < 2) {
			hideSuggestions();
			return;
		}
		personSearchTimer = setTimeout(() => {
			const thisSearch = ++personSearchId;
			fetch('/people?q=' + encodeURIComponent(q))
				.then(response => response.ok ? response.json() : Promise.reject(new Error('status ' + response.status)))
				.then(people => {
					if (thisSearch === personSearchId) showSuggestions(people);
				})
				.catch(() => {
					if (thisSearch === personSearchId) hideSuggestions();
				});
		}, 180);
	});

	personInput.addEventListener('keydown', e => {
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			moveSuggestion(1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			moveSuggestion(-1);
		} else if (e.key === 'Enter') {
			const items = [...personSuggestions.querySelectorAll('button')];
			const pick = items[activeSuggestion] || items[0];
			if (pick) {
				e.preventDefault();
				chooseSuggestion(pick.suggestion);
			}
		} else if (e.key === 'Escape' && !personSuggestions.hidden) {
			e.stopPropagation();
			hideSuggestions();
		}
	});

	personInput.addEventListener('blur', () => setTimeout(hideSuggestions, 150));

	// every filter but the person's back to its default (title search, type, years/rating/votes, language, genres and
	// subgenres incl. NOT ones) -- the sort order and the view stay as they are
	function clearOtherFilters() {
		input.value = '';

		yearFrom.value = '';
		yearTo.value = '';
		ratingFrom.value = '';
		ratingTo.value = '';
		votesFrom.value = '';
		votesTo.value = '';

		moviesCheckbox.checked = true;
		seriesCheckbox.checked = true;
		updateSeriesOptions();

		document.querySelector('.languageRadio[value=""]').checked = true;

		genreCheckboxes.forEach(cb => cb.checked = false);
		interestCheckboxes.forEach(cb => cb.checked = false);
		document.querySelectorAll('label.excluded').forEach(label => label.classList.remove('excluded'));
		interestSearchInput.value = '';
		filterInterests();
		refreshClearButtons();
	}

	// every filter back to its default, the person's included -- the sort order and the view stay as they are
	function clearAllFilters() {
		currentPerson = null;
		personFilterEl.hidden = true;
		personInput.value = '';
		hideSuggestions();
		clearOtherFilters();
	}

	// a genre/subgenre chip was clicked in a title's overview: close the overlay and show the titles with that genre
	// (or subgenre) -- all other filters are reset first, as when a person's name is clicked
	function showTitlesOfInterest(interestId) {
		closeDetail();
		clearAllFilters();
		const checkbox = document.querySelector('.genreCheckbox[value="' + interestId + '"], .interestCheckbox[value="' + interestId + '"]');
		if (checkbox) {
			checkbox.checked = true;
			if (sidebarCollapsed) toggleBtn.click(); // the ticked box must be visible
			checkbox.scrollIntoView({ block: 'nearest' });
		}
		resetAndSearch();
	}

	function resetFilters() {
		clearAllFilters();

		sortSelect.value = 'year';
		orderButton.disabled = false;

		currentOrder = 'desc';
		orderButton.textContent = '↓ Descending';

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
			series_mini: seriesMiniCheckbox.checked ? '1' : '0',
			series_not_mini: seriesMiniCheckbox.closest('label').classList.contains('excluded') ? '1' : '0',
			series_ended: seriesEndedCheckbox.checked ? '1' : '0',
			series_full: seriesFullCheckbox.checked ? '1' : '0',
			series_not_ended: seriesEndedCheckbox.closest('label').classList.contains('excluded') ? '1' : '0',
			series_not_full: seriesFullCheckbox.closest('label').classList.contains('excluded') ? '1' : '0',
			page: currentPage
        });

		if (currentPerson) {
			params.set('person', currentPerson.id);
			params.set('person_roles', personRoleCheckboxes.filter(cb => cb.checked).map(cb => cb.value).join(','));
		}

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

		// excluded (NOT) options -- see the long-press/right-click setup near the checkbox listeners
		genreCheckboxes.forEach(cb => {
			if (cb.closest('label').classList.contains('excluded')) {
				params.append('notGenres[]', cb.value);
			}
		});

		interestCheckboxes.forEach(cb => {
			if (cb.closest('label').classList.contains('excluded')) {
				params.append('notInterests[]', cb.value);
			}
		});

		let totalCount = null; // only sent with the first page (see server.py's search)
        fetch(`/search?${params.toString()}`, { signal: thisSearchController.signal })
            .then(response => {
                if (!response.ok) {
                    throw new Error('search request failed with status ' + response.status);
                }
                totalCount = response.headers.get('X-Total-Count');
                return response.json();
            })
            .then(data => {
				errorBanner.classList.add('hidden');
				if (totalCount !== null) {
					const total = Number(totalCount);
					resultCount.textContent = total.toLocaleString() + (total === 1 ? ' title' : ' titles');
				}

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
						// the placeholder shimmer (see .coverImage in index.html) ends when the image arrives or fails; the
						// listeners come before src is set, so even an instantly-cached cover can't slip past them
						img.addEventListener('load', () => img.classList.add('loaded'));
						img.addEventListener('error', () => img.classList.add('failed'));
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
						attachDetailOpen(linkElem, imdb_id, originalTitle);
						
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
							attachDetailOpen(img, imdb_id, originalTitle);
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

    input.addEventListener('input', () => debounceSearch(input.value));

	setupClearButton(input, () => resetAndSearch(input.value));
	[yearFrom, yearTo, ratingFrom, ratingTo, votesFrom, votesTo].forEach(el => setupClearButton(el, () => resetAndSearch(input.value)));
	setupClearButton(interestSearchInput, filterInterests);
	setupClearButton(personInput, hideSuggestions);

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
	seriesCheckbox.addEventListener('change', () => {
		updateSeriesOptions();
		resetAndSearch(input.value);
	});
	seriesMiniCheckbox.addEventListener('change', () => resetAndSearch(input.value));
	seriesEndedCheckbox.addEventListener('change', () => resetAndSearch(input.value));
	seriesFullCheckbox.addEventListener('change', () => resetAndSearch(input.value));

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

	// NOT filter for genres/subgenres (and the two series options): right-click (mouse) or long-press (touch) toggles an option
	// into/out of "excluded" -- shown red, sent as notGenres[]/notInterests[], and mutually exclusive
	// with being checked (included). Each button flips the other state directly: a left click takes an
	// excluded option straight to included, and a right-click/long-press takes an included one
	// straight to excluded (either also toggles its own state off again). Touch needs its own timer: iOS Safari never fires contextmenu on
	// a long-press, and Android Chrome fires it AFTER the press, so the timer is the one source of
	// truth for touch and contextmenu is only acted on for a mouse.
	const LONG_PRESS_MS = 500;
	const LONG_PRESS_MOVE_TOLERANCE = 10; // px of finger drift before it counts as a scroll, not a press
	let suppressClickLabel = null; // the label whose long-press just fired: its releasing tap must not also toggle include

	function toggleExcluded(cb) {
		if (cb.disabled) return; // the series options while Series is unticked
		const label = cb.closest('label');
		const nowExcluded = !label.classList.contains('excluded');
		label.classList.toggle('excluded', nowExcluded);
		if (nowExcluded) cb.checked = false;
		resetAndSearch(input.value);
	}

	[...genreCheckboxes, ...interestCheckboxes, seriesMiniCheckbox, seriesEndedCheckbox, seriesFullCheckbox].forEach(cb => {
		const label = cb.closest('label');
		let lastPointerType = 'mouse';
		let pressTimer = null;
		let pressStartX = 0;
		let pressStartY = 0;

		const cancelPress = () => {
			clearTimeout(pressTimer);
			pressTimer = null;
		};

		label.addEventListener('pointerdown', e => {
			lastPointerType = e.pointerType;
			if (e.pointerType !== 'touch') return;
			pressStartX = e.clientX;
			pressStartY = e.clientY;
			cancelPress();
			pressTimer = setTimeout(() => {
				pressTimer = null;
				suppressClickLabel = label;
				setTimeout(() => { if (suppressClickLabel === label) suppressClickLabel = null; }, 1000);
				toggleExcluded(cb);
			}, LONG_PRESS_MS);
		});

		label.addEventListener('pointermove', e => {
			if (pressTimer !== null && Math.hypot(e.clientX - pressStartX, e.clientY - pressStartY) > LONG_PRESS_MOVE_TOLERANCE) {
				cancelPress();
			}
		});

		['pointerup', 'pointercancel', 'pointerleave'].forEach(type => label.addEventListener(type, cancelPress));

		label.addEventListener('contextmenu', e => {
			e.preventDefault();
			if (lastPointerType === 'touch') return; // the long-press timer above already handled it
			toggleExcluded(cb);
		});

		// capture phase, so a click aimed straight at the checkbox itself is caught too
		label.addEventListener('click', e => {
			if (suppressClickLabel === label) {
				// preventing the click stops the label/checkbox from toggling, so no change event follows
				e.preventDefault();
				e.stopPropagation();
				suppressClickLabel = null;
			} else if (label.classList.contains('excluded')) {
				// excluded -> included in one click, the mirror of right-clicking an included option:
				// dropping the class is all that's needed, since the click itself then checks the
				// (unchecked) box and its change listener runs the search
				label.classList.remove('excluded');
			}
		}, true);
	});

	// Infinite scroll: the next chunk is fetched while the user is still PREFETCH_SCREENS screen heights
	// away from the end of the list, so it's already in place by the time they get there. (It used to
	// be a fixed 300px, i.e. less than one row of covers: fast scrolling reached the end of the chunk
	// before the next one had been fetched, appended and its covers loaded.) A chunk is ~50 covers (~2.5 MB
	// of thumbnails), a few screens tall in a wide window; its covers start loading as soon as it is
	// appended. Four screens of lookahead means the covers are normally there before they scroll into view
	// even over a slow connection, at the price of loading at most about a chunk more than has been seen.
	const PREFETCH_SCREENS = 4;

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
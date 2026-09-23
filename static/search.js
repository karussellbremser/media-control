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
		if (detailCover.getAttribute('src') !== coverUrl || !detailCover.complete) {
			detailCover.classList.add('loading'); // the previous title's poster must not linger meanwhile
			detailCover.src = coverUrl;
		}
	}

	detailCover.addEventListener('load', () => detailCover.classList.remove('loading'));
	detailCover.addEventListener('error', () => {
		detailCover.classList.remove('loading');
		detailCover.classList.add('noCover');
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
						img.loading = "lazy";
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
                }

				isLoading = false;
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

	window.addEventListener('scroll', () => {
		if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 300) {
			fetchResults(input.value, true);
		}
	});
	
	// initially: show everything, via resetFilters() rather than fetchResults('') directly -- this
	// also forces every filter control back to its default, undoing whatever the browser may have
	// restored into them on this reload (see the scrollRestoration comment above)
    resetFilters();
	if (/^#tt\d+$/.test(location.hash)) syncDetailWithHash(); // a linked/reloaded title opens straight away
});
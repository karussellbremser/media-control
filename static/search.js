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

		// Pfeil ändern
		toggleBtn.textContent = sidebarCollapsed ? '>>' : '<<';
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
		if (isLoading || allLoaded) return;

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

        fetch(`/search?${params.toString()}`)
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

							if (isPartialSeries) {
								const badge = document.createElement('span');
								badge.classList.add("ownershipBadge");
								badge.textContent = `${ownedEpisodes} / ${totalEpisodes}`;
								titleElem.appendChild(badge);
							}

							const wrapper = document.createElement('div');
							wrapper.classList.add("resultItem");

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

							if (isPartialSeries) {
								const badge = document.createElement('span');
								badge.classList.add("ownershipBadge", "ownershipBadge--grid");
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
			.catch(() => {
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
});
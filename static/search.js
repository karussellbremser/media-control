document.addEventListener('DOMContentLoaded', () => {
	const resetButton = document.getElementById('resetButton');
	
    const input = document.getElementById('searchInput');
    const results = document.getElementById('results');
	const sortSelect = document.getElementById('sortSelect');
	const orderButton = document.getElementById('orderButton');
	
	const yearFrom = document.getElementById('yearFrom');
    const yearTo = document.getElementById('yearTo');
    const ratingFrom = document.getElementById('ratingFrom');
    const ratingTo = document.getElementById('ratingTo');
    const votesFrom = document.getElementById('votesFrom');
    const votesTo = document.getElementById('votesTo');
	
	const genreCheckboxes = document.querySelectorAll('.genreCheckbox');
	
	let viewMode = "list";

	const listViewBtn = document.getElementById('listViewBtn');
	const gridViewBtn = document.getElementById('gridViewBtn');
	listViewBtn.classList.add("activeView");

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

		genreCheckboxes.forEach(cb => cb.checked = false);

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
			page: currentPage
        });
		
		genreCheckboxes.forEach(cb => {
			if (cb.checked) {
				params.append('genres[]', cb.value);
			}
		});
		
        fetch(`/search?${params.toString()}`)
            .then(response => response.json())
            .then(data => {
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
                    data.forEach(([imdb_id, originalTitle, startYear, rating_mul10, numVotes, genres]) => {
						const img = document.createElement('img');

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
						const safeYear = startYear ?? '—';
						const safeRating = rating_mul10 ? (rating_mul10 / 10).toFixed(1) : '—';
						const safeVotes = numVotes ? formatNumVotes(numVotes) : '—';
                        ratingsElem.textContent = safeRating + " (" + safeVotes + " votes)";
						
						const genresElem = document.createElement('div');
						genresElem.textContent = `${genres ?? '—'}`;

						if (viewMode === "list") {
							linkElem.classList.add("titleLink");
							linkElem.textContent = originalTitle + " (" + safeYear + ")";
							titleElem.appendChild(linkElem);
							
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

							linkElem.appendChild(imgWrapper);
							gridItem.appendChild(linkElem);

							results.appendChild(gridItem);
						}
                    });
					
					currentPage++;
                }
				
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
	
    [yearFrom, yearTo, ratingFrom, ratingTo, votesFrom, votesTo].forEach(el => {
        el.addEventListener('input', () => debounceSearch(input.value));
    });
	
	genreCheckboxes.forEach(cb => {
		cb.addEventListener('change', () => resetAndSearch(input.value));
	});
	
	window.addEventListener('scroll', () => {
		if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 300) {
			fetchResults(input.value, true);
		}
	});
	
	// initially: show everything
    fetchResults('');
});
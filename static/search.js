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
			return Math.floor(num / 1000) + 'k';
		} else {
			return (num / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
		}
	}
	
	function resetFilters() {
		input.value = '';

		sortSelect.value = 'year';

		currentOrder = 'desc';
		orderButton.textContent = '↓';

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
				}
				
                if (data.length === 0) {
                    allLoaded = true;
                } else {
                    data.forEach(([originalTitle, startYear, rating_mul10, numVotes, genres]) => {
                        const titleElem = document.createElement('h2');
                        titleElem.textContent = originalTitle + " (" + startYear + ")";

                        const ratingsElem = document.createElement('div');
						const safeRating = rating_mul10 ? (rating_mul10 / 10).toFixed(1) : '—';
						const safeVotes = numVotes ? formatNumVotes(numVotes) : '—';
                        ratingsElem.textContent = safeRating + " (" + safeVotes + " votes)";
						
						const genresElem = document.createElement('div');
						genresElem.textContent = `${genres ?? '—'}`;

                        results.appendChild(titleElem);
                        results.appendChild(ratingsElem);
						results.appendChild(genresElem)
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
            orderButton.textContent = '↑ Asc';
        } else {
            currentOrder = 'desc';
            orderButton.textContent = '↓ Desc';
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
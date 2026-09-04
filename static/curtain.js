document.addEventListener("DOMContentLoaded", () => {
	const overlay = document.getElementById("curtainOverlay");
	if (!overlay) return;

	function openCurtain() {
		if (overlay.classList.contains("open")) return;
		overlay.classList.add("open");
		setTimeout(() => overlay.classList.add("finished"), 1200);
	}

	setTimeout(openCurtain, 300);
	overlay.addEventListener("click", openCurtain);
});

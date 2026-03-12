const categoryFilter = document.getElementById("categoryFilter");
const priorityFilter = document.getElementById("priorityFilter");
const cards = document.querySelectorAll(".issue-card");

function applyFilters() {
  const c = categoryFilter.value;
  const p = priorityFilter.value;

  cards.forEach(card => {
    const matchC = c === "all" || card.dataset.category === c;
    const matchP = p === "all" || card.dataset.priority === p;
    card.classList.toggle("hidden", !(matchC && matchP));
  });
}

function resetFilters() {
  categoryFilter.value = "all";
  priorityFilter.value = "all";
  applyFilters();
}

if (categoryFilter && priorityFilter) {
  categoryFilter.addEventListener("change", applyFilters);
  priorityFilter.addEventListener("change", applyFilters);
}

window.resetFilters = resetFilters;

document.addEventListener("DOMContentLoaded", () => {

  const searchInput = document.getElementById("issueSearch");
  const statusFilter = document.getElementById("statusFilter");
  const categoryFilter = document.getElementById("categoryFilter");

  const rows = document.querySelectorAll("tbody tr[data-issue-id]");
  const cards = document.querySelectorAll(".issue-card[data-issue-id]");
  const paginationInfo = document.getElementById("paginationInfo");
  const prevPageBtn = document.getElementById("prevPage");
  const nextPageBtn = document.getElementById("nextPage");
  const pageNumbers = document.getElementById("pageNumbers");

  if (!searchInput || !statusFilter || !categoryFilter || !paginationInfo || !prevPageBtn || !nextPageBtn || !pageNumbers) {
    return;
  }

  const perPage = 10;
  let currentPage = 1;

  const sortByIssueId = (elements) => {
    return elements.sort((a, b) => {
      const aId = (a.dataset.issueId || "").toUpperCase();
      const bId = (b.dataset.issueId || "").toUpperCase();
      const aNum = parseInt(aId.replace("ISSUE-", ""), 10);
      const bNum = parseInt(bId.replace("ISSUE-", ""), 10);
      if (!isNaN(aNum) && !isNaN(bNum)) {
        return aNum - bNum;
      }
      return aId.localeCompare(bId);
    });
  };

  const paginate = (elements) => {
    const total = elements.length;
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    currentPage = Math.min(currentPage, totalPages);

    const start = (currentPage - 1) * perPage;
    const end = start + perPage;

    elements.forEach((el, index) => {
      el.style.display = index >= start && index < end ? "" : "none";
    });

    paginationInfo.textContent = total
      ? `Showing ${start + 1}-${Math.min(end, total)} of ${total}`
      : "Showing 0-0 of 0";

    prevPageBtn.disabled = currentPage === 1;
    nextPageBtn.disabled = currentPage === totalPages;

    pageNumbers.innerHTML = "";
    const maxButtons = 5;
    const half = Math.floor(maxButtons / 2);
    let startPage = Math.max(1, currentPage - half);
    let endPage = Math.min(totalPages, startPage + maxButtons - 1);
    if (endPage - startPage < maxButtons - 1) {
      startPage = Math.max(1, endPage - maxButtons + 1);
    }

    for (let p = startPage; p <= endPage; p++) {
      const btn = document.createElement("button");
      btn.className = `px-3 py-2 rounded-xl text-xs font-semibold fx-page-btn ${p === currentPage ? "is-active" : ""}`;
      btn.textContent = p;
      btn.addEventListener("click", () => {
        currentPage = p;
        paginate(elements);
      });
      pageNumbers.appendChild(btn);
    }
  };

  function applyFilters() {
    const search = searchInput.value.toLowerCase();
    const status = statusFilter.value.toLowerCase();
    const category = categoryFilter.value.toLowerCase();

    const matches = (el) => {
      const matchesSearch =
        el.dataset.issueId.includes(search) ||
        el.dataset.title.includes(search) ||
        el.dataset.location.includes(search);

      const matchesStatus = !status || el.dataset.status === status;
      const matchesCategory = !category || el.dataset.category === category;

      return matchesSearch && matchesStatus && matchesCategory;
    };

    const visibleRows = sortByIssueId(Array.from(rows).filter(matches));
    const visibleCards = sortByIssueId(Array.from(cards).filter(matches));

    rows.forEach((el) => { el.style.display = "none"; });
    cards.forEach((el) => { el.style.display = "none"; });

    const isMobile = window.matchMedia("(max-width: 767px)").matches;
    const activeList = isMobile ? visibleCards : visibleRows;

    paginate(activeList);
  }

  searchInput.addEventListener("input", applyFilters);
  statusFilter.addEventListener("change", applyFilters);
  categoryFilter.addEventListener("change", applyFilters);

  prevPageBtn.addEventListener("click", () => {
    currentPage = Math.max(1, currentPage - 1);
    applyFilters();
  });
  nextPageBtn.addEventListener("click", () => {
    currentPage = currentPage + 1;
    applyFilters();
  });

  window.addEventListener("resize", () => {
    currentPage = 1;
    applyFilters();
  });

  applyFilters();
});

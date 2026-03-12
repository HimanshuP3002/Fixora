document.addEventListener("DOMContentLoaded", function () {
  const cards = document.querySelectorAll(".stat-card");
  cards.forEach(card => {
    const bar = card.querySelector(".progress-bar");
    if (!bar) return;
    const rawValue = parseInt(card.dataset.progress, 10) || 0;
    const percentage = Math.min(100, Math.max(0, rawValue));
    setTimeout(() => {
      bar.style.width = percentage + "%";
      bar.style.transition = "width 1.2s ease-in-out";
    }, 200);
  });

  const dashboardMapEl = document.getElementById("dashboardMap");
  if (!dashboardMapEl || !window.L) return;

  const map = L.map("dashboardMap", {
    center: [20.5937, 78.9629],
    zoom: 5,
    attributionControl: false
  });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19
  }).addTo(map);

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(pos => {
      map.setView([pos.coords.latitude, pos.coords.longitude], 14);
      L.marker([pos.coords.latitude, pos.coords.longitude]).addTo(map)
        .bindPopup("Your Current Location");
    });
  }
});

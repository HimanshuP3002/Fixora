document.addEventListener("DOMContentLoaded", function () {
  const mapEl = document.getElementById("map");
  if (!mapEl || !window.L) return;

  const map = L.map("map", { zoomControl: false })
    .setView([20.5937, 78.9629], 5);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors"
  }).addTo(map);

  const pulseIcon = L.divIcon({
    html: '<div class="pulse-marker"></div>',
    className: "",
    iconSize: [14, 14],
    iconAnchor: [7, 7]
  });

  L.marker([28.6139, 77.2090], { icon: pulseIcon }).addTo(map);

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(pos => {
      const lat = pos.coords.latitude;
      const lng = pos.coords.longitude;

      const latNode = document.getElementById("lat");
      const lngNode = document.getElementById("lng");
      if (latNode) latNode.innerText = lat.toFixed(5);
      if (lngNode) lngNode.innerText = lng.toFixed(5);

      L.marker([lat, lng], { icon: pulseIcon }).addTo(map);
      map.setView([lat, lng], 14);
    });
  }

  setTimeout(() => map.invalidateSize(), 200);
});

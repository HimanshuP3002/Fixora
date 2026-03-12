(function () {
  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
  }

  function getFestivalProfile(scene, symbol, festivalName) {
    const sceneKey = String(scene || "").toLowerCase();
    const symbolKey = String(symbol || "").toUpperCase();
    const nameKey = String(festivalName || "").toLowerCase();

    const sceneProfiles = {
      diya: { particleClass: "diya", colors: ["#f59e0b", "#fbbf24", "#f97316", "#fde68a"], countDesktop: 24, countMobile: 12 },
      color: { particleClass: "dot", colors: ["#ec4899", "#0ea5e9", "#f59e0b", "#8b5cf6", "#22c55e"], countDesktop: 36, countMobile: 18 },
      kite: { particleClass: "ribbon", colors: ["#38bdf8", "#6366f1", "#f97316", "#ef4444"], countDesktop: 22, countMobile: 11 },
      flag: { particleClass: "ribbon", colors: ["#f97316", "#ffffff", "#16a34a"], countDesktop: 26, countMobile: 12 },
      trident: { particleClass: "dot", colors: ["#6366f1", "#f43f5e", "#a78bfa"], countDesktop: 20, countMobile: 10 },
      moon: { particleClass: "lantern", colors: ["#f8fafc", "#fde68a", "#f59e0b"], countDesktop: 18, countMobile: 9 },
      flute: { particleClass: "feather", colors: ["#2563eb", "#16a34a", "#a855f7"], countDesktop: 20, countMobile: 10 },
      lotus: { particleClass: "petal", colors: ["#f472b6", "#fb7185", "#f59e0b"], countDesktop: 24, countMobile: 12 },
      arrow: { particleClass: "ribbon", colors: ["#f97316", "#ef4444", "#fbbf24"], countDesktop: 18, countMobile: 9 },
      flower: { particleClass: "petal", colors: ["#f472b6", "#fb7185", "#f59e0b", "#facc15"], countDesktop: 28, countMobile: 14 },
      wheel: { particleClass: "dot", colors: ["#2563eb", "#c026d3", "#f59e0b"], countDesktop: 22, countMobile: 10 },
      star: { particleClass: "snow", colors: ["#ffffff", "#dbeafe", "#fde68a"], countDesktop: 34, countMobile: 16 },
      sun: { particleClass: "shadow", colors: ["rgba(2,6,23,0.45)", "rgba(30,41,59,0.35)", "rgba(56,189,248,0.28)"], countDesktop: 16, countMobile: 8 },
    };

    if (sceneProfiles[sceneKey]) return sceneProfiles[sceneKey];
    if (symbolKey === "ECLIPSE" || nameKey.includes("grahan")) {
      return sceneProfiles.sun;
    }
    return { particleClass: "dot", colors: ["var(--festival-accent)", "#60a5fa", "#a78bfa"], countDesktop: 20, countMobile: 10 };
  }

  function createParticle(profile, compactMode) {
    const particle = document.createElement("span");
    particle.className = "festival-particle " + profile.particleClass;
    particle.style.setProperty("--x", (Math.random() * 100).toFixed(2) + "%");
    particle.style.setProperty("--size", (compactMode ? 8 : 10 + Math.random() * 16).toFixed(2) + "px");
    particle.style.setProperty("--dur", (compactMode ? 14 : 9 + Math.random() * 10).toFixed(2) + "s");
    particle.style.setProperty("--delay", (-1 * Math.random() * 12).toFixed(2) + "s");
    particle.style.setProperty("--drift", (Math.random() * 42 - 21).toFixed(2) + "px");
    particle.style.setProperty("--rot", (Math.random() * 38 - 19).toFixed(2) + "deg");
    particle.style.setProperty("--particle-color", pick(profile.colors));
    return particle;
  }

  function triggerSparkBurst(x, y, count) {
    for (let i = 0; i < count; i += 1) {
      const spark = document.createElement("span");
      spark.className = "festival-hover-spark";
      spark.style.left = x + "px";
      spark.style.top = y + "px";
      spark.style.setProperty("--dx", (Math.random() * 34 - 17).toFixed(2) + "px");
      spark.style.setProperty("--dy", (Math.random() * 30 - 24).toFixed(2) + "px");
      document.body.appendChild(spark);
      window.setTimeout(function () {
        spark.remove();
      }, 520);
    }
  }

  function bindInteractiveEffects(scene) {
    if (prefersReducedMotion()) return;

    if (scene === "diya") {
      document.addEventListener(
        "pointerenter",
        function (evt) {
          const target = evt.target && evt.target.closest
            ? evt.target.closest("button, a, .mi-action")
            : null;
          if (!target) return;
          const rect = target.getBoundingClientRect();
          triggerSparkBurst(rect.left + rect.width * 0.8, rect.top + rect.height * 0.2, 6);
        },
        true
      );
    }

    if (scene === "color") {
      document.addEventListener("click", function (evt) {
        const x = evt.clientX;
        const y = evt.clientY;
        triggerSparkBurst(x, y, 12);
      });
    }
  }

  function initFestivalParticles() {
    const body = document.body;
    const enabled = body && body.dataset && body.dataset.festivalEnabled === "1";
    if (!enabled || prefersReducedMotion()) return;

    const layer = document.getElementById("festival-particles-layer");
    if (!layer) return;
    if (layer.dataset.initialized === "1") return;
    layer.dataset.initialized = "1";

    const scene = String((body.dataset && body.dataset.festivalScene) || "").toLowerCase();
    const symbol = String((body.dataset && body.dataset.festivalSymbol) || "");
    const festivalName = String((body.dataset && body.dataset.festivalName) || "");
    const compactMode = window.innerWidth < 768;
    const profile = getFestivalProfile(scene, symbol, festivalName);
    const count = compactMode ? profile.countMobile : profile.countDesktop;
    const frag = document.createDocumentFragment();

    for (let i = 0; i < count; i += 1) {
      frag.appendChild(createParticle(profile, compactMode));
    }
    layer.appendChild(frag);
    bindInteractiveEffects(scene);
  }

  document.addEventListener("DOMContentLoaded", initFestivalParticles);
})();

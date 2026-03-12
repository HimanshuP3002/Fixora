document.addEventListener("DOMContentLoaded", () => {
  const buttons = document.querySelectorAll(".js-fullscreen");

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".rx-chart-card");
      if (!card) return;
      card.classList.toggle("rx-expanded");
      const icon = btn.querySelector(".material-symbols-rounded");
      if (icon) {
        icon.textContent = card.classList.contains("rx-expanded")
          ? "fullscreen_exit"
          : "fullscreen";
      }
    });
  });
});

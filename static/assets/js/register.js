function setupPasswordToggle(inputId, toggleId, iconId) {
  const toggleButton = document.getElementById(toggleId);
  const passwordInput = document.getElementById(inputId);
  const toggleIcon = document.getElementById(iconId);
  if (toggleButton && passwordInput && toggleIcon) {
    toggleButton.addEventListener("click", function () {
      const isPassword = passwordInput.getAttribute("type") === "password";
      passwordInput.setAttribute("type", isPassword ? "text" : "password");
      toggleIcon.textContent = isPassword ? "visibility" : "visibility_off";
    });
  }
}

setupPasswordToggle("pass", "togglePass", "togglePassIcon");
setupPasswordToggle("cpass", "toggleCPass", "toggleCPassIcon");

const nameInput = document.getElementById('name');
const userInput = document.getElementById('user');
const suggestionsBox = document.getElementById('username-suggestions');

if (nameInput && userInput && suggestionsBox) {
  nameInput.addEventListener('input', function () {
    const fullName = this.value.trim().toLowerCase();

    if (fullName.length < 3) {
      suggestionsBox.innerHTML = '<span class="text-xs text-gray-500 italic">Type full name to see suggestions...</span>';
      return;
    }

    const parts = fullName.split(' ').filter(p => p.length > 0);
    const rand = Math.floor(Math.random() * 900) + 100;
    let suggestions = [];

    if (parts.length >= 2) {
      const first = parts[0].replace(/[^a-z0-9]/g, '');
      const last = parts[parts.length - 1].replace(/[^a-z0-9]/g, '');
      suggestions.push(`${first}.${last}`);
      suggestions.push(`${first}${last}${rand}`);
      suggestions.push(`${last}_${first}`);
    } else {
      const name = parts[0].replace(/[^a-z0-9]/g, '');
      suggestions.push(`${name}${rand}`);
      suggestions.push(`${name}.official`);
      suggestions.push(`real_${name}`);
    }

    suggestionsBox.innerHTML = '';
    suggestions.forEach(sugg => {
      const chip = document.createElement('div');
      chip.className = 'suggestion-chip cursor-pointer bg-cyan-500/10 hover:bg-cyan-500/30 border border-cyan-500/30 text-cyan-300 text-xs px-3 py-1.5 rounded-full transition-all duration-200 select-none';
      chip.textContent = sugg;

      chip.addEventListener('click', () => {
        userInput.value = sugg;
        suggestionsBox.innerHTML = '';
      });

      suggestionsBox.appendChild(chip);
    });
  });
}

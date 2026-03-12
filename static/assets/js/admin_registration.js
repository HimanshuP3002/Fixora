document.addEventListener("DOMContentLoaded", function () {
  const passwordInput = document.getElementById("admin_password");
  const confirmInput = document.getElementById("admin_confirm_password");
  const confirmError = document.getElementById("confirm_password_error");
  const toggleButtons = document.querySelectorAll("[data-toggle-password]");
  const strengthLabel = document.getElementById("password_strength_label");
  const strengthHint = document.getElementById("password_strength_hint");
  const strengthBars = [
    document.getElementById("strength_bar_1"),
    document.getElementById("strength_bar_2"),
    document.getElementById("strength_bar_3"),
    document.getElementById("strength_bar_4")
  ];

  function paintStrength(level, toneClass) {
    strengthBars.forEach((bar, index) => {
      if (!bar) return;
      bar.classList.remove("bg-slate-600", "bg-rose-500", "bg-amber-500", "bg-yellow-400", "bg-emerald-500");
      bar.classList.add(index < level ? toneClass : "bg-slate-600");
    });
  }

  function updatePasswordStrength() {
    if (!passwordInput || !strengthLabel || !strengthHint) return;
    const value = passwordInput.value || "";

    const hasUpper = /[A-Z]/.test(value);
    const hasLower = /[a-z]/.test(value);
    const hasDigit = /\d/.test(value);
    const hasSpecial = /[^A-Za-z0-9]/.test(value);
    const longEnough = value.length >= 8;
    const score = [hasUpper, hasLower, hasDigit, hasSpecial, longEnough].filter(Boolean).length;

    if (!value.length) {
      strengthLabel.textContent = "Enter password";
      strengthLabel.className = "text-xs font-medium text-slate-400";
      strengthHint.textContent = "Use uppercase, lowercase, number, and special character.";
      paintStrength(0, "bg-slate-600");
      return;
    }

    if (score <= 2) {
      strengthLabel.textContent = "Weak";
      strengthLabel.className = "text-xs font-medium text-rose-300";
      strengthHint.textContent = "Add more character types and use at least 8 characters.";
      paintStrength(1, "bg-rose-500");
      return;
    }

    if (score === 3) {
      strengthLabel.textContent = "Fair";
      strengthLabel.className = "text-xs font-medium text-amber-300";
      strengthHint.textContent = "Good start. Add missing character types.";
      paintStrength(2, "bg-amber-500");
      return;
    }

    if (score === 4) {
      strengthLabel.textContent = "Good";
      strengthLabel.className = "text-xs font-medium text-yellow-300";
      strengthHint.textContent = "Almost strong. Ensure at least 8 characters.";
      paintStrength(3, "bg-yellow-400");
      return;
    }

    strengthLabel.textContent = "Strong";
    strengthLabel.className = "text-xs font-medium text-emerald-300";
    strengthHint.textContent = "Excellent password strength.";
    paintStrength(4, "bg-emerald-500");
  }

  function validateConfirmPassword() {
    if (!passwordInput || !confirmInput) return;
    if (confirmInput.value && confirmInput.value !== passwordInput.value) {
      confirmInput.setCustomValidity("Confirm password must match password.");
      if (confirmError) confirmError.classList.remove("hidden");
    } else {
      confirmInput.setCustomValidity("");
      if (confirmError) confirmError.classList.add("hidden");
    }
  }

  if (passwordInput && confirmInput) {
    passwordInput.addEventListener("input", validateConfirmPassword);
    passwordInput.addEventListener("input", updatePasswordStrength);
    confirmInput.addEventListener("input", validateConfirmPassword);
    updatePasswordStrength();
  }

  toggleButtons.forEach((button) => {
    button.addEventListener("click", function () {
      const targetId = button.getAttribute("data-toggle-password");
      const input = document.getElementById(targetId);
      if (!input) return;

      const nextType = input.type === "password" ? "text" : "password";
      input.type = nextType;

      const eyeOpen = button.querySelector("[data-eye-open]");
      const eyeOff = button.querySelector("[data-eye-off]");
      if (eyeOpen && eyeOff) {
        eyeOpen.classList.toggle("hidden", nextType === "text");
        eyeOff.classList.toggle("hidden", nextType === "password");
      }
    });
  });
});

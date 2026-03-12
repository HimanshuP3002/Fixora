function initIntlPhoneFields() {
  const intlInputs = document.querySelectorAll('input[data-intl-phone="true"]');
  intlInputs.forEach((input) => {
    if (!window.intlTelInput || input.dataset.intlInitialized === "1") return;
    input.dataset.intlInitialized = "1";
    const hiddenId = input.getAttribute("data-hidden-input");
    const hiddenInput = hiddenId ? document.getElementById(hiddenId) : null;
    let iti = null;
    try {
      iti = window.intlTelInput(input, {
        initialCountry: "in",
        nationalMode: false,
        separateDialCode: true,
        autoPlaceholder: "polite",
      });
    } catch (e) {
      iti = null;
    }

    const syncIntlPhone = () => {
      if (!hiddenInput) return;
      if (iti && typeof iti.getNumber === "function") {
        const number = iti.getNumber();
        if (number) {
          hiddenInput.value = number;
          return;
        }
      }
      const dialCode = iti && iti.getSelectedCountryData ? (iti.getSelectedCountryData().dialCode || "") : "";
      const digits = (input.value || "").replace(/\D/g, "");
      hiddenInput.value = digits ? `+${dialCode}${digits}` : "";
    };

    input.addEventListener("input", syncIntlPhone);
    input.addEventListener("countrychange", syncIntlPhone);
    if (input.form) input.form.addEventListener("submit", syncIntlPhone);
    syncIntlPhone();
  });
}

document.addEventListener("DOMContentLoaded", function () {
  const closeButtons = document.querySelectorAll(
    '[data-bs-dismiss="alert"]',
  );
  closeButtons.forEach((button) => {
    button.addEventListener("click", function () {
      const alertBox = this.closest(".animate-message");
      if (alertBox) {
        alertBox.style.transition =
          "opacity 0.3s ease, transform 0.3s ease";
        alertBox.style.opacity = "0";
        alertBox.style.transform = "translateY(-10px)";
        setTimeout(() => {
          alertBox.remove();
        }, 300);
      }
    });
  });

  initIntlPhoneFields();
});

if (document.readyState !== "loading") {
  initIntlPhoneFields();
}

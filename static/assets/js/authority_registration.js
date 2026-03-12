document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('authority-request-form');
  const submitBtn = document.getElementById('submit-btn');
  const submitText = document.getElementById('submit-text');
  const loadingSpinner = document.getElementById('loading-spinner');
  const fileInput = document.getElementById('verification_document');
  const fileName = document.getElementById('file-name');
  const password = document.getElementById('password');
  const confirmPassword = document.getElementById('confirm_password');

  if (fileInput && fileName) {
    fileInput.addEventListener('change', function () {
      fileName.textContent = fileInput.files && fileInput.files.length ? fileInput.files[0].name : 'No file selected';
    });
  }

  if (form && password && confirmPassword) {
    form.addEventListener('submit', function (event) {
      if (password.value !== confirmPassword.value) {
        event.preventDefault();
        confirmPassword.setCustomValidity('Passwords do not match.');
        confirmPassword.reportValidity();
        return;
      }
      confirmPassword.setCustomValidity('');

      if (submitBtn && loadingSpinner && submitText) {
        submitBtn.disabled = true;
        loadingSpinner.classList.remove('hidden');
        submitText.textContent = 'Submitting...';
      }
    });

    confirmPassword.addEventListener('input', function () {
      confirmPassword.setCustomValidity('');
    });
  }
});

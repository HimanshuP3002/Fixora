(function () {
  const userTypeSelect = document.getElementById('user_type');
  const adminSection = document.getElementById('admin-section');
  const authoritySection = document.getElementById('authority-section');
  const adminPreview = document.getElementById('id-preview-admin');
  const form = document.getElementById('add-user-form');
  if (!form) return;

  const typePills = form.querySelectorAll('[data-pick-type]');
  const fullNameInput = document.getElementById('full_name');
  const usernameInput = document.getElementById('username');
  const usernameSuggestionWrap = document.getElementById('username-suggestion-wrap');
  const usernameSuggestionBtns = form.querySelectorAll('.username-suggestion-btn');
  let usernameTouched = false;

  function buildUsernameSuggestions(fullName) {
    const cleaned = (fullName || '')
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9\s]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    if (!cleaned) return [];
    const parts = cleaned.split(' ').filter(Boolean);
    if (!parts.length) return [];
    const suffix = String(new Date().getFullYear()).slice(-2);
    const base1 = parts.join('_');
    const base2 = parts.join('');
    const base3 = parts.length > 1
      ? `${parts[0]}_${parts[parts.length - 1]}`
      : `${parts[0]}_${parts[0]}`;
    const base4 = parts.length > 1
      ? `${parts[0][0]}${parts[parts.length - 1]}`
      : `${parts[0]}_${suffix}`;

    const ordered = [
      `${base1}${suffix}`,
      `${base2}${suffix}`,
      `${base3}${suffix}`,
      `${base4}${suffix}`,
    ];

    const unique = [];
    ordered.forEach((v) => {
      const normalized = v.replace(/[^a-z0-9_]/g, '');
      if (normalized && !unique.includes(normalized)) unique.push(normalized);
    });
    return unique.slice(0, 3);
  }

  function refreshUsernameSuggestion() {
    const suggestions = buildUsernameSuggestions(fullNameInput.value);
    if (!suggestions.length) {
      usernameSuggestionWrap.classList.add('hidden');
      usernameSuggestionBtns.forEach((btn) => {
        btn.classList.add('hidden');
        btn.textContent = '';
      });
      return;
    }

    usernameSuggestionBtns.forEach((btn, idx) => {
      const suggestion = suggestions[idx];
      if (suggestion) {
        btn.textContent = suggestion;
        btn.classList.remove('hidden');
      } else {
        btn.textContent = '';
        btn.classList.add('hidden');
      }
    });
    usernameSuggestionWrap.classList.remove('hidden');

    if (!usernameTouched || !usernameInput.value.trim()) {
      usernameInput.value = suggestions[0];
    }
  }

  function setSectionRequired(sectionName, enabled) {
    const fields = form.querySelectorAll(`[data-required-for="${sectionName}"]`);
    fields.forEach((field) => {
      field.required = enabled;
      if (!enabled) field.setCustomValidity('');
    });
  }

  function updateVisibility() {
    const userType = userTypeSelect.value;
    const isAdmin = userType === 'admin';
    const isAuthority = userType === 'authority';

    adminSection.classList.toggle('hidden-section', !isAdmin);
    authoritySection.classList.toggle('hidden-section', !isAuthority);
    adminSection.classList.toggle('visible-section', isAdmin);
    authoritySection.classList.toggle('visible-section', isAuthority);
    adminPreview.classList.toggle('hidden', !isAdmin);

    typePills.forEach((pill) => {
      pill.classList.toggle('active', pill.dataset.pickType === userType);
    });

    setSectionRequired('admin', isAdmin);
    setSectionRequired('authority', isAuthority);
  }

  userTypeSelect.addEventListener('change', updateVisibility);
  fullNameInput.addEventListener('input', refreshUsernameSuggestion);
  usernameInput.addEventListener('input', function () {
    usernameTouched = true;
  });
  usernameSuggestionBtns.forEach((btn) => {
    btn.addEventListener('click', function () {
      usernameInput.value = btn.textContent || '';
      usernameInput.focus();
      usernameTouched = true;
    });
  });
  typePills.forEach((pill) => {
    pill.addEventListener('click', function () {
      userTypeSelect.value = pill.dataset.pickType;
      updateVisibility();
    });
  });
  updateVisibility();
  refreshUsernameSuggestion();

  const password = document.getElementById('password');
  const confirmPassword = document.getElementById('confirm_password');
  const rules = {
    length: document.getElementById('rule-length'),
    upper: document.getElementById('rule-upper'),
    lower: document.getElementById('rule-lower'),
    number: document.getElementById('rule-number'),
    special: document.getElementById('rule-special'),
    match: document.getElementById('rule-match')
  };

  function markRule(el, ok) {
    if (!el) return;
    el.classList.toggle('ok', !!ok);
  }

  function validatePasswordRules() {
    const value = password.value || '';
    const confirmValue = confirmPassword.value || '';
    const checks = {
      length: value.length >= 8,
      upper: /[A-Z]/.test(value),
      lower: /[a-z]/.test(value),
      number: /\d/.test(value),
      special: /[^A-Za-z0-9]/.test(value),
      match: value.length > 0 && value === confirmValue
    };

    markRule(rules.length, checks.length);
    markRule(rules.upper, checks.upper);
    markRule(rules.lower, checks.lower);
    markRule(rules.number, checks.number);
    markRule(rules.special, checks.special);
    markRule(rules.match, checks.match);

    const strongEnough = checks.length && checks.upper && checks.lower && checks.number && checks.special;
    if (!strongEnough) {
      password.setCustomValidity('Password must include upper, lower, number, and special character.');
    } else {
      password.setCustomValidity('');
    }

    if (!checks.match) {
      confirmPassword.setCustomValidity('Passwords do not match.');
    } else {
      confirmPassword.setCustomValidity('');
    }

    return strongEnough && checks.match;
  }

  form.querySelectorAll('[data-toggle-password]').forEach((btn) => {
    btn.addEventListener('click', function () {
      const target = document.getElementById(this.dataset.togglePassword);
      if (!target) return;
      const nextType = target.type === 'password' ? 'text' : 'password';
      target.type = nextType;
      const icon = this.querySelector('.material-symbols-rounded');
      if (icon) {
        icon.textContent = nextType === 'password' ? 'visibility' : 'visibility_off';
      }
      this.setAttribute('aria-label', nextType === 'password' ? 'Show password' : 'Hide password');
    });
  });

  password.addEventListener('input', validatePasswordRules);
  confirmPassword.addEventListener('input', validatePasswordRules);
  form.addEventListener('submit', function (event) {
    if (!validatePasswordRules()) {
      event.preventDefault();
      if (password.validationMessage) {
        password.reportValidity();
        return;
      }
      confirmPassword.reportValidity();
      return;
    }
  });
  validatePasswordRules();
})();

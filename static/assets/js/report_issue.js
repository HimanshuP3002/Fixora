function updateUI(category) {
  const titleInput = document.getElementById('titleInput');
  const descInput = document.getElementById('descInput');
  if (!titleInput || !descInput) return;

  if (category === 'road') {
    titleInput.placeholder = 'e.g. Deep Pothole at Main Junction';
    descInput.placeholder = 'Describe the size of the pothole and any traffic blockage caused...';
  } else if (category === 'garbage') {
    titleInput.placeholder = 'e.g. Uncollected Garbage Dump';
    descInput.placeholder = 'Describe the volume of waste and if it poses a health hazard...';
  } else if (category === 'water') {
    titleInput.placeholder = 'e.g. Pipeline Burst / Contaminated Water';
    descInput.placeholder = 'Is it a leakage or shortage? Describe the flow and duration...';
  } else if (category === 'electric') {
    titleInput.placeholder = 'e.g. Street Light Failure / Exposed Wire';
    descInput.placeholder = 'Is there sparking? Is the area completely dark? Describe safety risks...';
  }

  runAIPrediction();
}

function previewFile() {
  const input = document.getElementById('fileInput');
  const prompt = document.getElementById('uploadPrompt');
  const preview = document.getElementById('filePreview');
  const previewImg = document.getElementById('previewImage');
  if (!input || !prompt || !preview || !previewImg) return;

  if (input.files && input.files[0]) {
    const reader = new FileReader();
    reader.onload = function (e) {
      previewImg.src = e.target.result;
      prompt.classList.add('hidden');
      preview.classList.remove('hidden');
      preview.classList.add('flex');
      runAIPrediction();
    };
    reader.readAsDataURL(input.files[0]);
  }
}

function getSelectedRadioValue(name, fallback = '') {
  const node = document.querySelector(`input[name="${name}"]:checked`);
  return node ? node.value : fallback;
}

function toTitleCase(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function getPriorityTextClass(priority) {
  if (priority === 'High') return 'text-rose-300';
  if (priority === 'Low') return 'text-emerald-300';
  return 'text-amber-300';
}

function runAIPrediction() {
  const titleInput = document.getElementById('titleInput');
  const descInput = document.getElementById('descInput');
  const locationInput = document.getElementById('locationInput');
  const fileInput = document.getElementById('fileInput');

  const aiCategoryText = document.getElementById('aiCategoryText');
  const aiPriorityText = document.getElementById('aiPriorityText');
  const aiConfidenceText = document.getElementById('aiConfidenceText');
  const aiReasonText = document.getElementById('aiReasonText');
  const aiConfidenceBar = document.getElementById('aiConfidenceBar');
  const aiAuthenticityText = document.getElementById('aiAuthenticityText');
  const aiAuthenticityBadge = document.getElementById('aiAuthenticityBadge');

  if (!titleInput || !descInput || !aiCategoryText || !aiPriorityText || !aiConfidenceText || !aiReasonText || !aiConfidenceBar) {
    return;
  }

  const selectedCategory = getSelectedRadioValue('cat', 'road');
  const selectedUrgency = getSelectedRadioValue('urg', 'Medium');
  const textBlob = `${titleInput.value} ${descInput.value} ${locationInput ? locationInput.value : ''}`.toLowerCase();
  const hasImage = Boolean(fileInput && fileInput.files && fileInput.files.length > 0);

  const categoryKeywords = {
    road: ['pothole', 'road', 'traffic', 'accident', 'street', 'footpath', 'crack'],
    garbage: ['garbage', 'waste', 'trash', 'smell', 'dump', 'bin', 'sanitation'],
    water: ['water', 'pipeline', 'leak', 'drain', 'sewage', 'flood', 'overflow'],
    electric: ['electric', 'wire', 'pole', 'transformer', 'spark', 'street light', 'power']
  };

  const urgencyKeywords = {
    High: ['urgent', 'danger', 'accident', 'sparking', 'shock', 'flooding', 'blocked', 'emergency', 'fire'],
    Medium: ['soon', 'problem', 'issue', 'complaint', 'inconvenience'],
    Low: ['minor', 'small', 'cleaning', 'routine', 'slow']
  };

  const categoryScores = { road: 0, garbage: 0, water: 0, electric: 0 };
  Object.entries(categoryKeywords).forEach(([cat, words]) => {
    words.forEach((word) => {
      if (textBlob.includes(word)) categoryScores[cat] += 1;
    });
  });
  categoryScores[selectedCategory] += 1;

  let predictedCategory = selectedCategory;
  let topCategoryScore = categoryScores[selectedCategory];
  Object.entries(categoryScores).forEach(([cat, score]) => {
    if (score > topCategoryScore) {
      topCategoryScore = score;
      predictedCategory = cat;
    }
  });

  const urgencyScores = { High: 0, Medium: 1, Low: 0 };
  Object.entries(urgencyKeywords).forEach(([level, words]) => {
    words.forEach((word) => {
      if (textBlob.includes(word)) urgencyScores[level] += 1;
    });
  });
  urgencyScores[selectedUrgency] += 1;

  let predictedPriority = 'Medium';
  if (urgencyScores.High >= urgencyScores.Medium && urgencyScores.High >= urgencyScores.Low) {
    predictedPriority = 'High';
  } else if (urgencyScores.Low > urgencyScores.Medium) {
    predictedPriority = 'Low';
  }

  if (!titleInput.value.trim() || !descInput.value.trim()) {
    predictedPriority = selectedUrgency;
  }

  let confidence = 18;
  const textLength = `${titleInput.value} ${descInput.value}`.trim().length;
  if (textLength >= 30) confidence += 20;
  if (textLength >= 80) confidence += 15;
  confidence += Math.min(topCategoryScore * 8, 24);
  if (selectedUrgency === predictedPriority) confidence += 8;
  if (hasImage) confidence += 10;
  confidence = Math.max(18, Math.min(confidence, 96));

  const reasonParts = [];
  reasonParts.push(`Category signal: ${toTitleCase(predictedCategory)}.`);
  reasonParts.push(`Priority signal: ${predictedPriority}.`);
  if (hasImage) reasonParts.push('Evidence image attached.');
  if (textLength < 30) reasonParts.push('Add more description for better confidence.');

  aiCategoryText.textContent = toTitleCase(predictedCategory);
  aiPriorityText.textContent = predictedPriority;
  aiPriorityText.classList.remove('text-rose-300', 'text-amber-300', 'text-emerald-300');
  aiPriorityText.classList.add(getPriorityTextClass(predictedPriority));
  aiConfidenceText.textContent = `${confidence}%`;
  aiReasonText.textContent = reasonParts.join(' ');
  aiConfidenceBar.style.width = `${confidence}%`;

  if (aiAuthenticityText && aiAuthenticityBadge) {
    if (hasImage) {
      aiAuthenticityText.textContent = 'Original';
      aiAuthenticityText.classList.remove('text-amber-300');
      aiAuthenticityText.classList.add('text-emerald-300');
      aiAuthenticityBadge.classList.remove('bg-amber-300');
      aiAuthenticityBadge.classList.add('bg-emerald-300');
    } else {
      aiAuthenticityText.textContent = 'Awaiting image';
      aiAuthenticityText.classList.remove('text-emerald-300');
      aiAuthenticityText.classList.add('text-amber-300');
      aiAuthenticityBadge.classList.remove('bg-emerald-300');
      aiAuthenticityBadge.classList.add('bg-amber-300');
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  updateUI('road');

  const titleInput = document.getElementById('titleInput');
  const descInput = document.getElementById('descInput');
  const locationInput = document.getElementById('locationInput');
  const fileInput = document.getElementById('fileInput');
  const categoryInputs = document.querySelectorAll('input[name="cat"]');
  const urgencyInputs = document.querySelectorAll('input[name="urg"]');

  [titleInput, descInput, locationInput, fileInput].forEach((el) => {
    if (el) {
      el.addEventListener('input', runAIPrediction);
      el.addEventListener('change', runAIPrediction);
    }
  });

  categoryInputs.forEach((el) => el.addEventListener('change', runAIPrediction));
  urgencyInputs.forEach((el) => el.addEventListener('change', runAIPrediction));

  runAIPrediction();
});

window.updateUI = updateUI;
window.previewFile = previewFile;

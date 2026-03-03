'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  sourceDir: '',
  refDir: '',
  outputDir: '',
  threshold: 0.55,
  jobId: null,
  sse: null,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const sourceInput   = $('source-dir');
const sourceStatus  = $('source-status');
const btnNext1      = $('btn-next-1');

const refInput      = $('ref-dir');
const refStatus     = $('ref-status');
const thumbGrid     = $('thumbnail-grid');
const btnNext2      = $('btn-next-2');

const outputInput   = $('output-dir');
const outputStatus  = $('output-status');
const thresholdSlider = $('threshold');
const thresholdVal  = $('threshold-val');
const btnStart      = $('btn-start');

const phaseLabel    = $('phase-label');
const progressBar   = $('progress-bar');
const progressStats = $('progress-stats');
const completeBlock = $('complete-block');
const completeMsg   = $('complete-msg');
const cancelBlock   = $('cancel-block');

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtTime(sec) {
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function showStep(n) {
  for (let i = 1; i <= 4; i++) {
    const section = $(`step-${i}`);
    section.classList.toggle('hidden', i !== n);
  }
  document.querySelectorAll('.step').forEach(el => {
    const sn = parseInt(el.dataset.step);
    el.classList.toggle('active', sn === n);
    el.classList.toggle('done', sn < n);
  });
}

function setStatus(el, msg, type) {
  el.textContent = msg;
  el.className = 'status-line' + (type ? ' ' + type : '');
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

// ── Step 1: Photo Library ─────────────────────────────────────────────────────
let validateSourceTimer = null;

sourceInput.addEventListener('input', () => {
  btnNext1.disabled = true;
  setStatus(sourceStatus, '');
  clearTimeout(validateSourceTimer);
  validateSourceTimer = setTimeout(validateSource, 600);
});

async function validateSource() {
  const path = sourceInput.value.trim();
  if (!path) return;
  setStatus(sourceStatus, 'Checking…');
  const data = await apiPost('/api/validate-dir', { path });
  if (data.valid) {
    setStatus(sourceStatus, `Found ${data.images.toLocaleString()} photos in ${data.folders} folder(s)`, 'ok');
    state.sourceDir = path;
    btnNext1.disabled = false;
  } else {
    setStatus(sourceStatus, data.error || 'Directory not found', 'err');
    btnNext1.disabled = true;
  }
}

btnNext1.addEventListener('click', () => showStep(2));

$('btn-back-2').addEventListener('click', () => showStep(1));

// ── Step 2: Reference Photos ──────────────────────────────────────────────────
let validateRefTimer = null;

refInput.addEventListener('input', () => {
  btnNext2.disabled = true;
  setStatus(refStatus, '');
  thumbGrid.classList.add('hidden');
  thumbGrid.innerHTML = '';
  clearTimeout(validateRefTimer);
  validateRefTimer = setTimeout(validateRef, 600);
});

async function validateRef() {
  const path = refInput.value.trim();
  if (!path) return;
  setStatus(refStatus, 'Scanning…');
  const data = await apiPost('/api/scan-references', { path });
  if (data.error) {
    setStatus(refStatus, data.error, 'err');
    return;
  }
  if (data.count === 0) {
    setStatus(refStatus, 'No images found in this directory', 'err');
    return;
  }
  setStatus(refStatus, `${data.count} reference photo(s) found`, 'ok');
  state.refDir = path;

  // Render thumbnails
  thumbGrid.innerHTML = '';
  data.thumbnails.forEach(t => {
    const img = document.createElement('img');
    img.src = t.url;
    img.alt = t.name;
    img.title = t.name;
    thumbGrid.appendChild(img);
  });
  thumbGrid.classList.remove('hidden');
  btnNext2.disabled = false;
}

btnNext2.addEventListener('click', () => showStep(3));

// ── Step 3: Settings ──────────────────────────────────────────────────────────
$('btn-back-3').addEventListener('click', () => showStep(2));

thresholdSlider.addEventListener('input', () => {
  thresholdVal.textContent = parseFloat(thresholdSlider.value).toFixed(2);
  state.threshold = parseFloat(thresholdSlider.value);
});

let validateOutputTimer = null;

outputInput.addEventListener('input', () => {
  btnStart.disabled = true;
  setStatus(outputStatus, '');
  clearTimeout(validateOutputTimer);
  validateOutputTimer = setTimeout(validateOutput, 600);
});

async function validateOutput() {
  const path = outputInput.value.trim();
  if (!path) return;
  // Output dir may not exist yet; just check parent exists or accept the path
  const parent = path.substring(0, path.lastIndexOf('/')) || '/';
  const data = await apiPost('/api/validate-dir', { path: parent });
  if (data.valid || path.startsWith('/')) {
    setStatus(outputStatus, 'Output folder path accepted (will be created if needed)', 'ok');
    state.outputDir = path;
    btnStart.disabled = false;
  } else {
    setStatus(outputStatus, 'Parent directory not found', 'err');
  }
}

btnStart.addEventListener('click', startJob);

// ── Step 4: Progress ──────────────────────────────────────────────────────────
async function startJob() {
  showStep(4);
  phaseLabel.textContent = 'Starting…';
  progressBar.style.width = '0%';
  progressStats.textContent = '';
  completeBlock.classList.add('hidden');
  cancelBlock.classList.remove('hidden');

  const data = await apiPost('/api/start', {
    reference_dir: state.refDir,
    source_dir: state.sourceDir,
    output_dir: state.outputDir,
    threshold: state.threshold,
  });

  if (data.error) {
    phaseLabel.textContent = 'Error: ' + data.error;
    return;
  }

  state.jobId = data.job_id;
  connectSSE(data.job_id);
}

function connectSSE(jobId) {
  if (state.sse) state.sse.close();
  const es = new EventSource(`/api/progress?job_id=${jobId}`);
  state.sse = es;

  es.addEventListener('status', e => {
    const d = JSON.parse(e.data);
    phaseLabel.textContent = d.message;
  });

  es.addEventListener('progress', e => {
    const d = JSON.parse(e.data);
    const pct = d.total > 0 ? Math.round((d.done / d.total) * 100) : 0;
    progressBar.style.width = pct + '%';
    phaseLabel.textContent = `Processing photos… ${pct}%`;
    const eta = d.eta_sec > 0 ? ` — ~${fmtTime(d.eta_sec)} remaining` : '';
    progressStats.textContent =
      `${d.done.toLocaleString()} / ${d.total.toLocaleString()} — ${d.matched} match${d.matched !== 1 ? 'es' : ''}${eta}`;
  });

  es.addEventListener('complete', e => {
    const d = JSON.parse(e.data);
    progressBar.style.width = '100%';
    phaseLabel.textContent = 'Done!';
    progressStats.textContent =
      `${d.matched} match${d.matched !== 1 ? 'es' : ''} out of ${d.total.toLocaleString()} photos — ${fmtTime(d.elapsed_sec)}`;
    completeMsg.textContent =
      `Found ${d.matched} photo${d.matched !== 1 ? 's' : ''} — saved to ${d.output_dir}`;
    completeBlock.classList.remove('hidden');
    cancelBlock.classList.add('hidden');
    es.close();
  });

  es.addEventListener('error', e => {
    try {
      const d = JSON.parse(e.data);
      phaseLabel.textContent = 'Error: ' + d.message;
    } catch {
      phaseLabel.textContent = 'Connection error.';
    }
    cancelBlock.classList.add('hidden');
    es.close();
  });

  es.onerror = () => {
    // SSE connection dropped — stream ended or server error
    es.close();
  };
}

$('btn-cancel').addEventListener('click', async () => {
  if (!state.jobId) return;
  $('btn-cancel').disabled = true;
  await apiPost('/api/cancel', { job_id: state.jobId });
  phaseLabel.textContent = 'Cancelling…';
});

$('btn-open-folder').addEventListener('click', () => {
  fetch(`/api/reveal?path=${encodeURIComponent(state.outputDir)}`);
});

$('btn-restart').addEventListener('click', () => {
  // Reset all state
  state.sourceDir = '';
  state.refDir = '';
  state.outputDir = '';
  state.threshold = 0.55;
  state.jobId = null;
  if (state.sse) { state.sse.close(); state.sse = null; }

  sourceInput.value = '';
  refInput.value = '';
  outputInput.value = '';
  thresholdSlider.value = 0.55;
  thresholdVal.textContent = '0.55';
  setStatus(sourceStatus, '');
  setStatus(refStatus, '');
  setStatus(outputStatus, '');
  thumbGrid.innerHTML = '';
  thumbGrid.classList.add('hidden');
  btnNext1.disabled = true;
  btnNext2.disabled = true;
  btnStart.disabled = true;
  $('btn-cancel').disabled = false;

  showStep(1);
});

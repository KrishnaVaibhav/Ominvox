// First-run setup: system check, voice licence, Hugging Face token, model downloads.
// Server side: ominvox/ui/onboarding.py (fr_* messages). Uses $, send, showToast from app.js.
'use strict';

let fr = null;                 // latest "onboarding" state from the server
let setupPage = 0;
let setupDismissed = false;    // "Finish later" clicked this session
let dlStats = {t: 0, bytes: 0, speed: 0};

const GBf = b => (b / 2 ** 30).toFixed(b >= 2 ** 30 * 10 ? 0 : 1) + ' GB';
const MBf = b => b >= 2 ** 30 ? GBf(b) : Math.max(1, Math.round(b / 2 ** 20)) + ' MB';

// ── open / close / navigate ────────────────────────────────
function openSetup(needed) {
  $('setup').hidden = false;
  if (needed) {
    showToast('Finish setup first, then press Start');
    goToPage(firstIncompleteStep());
  }
  send({type: 'fr_state', recheck: true});
}
function closeSetup() { $('setup').hidden = true; }
function goToPage(i) {
  setupPage = Math.max(0, Math.min(3, i));
  document.querySelectorAll('.setup-page').forEach(p => p.hidden = +p.dataset.page !== setupPage);
  document.querySelectorAll('#setup-step-list li').forEach(li => li.classList.toggle('on', +li.dataset.step === setupPage));
  renderFooter();
}

// ── step status ────────────────────────────────────────────
function stepStatus(i) {
  if (!fr) return '';
  if (i === 0) {
    const s = fr.checks.map(c => c.status);
    return s.includes('fail') ? 'fail' : s.includes('warn') ? 'warn' : 'ok';
  }
  if (i === 1) return fr.license.accepted ? 'ok' : 'warn';
  if (i === 2) return fr.token.ok ? 'ok' : 'warn';
  return fr.ready ? 'ok' : (fr.models.some(m => m.state === 'error') ? 'fail' : '');
}
function firstIncompleteStep() {
  if (!fr) return 0;
  if (stepStatus(0) === 'fail') return 0;
  if (!fr.license.accepted && !fr.done) return 1;
  return fr.ready ? 0 : 3;
}

// ── server messages ────────────────────────────────────────
function setupState(m) {
  const first = fr === null;
  fr = m;
  renderChecks(); renderLicense(); renderToken(); renderModels(); renderFooter();
  document.querySelectorAll('#setup-step-list li').forEach(li => {
    li.classList.remove('ok', 'warn', 'fail');
    const s = stepStatus(+li.dataset.step); if (s) li.classList.add(s);
  });
  $('setup-btn').classList.toggle('apply', !m.ready);
  if (first) {
    $('want-translator').checked = m.needs_translator;
    if (m.show && !setupDismissed) { $('setup').hidden = false; goToPage(firstIncompleteStep()); }
  }
}
function setupModels(m) {
  if (!fr) return;
  fr.models = m.models; fr.busy = m.busy;
  renderModels(); renderFooter();
}
function setupTokenChecking() {
  $('token-msg').className = 'token-msg'; $('token-msg').textContent = 'Checking…';
}

// ── page renderers ─────────────────────────────────────────
function renderChecks() {
  const icon = {ok: '✓', warn: '!', fail: '✕'};
  $('check-list').innerHTML = '';
  for (const c of fr.checks) {
    const row = document.createElement('div');
    row.className = 'check';
    const status = c.status in icon ? c.status : 'warn';
    row.innerHTML = '<span class="ic"></span><div><b></b><span></span></div>';
    row.querySelector('.ic').classList.add(status);
    row.querySelector('.ic').textContent = icon[status];
    row.querySelector('b').textContent = c.label;
    row.querySelector('span:not(.ic)').textContent = c.detail;
    if (c.fix_url) {
      const b = document.createElement('button');
      b.className = 'btn-sm'; b.textContent = 'Get driver';
      b.onclick = () => send({type: 'open_url', url: c.fix_url});
      row.appendChild(b);
    }
    $('check-list').appendChild(row);
  }
}
function renderLicense() {
  $('license-state').textContent = fr.license.accepted
    ? 'Agreed. The voice model will be downloaded in the last step.'
    : 'Without the voice model, translations are shown as text only. You can agree later in Setup.';
  $('license-yes').disabled = fr.license.accepted;
}
function renderToken() {
  const t = fr.token;
  const repos = (t.models && t.models.length) ? t.models
    : ['pyannote/speaker-diarization-3.1', 'pyannote/segmentation-3.0'].map(r => ({repo: r, url: 'https://huggingface.co/' + r, ok: null}));
  $('gated-list').innerHTML = '';
  for (const r of repos) {
    const d = document.createElement('div');
    d.innerHTML = `<span class="${r.ok ? 'ok' : 'no'}">${r.ok ? '✓' : r.ok === false ? '✕' : '•'}</span><button class="link"></button>`;
    const b = d.querySelector('button'); b.textContent = r.repo; b.onclick = () => send({type: 'open_url', url: r.url});
    $('gated-list').appendChild(d);
  }
  const msg = $('token-msg');
  if (!t.checked) { msg.className = 'token-msg'; msg.textContent = ''; return; }
  if (t.ok) { msg.className = 'token-msg ok'; msg.textContent = `✓ Signed in as ${t.user}. Speaker separation is ready to download.`; }
  else if (t.valid) { msg.className = 'token-msg err'; msg.textContent = `Signed in as ${t.user}, but the pages marked ✕ haven't been accepted yet. Accept them, then click Check & save again.`; }
  else { msg.className = 'token-msg err'; msg.textContent = t.error || 'Token not accepted.'; }
}
function modelStateText(m) {
  switch (m.state) {
    case 'present': case 'done': return ['ok', 'Downloaded'];
    case 'queued': return ['', 'Waiting…'];
    case 'downloading': return ['', `${MBf(m.done_bytes)} of ${MBf(m.size)}`];
    case 'error': return ['err', m.error || 'Failed'];
    case 'blocked': return ['skip', m.needs === 'token' ? 'Skipped — needs the Hugging Face token (step 3)'
                                                       : 'Skipped — voice licence not agreed (step 2)'];
    default: return ['', 'Not downloaded'];
  }
}
function wantedModels() {
  const wantTr = $('want-translator').checked;
  return fr.models.filter(m => !m.optional || wantTr || ['present', 'done', 'downloading', 'queued'].includes(m.state));
}
function renderModels() {
  const list = $('model-list'); list.innerHTML = '';
  for (const m of wantedModels()) {
    const [cls, text] = modelStateText(m);
    const pct = ['present', 'done'].includes(m.state) ? 100 : m.size ? 100 * m.done_bytes / m.size : 0;
    const row = document.createElement('div');
    row.className = 'model';
    row.innerHTML = `<div class="model-top"><b></b><span class="size">${MBf(m.size)}</span></div>
      <div class="purpose"></div><div class="pbar"><div style="width:${pct}%"></div></div>
      <div class="state ${cls}" style="margin-top:4px"></div>`;
    row.querySelector('b').textContent = m.name;
    row.querySelector('.purpose').textContent = m.purpose;
    row.querySelector('.state').textContent = text;
    list.appendChild(row);
  }
  // totals, speed and time left
  const todo = wantedModels().filter(m => ['missing', 'error', 'queued', 'downloading'].includes(m.state));
  const total = todo.reduce((a, m) => a + m.size, 0);
  const done = todo.reduce((a, m) => a + (m.done_bytes || 0), 0);
  const now = performance.now() / 1000;
  if (fr.busy && dlStats.t) {
    const inst = (done - dlStats.bytes) / Math.max(0.1, now - dlStats.t);
    if (inst >= 0) dlStats.speed = dlStats.speed ? 0.8 * dlStats.speed + 0.2 * inst : inst;
  }
  dlStats.t = now; dlStats.bytes = done;
  const left = total - done;
  $('dl-total').textContent = !todo.length
    ? (fr.ready ? 'Everything needed is downloaded.' : '')
    : fr.busy
      ? `${MBf(done)} of ${MBf(total)}` + (dlStats.speed > 1e5 ? ` · ${(dlStats.speed / 2 ** 20).toFixed(1)} MB/s · about ${Math.ceil(left / dlStats.speed / 60)} min left` : '')
      : `${MBf(total)} to download.`;
  const missing = todo.filter(m => ['missing', 'error'].includes(m.state));
  const btn = $('download-btn');
  btn.disabled = fr.busy || !missing.length;
  btn.textContent = fr.busy ? 'Downloading…' : missing.length ? `Download (${MBf(missing.reduce((a, m) => a + m.size, 0))})` : 'Download';
}
function renderFooter() {
  $('setup-back').style.visibility = setupPage === 0 ? 'hidden' : '';
  const last = setupPage === 3;
  const next = $('setup-next');
  next.textContent = last ? 'Finish' : 'Next';
  next.disabled = last && !(fr && fr.ready);
  next.title = next.disabled ? 'Download the models first' : '';
}

// ── actions ────────────────────────────────────────────────
$('setup-btn').onclick = () => { setupDismissed = false; openSetup(false); };
$('setup-back').onclick = () => goToPage(setupPage - 1);
$('setup-next').onclick = () => {
  if (setupPage < 3) return goToPage(setupPage + 1);
  send({type: 'fr_done'}); closeSetup(); showToast('All set. Pick your devices and press Start Listening.', 3500);
};
$('setup-later').onclick = () => { setupDismissed = true; closeSetup(); };
document.querySelectorAll('#setup-step-list li').forEach(li => li.onclick = () => goToPage(+li.dataset.step));
$('recheck-btn').onclick = () => send({type: 'fr_state', recheck: true});
$('license-yes').onclick = () => { send({type: 'fr_license', accept: true}); goToPage(2); };
$('license-no').onclick = () => { send({type: 'fr_license', accept: false}); goToPage(2); };
$('token-btn').onclick = () => {
  const v = $('token-input').value.trim();
  if (!v) { $('token-msg').className = 'token-msg err'; $('token-msg').textContent = 'Paste your token first.'; return; }
  send({type: 'fr_token', token: v});
};
$('token-input').addEventListener('keydown', e => { if (e.key === 'Enter') $('token-btn').click(); });
$('want-translator').addEventListener('change', () => fr && renderModels());
$('download-btn').onclick = () => {
  const ids = wantedModels().filter(m => ['missing', 'error'].includes(m.state)).map(m => m.id);
  dlStats = {t: 0, bytes: 0, speed: 0};
  send({type: 'fr_download', ids});
};
document.querySelectorAll('#setup [data-url]').forEach(b => b.onclick = () => send({type: 'open_url', url: b.dataset.url}));
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('setup').hidden) $('setup-later').click(); });

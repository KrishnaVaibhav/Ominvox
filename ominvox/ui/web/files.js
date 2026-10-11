'use strict';
// Files tab: choose a file -> audio track -> spoken language -> target languages
// -> output -> translate, with progress and the saved files. Uses $, send,
// escHtml, showToast and openSetup from app.js / setup.js.

const F = {info: null, track: 0, detected: {}, prefs: {}, langs: [], outDir: null,
           running: false, translatorReady: false, targets: new Set()};

// ── Live / Files switch ────────────────────────────────────
function setMode(mode) {
  document.querySelectorAll('#mode-seg button').forEach(b => b.classList.toggle('on', b.dataset.mode === mode));
  const files = mode === 'files';
  $('files-view').hidden = !files;
  $('layout').hidden = files;
  document.querySelectorAll('.live-only').forEach(el => el.classList.toggle('mode-hidden', files));
  try { localStorage.setItem('ominvox-mode', mode); } catch (e) {}
  if (!files) setTimeout(drawLagChart, 0);
}
document.querySelectorAll('#mode-seg button').forEach(b => b.onclick = () => setMode(b.dataset.mode));
try { if (location.hash === '#files' || localStorage.getItem('ominvox-mode') === 'files') setMode('files'); } catch (e) {}

// ── Messages from the server (routed from app.js) ──────────
function filesMessage(m) {
  switch (m.type) {
    case 'file_state': fileState(m); break;
    case 'file_lang': fileLang(m); break;
    case 'file_track': F.track = m.track; renderFile(); showToast(m.reason, 4000); break;
    case 'file_out_dir': F.outDir = m.out_dir; $('out-dir').textContent = m.out_dir; break;
    case 'file_started': F.running = true; showProgress(); renderForm(); break;
    case 'file_progress': F.running = true; renderProgress(m); renderForm(); break;
    case 'file_done': F.running = false; renderDone(m); renderForm(); break;
    case 'file_cancelled': F.running = false; $('fp-stage').textContent = 'Cancelled'; $('cancel-btn').hidden = true; renderForm(); break;
    case 'file_error':
      if (F.running) { F.running = false; $('fp-stage').textContent = 'Failed: ' + m.msg; $('cancel-btn').hidden = true; renderForm(); }
      $('drop-msg').textContent = ''; showToast(m.msg, 5000); setLog(m.msg); break;
  }
}

function fileState(m) {
  F.langs = m.languages || F.langs;
  F.prefs = m.prefs || {};
  F.translatorReady = !!m.translator_ready;
  F.running = !!m.running;
  F.targets = new Set(F.prefs.targets || []);
  if (m.info) F.track = m.track != null ? m.track : (m.info.default_track || 0);
  F.info = m.info; F.detected = m.detected || {}; F.outDir = m.out_dir;
  applyPrefs();
  renderFile();
  if (m.last) {
    if (m.last.type === 'file_progress') { showProgress(); renderProgress(m.last); }
    else if (m.last.type === 'file_done') renderDone(m.last);
  }
}

function applyPrefs() {
  const p = F.prefs;
  document.querySelectorAll('input[name=out-mode]').forEach(r => r.checked = r.value === (p.output || 'add'));
  $('fmt-sel').value = p.audio_format || 'mp3';
  $('opt-bg').checked = !!p.keep_background;
  $('opt-srt').checked = p.subtitles !== false;
  $('opt-single').checked = p.voice_mode === 'single';
}

// ── File ───────────────────────────────────────────────────
const fmtDur = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`; };
const fmtSize = b => b >= 2 ** 30 ? (b / 2 ** 30).toFixed(1) + ' GB' : (b / 2 ** 20).toFixed(1) + ' MB';
const fmtLeft = s => s == null ? '–' : s < 60 ? `${Math.max(1, Math.round(s))} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;

function renderFile() {
  const info = F.info, has = !!info;
  $('drop').hidden = has;
  $('file-card').hidden = !has;
  ['lang-sec', 'target-sec', 'out-sec', 'fv-actions'].forEach(id => $(id).hidden = !has);
  if (!has) { $('track-sec').hidden = true; renderForm(); return; }
  const video = info.kind === 'video';
  $('fc-ico').textContent = video ? '🎬' : '🎵';
  $('fc-name').textContent = info.name;
  $('fc-meta').textContent = `${video ? 'Video' : 'Audio'} · ${fmtDur(info.duration)} · ${fmtSize(info.size)}` +
    (info.tracks.length > 1 ? ` · ${info.tracks.length} audio tracks` : '');
  $('out-dir').textContent = F.outDir || '–';
  $('track-sec').hidden = info.tracks.length < 2;
  $('track-count').textContent = `${info.tracks.length} tracks`;
  $('track-list').innerHTML = info.tracks.map(t => {
    const bits = [t.lang_name || (t.language && t.language !== 'und' ? t.language : null), t.title,
      `${t.codec.toUpperCase()} ${t.channels === 1 ? 'mono' : t.channels === 2 ? 'stereo' : t.channels + 'ch'}`].filter(Boolean);
    return `<label class="choice"><input type="radio" name="track" value="${t.index}" ${t.index === F.track ? 'checked' : ''}>
      <span><b>Track ${t.index + 1}${t.default ? ' <span class="tag">default</span>' : ''}</b>
      <span class="hint">${escHtml(bits.join(' · '))}</span></span></label>`;
  }).join('');
  document.querySelectorAll('input[name=track]').forEach(r => r.onchange = () => {
    F.track = +r.value;
    if (!F.detected[F.track]) send({type: 'file_detect', track: F.track});
    renderDetect();
  });
  $('out-sec').querySelector('#video-out').hidden = !video;
  renderDetect();
}

function fileLang(m) {
  if (m.busy) { F.detected[m.track] = {busy: true}; }
  else F.detected[m.track] = m;
  renderDetect();
}

function sourceLang() {
  const o = $('src-override').value;
  if (o) return o;
  const d = F.detected[F.track];
  return d && d.lang ? d.lang : null;
}

function renderDetect() {
  const d = F.detected[F.track];
  const out = $('detect-out');
  if (!d || d.busy) out.innerHTML = '<span class="spinner"></span> Listening to the start of the track…';
  else if (!d.speech) out.innerHTML = '<b>No speech found</b> in the first minutes of this track. Pick the language below, or another track.';
  else {
    const pct = Math.round(d.prob * 100);
    const others = (d.candidates || []).filter(c => c.lang !== d.lang && c.prob > 0.05)
      .map(c => `${escHtml(c.name)} ${Math.round(c.prob * 100)}%`).join(', ');
    out.innerHTML = `<b>${escHtml(d.name)}</b> <span class="hint">${pct}% sure${others ? ' · also possible: ' + others : ''}</span>`;
  }
  const sel = $('src-override'), keep = sel.value;
  const names = Object.fromEntries(F.langs.map(l => [l.code, l.name]));
  sel.innerHTML = `<option value="">${d && d.name ? 'Detected: ' + escHtml(d.name) : 'Detect automatically'}</option>` +
    F.langs.map(l => `<option value="${l.code}">${escHtml(l.name)}</option>`).join('');
  if (keep && names[keep]) sel.value = keep;
  renderChips();
}
$('src-override').onchange = () => renderChips();

// ── Target languages ───────────────────────────────────────
function renderChips() {
  const src = sourceLang();
  $('chips').innerHTML = F.langs.map(l => {
    const spoken = l.code === src;
    const on = F.targets.has(l.code) && !spoken;
    return `<label class="chip${on ? ' on' : ''}${spoken ? ' off' : ''}" title="${spoken ? 'This is the spoken language' : ''}">
      <input type="checkbox" value="${l.code}" ${on ? 'checked' : ''} ${spoken ? 'disabled' : ''}>${escHtml(l.name)}${spoken ? ' <small>spoken</small>' : ''}</label>`;
  }).join('');
  $('chips').querySelectorAll('input').forEach(cb => cb.onchange = () => {
    cb.checked ? F.targets.add(cb.value) : F.targets.delete(cb.value);
    cb.parentElement.classList.toggle('on', cb.checked);
    renderForm();
  });
  renderForm();
}
$('all-btn').onclick = () => { const src = sourceLang(); F.langs.forEach(l => l.code !== src && F.targets.add(l.code)); renderChips(); };
$('none-btn').onclick = () => { F.targets.clear(); renderChips(); };
$('get-translator').onclick = () => { send({type: 'fr_state'}); openSetup(true); };

function chosenTargets() {
  const src = sourceLang();
  return F.langs.map(l => l.code).filter(c => F.targets.has(c) && c !== src);
}

// ── Output + Translate button ──────────────────────────────
function outMode() {
  if (!F.info || F.info.kind !== 'video') return 'separate';
  const r = document.querySelector('input[name=out-mode]:checked');
  return r ? r.value : 'add';
}
document.querySelectorAll('input[name=out-mode]').forEach(r => r.onchange = renderForm);
$('dir-btn').onclick = () => send({type: 'file_pick_dir'});

function renderForm() {
  const targets = chosenTargets();
  const mode = outMode();
  $('fmt-field').hidden = mode !== 'separate';
  $('translator-warn').classList.toggle('show', !F.translatorReady && targets.some(t => t !== 'en'));
  const d = F.detected[F.track];
  const detecting = d && d.busy;
  const ready = F.info && targets.length && !F.running && !detecting && sourceLang();
  $('dub-btn').disabled = !ready;
  $('dub-btn').textContent = targets.length > 1 ? `Translate into ${targets.length} languages` : 'Translate';
  let hint = '';
  if (F.running) hint = 'Translating… you can switch to Live view meanwhile (Start Listening waits until this finishes).';
  else if (F.info && !sourceLang() && !detecting) hint = 'Choose the spoken language first.';
  else if (F.info && !targets.length) hint = 'Pick at least one language.';
  else if (F.info) {
    // Rough guide from measurements on an RTX 4070 laptop: speech recognition
    // ~0.15x the length, each language ~0.6x; plus loading the models.
    const est = F.info.duration * (0.15 + 0.6 * targets.length) + 40;
    hint = `Takes roughly ${fmtLeft(est)} on a fast GPU.`;
  }
  $('dub-hint').textContent = hint;
  document.querySelectorAll('#files-view .fv-form input, #files-view .fv-form select, #change-btn, #dir-btn, #all-btn, #none-btn')
    .forEach(el => el.disabled = F.running || (el.closest('.chip') && el.closest('.chip').classList.contains('off')));
}

$('dub-btn').onclick = () => {
  const msg = {
    type: 'file_start', track: F.track, source_lang: sourceLang(), targets: chosenTargets(),
    output: outMode(), audio_format: $('fmt-sel').value, keep_background: $('opt-bg').checked,
    subtitles: $('opt-srt').checked, voice_mode: $('opt-single').checked ? 'single' : 'match',
  };
  send(msg);
  $('dub-btn').disabled = true;
};
$('cancel-btn').onclick = () => send({type: 'file_cancel'});

// ── Choosing / dropping a file ─────────────────────────────
$('pick-btn').onclick = () => send({type: 'file_pick'});
$('change-btn').onclick = () => send({type: 'file_pick'});

// The window would otherwise open a dropped file itself.
['dragover', 'drop'].forEach(ev => window.addEventListener(ev, e => e.preventDefault()));
const fv = $('files-view');
fv.addEventListener('dragover', e => { if (!F.running) $('drop').classList.add('hover'); });
fv.addEventListener('dragleave', e => { if (e.target === fv || !fv.contains(e.relatedTarget)) $('drop').classList.remove('hover'); });
fv.addEventListener('drop', e => {
  $('drop').classList.remove('hover');
  const file = e.dataTransfer && e.dataTransfer.files[0];
  if (!file || F.running) return;
  $('drop').hidden = false; $('file-card').hidden = true;
  const xhr = new XMLHttpRequest();
  xhr.open('PUT', '/api/upload?name=' + encodeURIComponent(file.name));
  xhr.upload.onprogress = ev => { if (ev.lengthComputable) $('drop-msg').textContent = `Loading ${file.name}… ${Math.round(100 * ev.loaded / ev.total)}%`; };
  xhr.onload = () => {
    $('drop-msg').textContent = '';
    if (xhr.status !== 200) showToast(xhr.status === 409 ? 'Wait for the current translation to finish' : 'Could not load the file');
  };
  xhr.onerror = () => { $('drop-msg').textContent = ''; showToast('Could not load the file'); };
  xhr.send(file);
});

// ── Progress / results ─────────────────────────────────────
const LANG_STATE = {queued: 'Waiting', translating: 'Translating', voicing: 'Speaking', saving: 'Saving', done: 'Done', error: 'Failed'};
function langName(code) { const l = F.langs.find(l => l.code === code); return l ? l.name : code; }

function showProgress() {
  $('fp-empty').hidden = true; $('fp-body').hidden = false;
  $('cancel-btn').hidden = false; $('fp-results').hidden = true; $('fp-result-list').innerHTML = '';
  $('fp-preview').hidden = true;
}

function renderProgress(p) {
  if ($('fp-body').hidden) showProgress();
  $('cancel-btn').hidden = false;
  const pct = Math.floor(p.pct * 100);
  $('fp-stage').textContent = p.stage;
  $('fp-pct').innerHTML = `${pct}<small>%</small>`;
  $('fp-bar').style.width = (p.pct * 100) + '%';
  $('fp-elapsed').textContent = fmtLeft(p.elapsed_s);
  $('fp-eta').textContent = p.eta_s == null ? 'estimating…' : fmtLeft(p.eta_s);
  renderLangRows(p.langs || {});
  if (p.preview) {
    const v = p.preview;
    $('fp-preview').hidden = false;
    $('fp-preview').innerHTML = `<div class="hint">${escHtml(v.speaker)} · ${fmtDur(v.at)} · ${escHtml(langName(v.lang))}</div>
      <div class="pv-src"></div><div class="pv-tgt"></div>`;
    $('fp-preview').querySelector('.pv-src').textContent = v.src;
    $('fp-preview').querySelector('.pv-tgt').textContent = v.text;
  }
  if (p.outputs && p.outputs.length) renderResults(p.outputs, null);
}

function renderLangRows(langs) {
  const codes = Object.keys(langs);
  $('fp-count').textContent = codes.length ? `${codes.filter(c => langs[c].state === 'done').length} of ${codes.length}` : '–';
  $('fp-langs').innerHTML = codes.map(c => {
    const s = langs[c];
    const done = Number(s.done) || 0, total = Number(s.total) || 0;
    const state = escHtml(s.state);
    const frac = s.state === 'done' ? 1 : total ? done / total : 0;
    const detail = s.state === 'voicing' && total ? ` ${done}/${total}` : '';
    // Translations can run longer than the original; say how far lines slipped.
    const tip = s.error || (s.late_lines ? `${s.late_lines} line(s) start late, by up to ${s.late_max} s, `
      + 'because the translation is longer than the original line.' : '');
    return `<div class="lang-row ${state}" title="${escHtml(tip)}">
      <span class="ln">${escHtml(langName(c))}</span>
      <div class="pbar"><div style="width:${(frac * 100).toFixed(1)}%"></div></div>
      <span class="ls">${LANG_STATE[s.state] || state}${detail}${s.state === 'done' && s.late_lines ? ' ⚠' : ''}</span></div>`;
  }).join('');
}

const KIND_ICON = {video: '🎬', audio: '🎵', subtitles: '💬'};
function renderResults(outputs, outDir) {
  $('fp-results').hidden = false;
  $('fp-result-list').innerHTML = outputs.map((o, i) => `<div class="result-row">
      <span class="ri">${KIND_ICON[o.kind] || '📄'}</span><span class="rn" title="${escHtml(o.path)}">${escHtml(o.name)}</span>
      <button class="btn-sm" data-i="${i}">Show</button></div>`).join('');
  $('fp-result-list').querySelectorAll('button').forEach(b => b.onclick = () => send({type: 'file_reveal', path: outputs[+b.dataset.i].path}));
  $('open-dir-btn').onclick = () => send({type: 'file_reveal', path: outDir || F.outDir});
}

function renderDone(m) {
  if ($('fp-body').hidden) showProgress();
  $('cancel-btn').hidden = true;
  const failed = Object.entries(m.langs || {}).filter(([, s]) => s.state === 'error');
  $('fp-stage').textContent = failed.length ? `Done, but ${failed.map(([c]) => langName(c)).join(', ')} failed` : 'Done';
  $('fp-pct').innerHTML = '100<small>%</small>';
  $('fp-bar').style.width = '100%';
  $('fp-eta').textContent = '–';
  renderLangRows(m.langs || {});
  renderResults(m.outputs || [], m.out_dir);
  showToast('Translation finished');
}

renderFile();

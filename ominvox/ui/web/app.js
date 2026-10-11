'use strict';
const $ = id => document.getElementById(id);
const SPEAKER_COLORS = ['--spk0','--spk1','--spk2','--spk3','--spk4'];
// The parts of a line's lag, in order; together they add up to the lag.
const STAGES = [
  {key:'speech',   label:'Person speaking',      color:'--series-1', tip:'Whole sentences are translated, so this waits for the speaker to finish'},
  {key:'endpoint', label:'End-of-sentence pause', color:'--series-2', tip:'Silence needed to know the sentence has ended'},
  {key:'queue',    label:'Waiting for GPU',       color:'--series-3', tip:'The previous line was still being processed'},
  {key:'diarize',  label:'Speaker ID',            color:'--series-4', tip:'Who is speaking'},
  {key:'stt',      label:'Speech-to-text',        color:'--series-5', tip:'Whisper'},
  {key:'mt',       label:'Translation',           color:'--series-6', tip:'Whisper (to English) or NLLB'},
  {key:'tts',      label:'Voice',                 color:'--series-7', tip:'XTTS voice synthesis'},
  {key:'wait',     label:'Playback wait',         color:'--series-8', tip:'Waiting for the previous line to finish playing, or for its fixed-lag slot'},
];
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

let ws = null, pipelineState = 'stopped', devices = null, cfg = {};
let speakerRoster = {}, speakerMap = {}, speakerCount = 0, activeSpeaker = null;
let autoScroll = true, lastStats = null, lastLine = null, probeActive = false;
let lagHistory = [];

// ── WebSocket ──────────────────────────────────────────────
function connect() {
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onopen = () => setLog('Connected');
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    switch (m.type) {
      case 'status': handleStatus(m); break;
      case 'utterance': handleUtterance(m); break;
      case 'line_metrics': handleLineMetrics(m); break;
      case 'stats': handleStats(m); break;
      case 'speakers': handleSpeakers(m.speakers, m); break;
      case 'devices': devices = m.devices; renderDevices(); showToast('Device list updated'); break;
      case 'level': updateLevel(m.rms); break;
      case 'probe': probeActive = m.active; renderProbe(); break;
      case 'log': setLog(m.msg); break;
      case 'onboarding': setupState(m); break;          // setup.js
      case 'models': setupModels(m); break;
      case 'fr_token_checking': setupTokenChecking(); break;
      case 'need_setup': openSetup(true); break;
      default: if (m.type.startsWith('file_')) filesMessage(m);   // files.js
    }
  };
  ws.onclose = () => { setStatus('stopped'); setLog('Disconnected — retrying in 3 s…'); setTimeout(connect, 3000); };
  ws.onerror = () => ws.close();
}
function send(obj) { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); }

// ── Status / start-stop ────────────────────────────────────
function handleStatus(m) {
  setStatus(m.state);
  if (m.config) { cfg = m.config; devices = cfg.devices; applyConfig(); }
  if (m.speakers) handleSpeakers(m.speakers);
}
function setStatus(state) {
  pipelineState = state;
  ['running', 'loading', 'stopped'].forEach(c => $('status-chip').classList.toggle(c, c === state));
  $('status-label').textContent = state === 'running' ? 'Listening' : state === 'loading' ? 'Loading models…' : 'Stopped';
  const b = $('main-btn');
  b.textContent = state === 'running' ? 'Stop' : state === 'loading' ? 'Cancel' : 'Start Listening';
  b.classList.toggle('danger', state !== 'stopped');     // keep other classes (live-only)
  $('check-input-btn').disabled = state !== 'stopped';
  if (state !== 'running') updateLevel(0);
}
$('main-btn').onclick = () => {
  if (pipelineState !== 'stopped') send({type: 'stop'});
  else { setStatus('loading'); send({type: 'start'}); }
};

// ── Config → controls ──────────────────────────────────────
function applyConfig() {
  setSelect('src-lang-sel', cfg.source_lang);
  setSelect('tgt-lang-sel', cfg.target_lang);
  setSelect('voice-mode-sel', cfg.voice_mode);
  $('delay-input').value = ((cfg.delay_ms || 0) / 1000).toFixed(1);
  $('lag-input').value = ((cfg.fixed_lag_ms || 4000) / 1000).toFixed(1);
  renderSync();
  renderDevices();
}
function setSelect(id, v) {
  const el = $(id);
  if (v != null && [...el.options].some(o => o.value === v)) el.value = v;
}
['src-lang-sel', 'tgt-lang-sel', 'voice-mode-sel'].forEach(id => {
  $(id).addEventListener('change', () => {
    const key = {['src-lang-sel']: 'source_lang', ['tgt-lang-sel']: 'target_lang', ['voice-mode-sel']: 'voice_mode'}[id];
    cfg[key] = $(id).value;
    send({type: 'set_config', [key]: $(id).value});
    showToast('Saved');
  });
});

// ── Devices ────────────────────────────────────────────────
function devName(list, idx) { const d = (list || []).find(d => d.index === idx); return d ? d.name : null; }
function renderDevices() {
  if (!devices) return;
  const inSel = $('input-sel'), outSel = $('output-sel');
  const sys = devices.inputs.filter(d => d.kind === 'system'), mics = devices.inputs.filter(d => d.kind !== 'system');
  const opt = d => new Option(d.name + (d.default ? ' (default)' : ''), String(d.index));
  const group = (label, list) => {
    const g = document.createElement('optgroup'); g.label = label;
    list.forEach(d => g.appendChild(opt(d)));
    return g;
  };
  inSel.replaceChildren(new Option('Automatic — default speakers', ''));
  if (sys.length) inSel.appendChild(group("Computer sound (what's playing)", sys));
  if (mics.length) inSel.appendChild(group('Microphones / line-in', mics));
  outSel.replaceChildren(new Option('Automatic — default speakers', ''), ...devices.outputs.map(opt));
  inSel.value = cfg.input_device_index == null ? '' : String(cfg.input_device_index);
  outSel.value = cfg.output_device_index == null ? '' : String(cfg.output_device_index);
  if (inSel.value === '' && cfg.input_device_index != null) inSel.value = '';
  checkEcho();
}
function sameDevice(a, b) {
  if (!a || !b) return false;
  const n = s => s.toLowerCase().replace(/\s+/g, ' ').trim().slice(0, 28);   // MME truncates names
  return n(a) === n(b) || n(a).startsWith(n(b)) || n(b).startsWith(n(a));
}
function checkEcho() {
  if (!devices) return;
  const inIdx = cfg.input_device_index, outIdx = cfg.output_device_index;
  const inDev = inIdx == null ? devices.inputs.find(d => d.index === devices.default_input)
                              : devices.inputs.find(d => d.index === inIdx);
  const outName = outIdx == null ? devName(devices.outputs, devices.default_output) : devName(devices.outputs, outIdx);
  const echo = inDev && inDev.kind === 'system' && sameDevice(inDev.name, outName);
  $('echo-warn').classList.toggle('show', !!echo);
  $('input-hint').textContent = inDev && inDev.kind !== 'system'
    ? 'Microphone: translates what it hears.' : 'Pick the device your movie plays on.';
}
$('input-sel').addEventListener('change', () => {
  const v = $('input-sel').value; cfg.input_device_index = v === '' ? null : +v;
  send({type: 'set_config', input_device_index: cfg.input_device_index});
  checkEcho(); showToast('Input switched');
});
$('output-sel').addEventListener('change', () => {
  const v = $('output-sel').value; cfg.output_device_index = v === '' ? null : +v;
  send({type: 'set_config', output_device_index: cfg.output_device_index});
  checkEcho(); showToast('Output switched');
});
$('refresh-btn').onclick = () => send({type: 'refresh_devices'});
$('test-output-btn').onclick = () => send({type: 'test_output'});
$('check-input-btn').onclick = () => send({type: probeActive ? 'stop_check_input' : 'check_input'});
function renderProbe() { $('check-input-btn').textContent = probeActive ? 'Stop check' : 'Check input'; if (!probeActive) updateLevel(0); }

function updateLevel(rms) {
  const pct = Math.min(100, Math.round((rms || 0) * 600));
  const live = pct > 4;
  const bar = $('level-bar');
  bar.style.width = pct + '%';
  bar.style.background = live ? css('--good') : css('--text3');
  const db = rms > 1e-5 ? Math.round(20 * Math.log10(rms)) : null;
  $('level-val').textContent = (pipelineState === 'running' || probeActive) ? (live ? `${db} dB` : 'silent') : '–';
}

// ── Video sync ─────────────────────────────────────────────
function renderSync() {
  const mode = cfg.sync_mode || 'asap';
  document.querySelectorAll('#sync-seg button').forEach(b => b.classList.toggle('on', b.dataset.mode === mode));
  $('fixed-box').style.display = mode === 'fixed' ? '' : 'none';
  $('asap-box').style.display = mode === 'asap' ? '' : 'none';
  $('target-legend').style.display = mode === 'fixed' ? '' : 'none';
  $('sync-hint').textContent = mode === 'fixed'
    ? 'Every line is spoken the same time after the original, so you can shift your video player to match.'
    : 'Each line is spoken as soon as it is ready. Lowest delay, but it varies line to line.';
  const s = (cfg.fixed_lag_ms || 4000) / 1000;
  $('player-delay').textContent = `−${s.toFixed(3)} s   (−${Math.round(s * 1000)} ms)`;
  drawLagChart();
}
document.querySelectorAll('#sync-seg button').forEach(b => b.onclick = () => {
  cfg.sync_mode = b.dataset.mode; send({type: 'set_config', sync_mode: cfg.sync_mode}); renderSync();
});
$('lag-input').addEventListener('change', () => {
  const v = Math.max(0.5, Math.min(30, parseFloat($('lag-input').value) || 4));
  $('lag-input').value = v.toFixed(1);
  cfg.fixed_lag_ms = Math.round(v * 1000);
  send({type: 'set_config', fixed_lag_ms: cfg.fixed_lag_ms}); renderSync(); showToast('Lag set to ' + v.toFixed(1) + ' s');
});
$('delay-input').addEventListener('change', () => {
  const v = Math.max(0, Math.min(10, parseFloat($('delay-input').value) || 0));
  $('delay-input').value = v.toFixed(1);
  cfg.delay_ms = Math.round(v * 1000); send({type: 'set_config', delay_ms: cfg.delay_ms});
});
$('suggest-btn').onclick = () => {
  const ms = lastStats && lastStats.suggested_lag_ms; if (!ms) return;
  $('lag-input').value = (ms / 1000).toFixed(1); $('lag-input').dispatchEvent(new Event('change'));
};

// ── Transcript ─────────────────────────────────────────────
function speakerColor(name) {
  if (!(name in speakerMap)) speakerMap[name] = SPEAKER_COLORS[speakerCount++ % SPEAKER_COLORS.length];
  return speakerMap[name];
}
function appendCard(side, m, text, lang) {
  const box = $(side + '-transcript');
  $(side + '-empty').style.display = 'none';
  if (lang) $(side + '-lang').textContent = lang.toUpperCase();
  const color = `var(${speakerColor(m.speaker)})`;
  const div = document.createElement('div');
  div.className = 'utterance';
  if (side === 'tgt') div.dataset.lineId = m.id;
  div.innerHTML = `<div class="speaker-tag"><span class="speaker-dot" style="background:${color}"></span>${escHtml(m.speaker)}
      ${side === 'tgt' ? '<span class="utt-meta tabular" title="Waiting for timing…">…</span>' : ''}</div>
    <div class="utt-text hl" style="--spk-color:${color}"></div>`;
  div.querySelector('.utt-text').textContent = text;
  box.appendChild(div);
  while (box.children.length > 400) box.children[1].remove();    // keep the DOM light
  if (autoScroll) box.scrollTop = box.scrollHeight;
}
function handleUtterance(m) {
  if (!speakerRoster[m.speaker]) speakerRoster[m.speaker] = {name: m.speaker, utterances: 0};
  activeSpeaker = m.speaker;
  appendCard('src', m, m.src_text, m.src_lang);
  appendCard('tgt', m, m.translated, m.tgt_lang);
  renderSpeakers();
}
['src-transcript', 'tgt-transcript'].forEach(id => $(id).addEventListener('scroll', function () {
  autoScroll = this.scrollTop + this.clientHeight >= this.scrollHeight - 40;
}));
$('clear-btn').onclick = () => {
  ['src', 'tgt'].forEach(s => {
    $(s + '-transcript').querySelectorAll('.utterance').forEach(n => n.remove());
    $(s + '-empty').style.display = ''; $(s + '-lang').textContent = '—';
  });
};

// ── Metrics ────────────────────────────────────────────────
function lagStatus(s) {
  if (s == null) return {c: '--text3', t: 'No data'};
  if (s < 3) return {c: '--good', t: 'Good'};
  if (s < 5) return {c: '--warning', t: 'Noticeable'};
  if (s < 8) return {c: '--serious', t: 'High'};
  return {c: '--critical', t: 'Very high'};
}
const fmtS = v => v == null ? '–' : v.toFixed(1) + ' s';
const fmtMs = v => v == null ? '–' : v >= 1000 ? (v / 1000).toFixed(2) + ' s' : Math.round(v) + ' ms';

function handleLineMetrics(m) {
  lastLine = m;
  const card = document.querySelector(`#tgt-transcript [data-line-id="${m.id}"] .utt-meta`);
  if (card) {
    const st = lagStatus(m.lag_s);
    const parts = STAGES.map(s => `${s.label}: ${fmtMs(m.stages[s.key])}`).join('\n');
    card.innerHTML = `<span class="ov-dot" style="background:var(${st.c})"></span>${m.spoken ? 'voice' : 'text'} +${m.lag_s.toFixed(1)} s` +
      (m.late_s > 0.05 ? (cfg.sync_mode === 'fixed' ? ` · late ${m.late_s.toFixed(1)} s` : '') : '');
    card.title = `Lag behind original: ${m.lag_s.toFixed(2)} s\nReady after: ${m.ready_lag_s.toFixed(2)} s\n${parts}`;
  }
  const st = lagStatus(m.lag_s);
  $('lag-pill-val').textContent = m.lag_s.toFixed(1) + ' s';
  $('lag-pill-dot').style.background = `var(${st.c})`;
  $('lag-hero').innerHTML = `${m.lag_s.toFixed(1)}<small>s</small>`;
  $('lag-status').innerHTML = `<span class="ov-dot" style="background:var(${st.c})"></span><span>${st.t}</span>`;
  renderStages();
}

function handleStats(s) {
  lastStats = s;
  const sys = s.system || {};
  $('s-gpu').textContent = sys.gpu_name || 'No NVIDIA GPU detected';
  $('s-gpu-util').textContent = sys.gpu_util != null ? sys.gpu_util + ' %' : '–';
  $('s-gpu-bar').style.width = (sys.gpu_util || 0) + '%';
  if (sys.vram_total_gb) {
    const pct = 100 * sys.vram_used_gb / sys.vram_total_gb;
    $('s-vram').textContent = `${sys.vram_used_gb.toFixed(1)} / ${sys.vram_total_gb.toFixed(1)} GB`;
    $('s-vram-bar').style.width = pct + '%';
    $('s-vram-bar').style.background = pct > 92 ? css('--critical') : css('--series-1');
  }
  $('s-temp').textContent = sys.gpu_temp_c != null ? sys.gpu_temp_c + ' °C' : '–';
  $('s-cpu').textContent = sys.cpu_pct != null ? Math.round(sys.cpu_pct) + ' %' : '–';
  $('s-ram').textContent = sys.ram_used_gb != null ? sys.ram_used_gb.toFixed(1) + ' GB' : '–';
  $('s-in').textContent = s.input_device || '–';
  $('s-out').textContent = s.output_device || '–';
  if (s.sync_mode && s.sync_mode !== cfg.sync_mode) { cfg.sync_mode = s.sync_mode; renderSync(); }
  if (!s.lag) return;                                     // idle: system stats only

  $('lag-avg').textContent = fmtS(s.lag.avg);
  $('lag-p95').textContent = fmtS(s.lag.p95);
  $('lag-range').textContent = s.lag.min == null ? '–' : `${s.lag.min.toFixed(1)}–${s.lag.max.toFixed(1)}`;
  $('t-rtf').textContent = s.rtf_avg == null ? '–' : s.rtf_avg.toFixed(2) + '×';
  $('t-rtf').style.color = s.rtf_avg == null ? '' : s.rtf_avg < 1 ? '' : css('--serious');
  $('t-rtf-s').textContent = s.rtf_avg == null ? 'below 1.0 keeps up' : s.rtf_avg < 1 ? 'keeping up with real time' : 'falling behind real time';
  const resp = lastLine ? lastLine.response_s : null;
  $('t-resp').textContent = fmtS(resp);
  $('t-backlog').textContent = fmtS(s.backlog_s);
  $('t-queue').textContent = `queue: ${s.queue_depth} line${s.queue_depth === 1 ? '' : 's'} waiting`;
  $('t-lines').textContent = s.lines_total;
  const extra = [];
  if (s.sync_mode === 'fixed') extra.push(`${s.lines_late} late`);
  if (s.segments_dropped) extra.push(`${s.segments_dropped} dropped`);
  if (s.errors) extra.push(`${s.errors} errors`);
  extra.push(`${s.lines_spoken} spoken`);
  $('t-lines-s').textContent = extra.join(' · ');

  const sug = s.suggested_lag_ms;
  $('suggest-btn').disabled = !sug;
  $('suggest-btn').textContent = sug ? `Use ${(sug / 1000).toFixed(1)} s` : 'Use suggested';
  $('suggest-hint').textContent = sug
    ? `About 95% of recent lines were ready within ${(s.ready_p95 || 0).toFixed(1)} s.`
    : 'Start listening for a few lines to get a suggestion.';
  lagHistory = s.history || [];
  renderStages();
  drawLagChart();
}

function renderStages() {
  const nums = o => o ? Object.fromEntries(STAGES.map(s => [s.key, Number(o[s.key]) || 0])) : null;
  const avg = nums(lastStats && lastStats.stages_avg);
  const last = nums(lastLine && lastLine.stages);
  const sum = o => o ? STAGES.reduce((a, s) => a + o[s.key], 0) : 0;
  const lastTotal = sum(last), avgTotal = sum(avg);
  // stacked bar = the last line's lag, split into its parts
  $('stage-stack').replaceChildren(...(lastTotal ? STAGES.filter(s => last[s.key] > 0).map(s => {
    const seg = document.createElement('div');
    seg.style.flexGrow = last[s.key];
    seg.style.background = `var(${s.color})`;
    seg.title = `${s.label}: ${fmtMs(last[s.key])}`;
    return seg;
  }) : []));
  $('stage-rows').innerHTML = STAGES.map(s => `<tr title="${s.tip}">
      <td><i class="swatch" style="background:var(${s.color});margin-right:6px"></i>${s.label}</td>
      <td class="n">${last ? fmtMs(last[s.key]) : '–'}</td>
      <td class="n">${avgTotal ? fmtMs(avg[s.key]) : '–'}</td></tr>`).join('') +
    `<tr><td style="color:var(--text)"><b>Lag</b></td>
      <td class="n"><b>${lastTotal ? fmtMs(lastTotal) : '–'}</b></td>
      <td class="n"><b>${avgTotal ? fmtMs(avgTotal) : '–'}</b></td></tr>`;
}

// ── Lag chart (canvas) ─────────────────────────────────────
const chart = {pts: [], x0: 0, w: 0, h: 0};
function drawLagChart() {
  const cv = $('lag-chart');
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W) return;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext('2d'); g.scale(dpr, dpr); g.clearRect(0, 0, W, H);
  const pad = {l: 30, r: 6, t: 6, b: 16};
  const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
  const target = cfg.sync_mode === 'fixed' ? (cfg.fixed_lag_ms || 0) / 1000 : null;
  const data = lagHistory;
  let ymax = Math.max(2, target || 0, ...data.map(d => Math.max(d.lag, d.ready)));
  ymax = Math.ceil(ymax / 2) * 2;
  const y = v => pad.t + ph - (v / ymax) * ph;
  const x = i => pad.l + (data.length <= 1 ? pw / 2 : (i / (data.length - 1)) * pw);
  // grid + axis labels
  g.font = '10px Segoe UI, sans-serif'; g.fillStyle = css('--text3'); g.strokeStyle = css('--border'); g.lineWidth = 1;
  for (let v = 0; v <= ymax; v += ymax / 2) {
    g.beginPath(); g.moveTo(pad.l, Math.round(y(v)) + .5); g.lineTo(W - pad.r, Math.round(y(v)) + .5); g.stroke();
    g.fillText(v + ' s', 2, y(v) + 3);
  }
  g.fillText(data.length ? `last ${data.length} lines` : 'no lines yet', pad.l, H - 3);
  if (target) {
    g.setLineDash([4, 4]); g.strokeStyle = css('--text2'); g.beginPath();
    g.moveTo(pad.l, y(target)); g.lineTo(W - pad.r, y(target)); g.stroke(); g.setLineDash([]);
  }
  const line = (key, color) => {
    if (!data.length) return;
    g.strokeStyle = color; g.lineWidth = 2; g.lineJoin = 'round'; g.beginPath();
    data.forEach((d, i) => i ? g.lineTo(x(i), y(d[key])) : g.moveTo(x(i), y(d[key]))); g.stroke();
    const i = data.length - 1;                              // emphasise the latest point
    g.fillStyle = color; g.strokeStyle = css('--surface'); g.lineWidth = 2;
    g.beginPath(); g.arc(x(i), y(data[i][key]), 4, 0, 7); g.fill(); g.stroke();
  };
  line('ready', css('--series-2'));
  line('lag', css('--series-1'));
  chart.pts = data.map((d, i) => ({x: x(i), d}));
}
$('lag-chart').addEventListener('mousemove', e => {
  const tip = $('lag-tip'); if (!chart.pts.length) return;
  const r = e.currentTarget.getBoundingClientRect(), mx = e.clientX - r.left;
  const p = chart.pts.reduce((a, b) => Math.abs(b.x - mx) < Math.abs(a.x - mx) ? b : a);
  tip.style.display = 'block';
  tip.innerHTML = `Line #${p.d.id}<br>Lag <b>${p.d.lag.toFixed(2)} s</b><br>Ready ${p.d.ready.toFixed(2)} s`;
  tip.style.left = Math.min(p.x + 8, r.width - tip.offsetWidth - 2) + 'px'; tip.style.top = '4px';
});
$('lag-chart').addEventListener('mouseleave', () => $('lag-tip').style.display = 'none');
window.addEventListener('resize', drawLagChart);

// ── Speakers ───────────────────────────────────────────────
function handleSpeakers(speakers, extra) {
  if (extra && extra.renamed) {
    const {from, to} = extra.renamed;
    if (from in speakerMap && !(to in speakerMap)) speakerMap[to] = speakerMap[from];
  }
  speakerRoster = {};
  for (const [name, info] of Object.entries(speakers || {})) speakerRoster[name] = {name, utterances: info.utterances || 0};
  renderSpeakers();
}
function renderSpeakers() {
  const list = $('speakers-list');
  const names = Object.keys(speakerRoster);
  list.innerHTML = names.length ? '' : '<div class="speakers-empty">No speakers detected yet.</div>';
  for (const name of names) {
    const info = speakerRoster[name], color = `var(${speakerColor(name)})`;
    const row = document.createElement('div');
    row.className = 'speaker-row' + (name === activeSpeaker ? ' active' : '');
    row.innerHTML = `<div class="speaker-pill"><span class="speaker-pill-dot" style="background:${color};--dot-color:${color}"></span>
        <span class="speaker-pill-name"></span></div>
      <span class="speaker-meta">${info.utterances} line${info.utterances === 1 ? '' : 's'}</span>
      <button class="btn-sm">Rename</button>`;
    row.querySelector('.speaker-pill-name').textContent = name;
    row.querySelector('button').onclick = () => startRename(row, name);
    list.appendChild(row);
  }
}
function startRename(row, name) {
  row.innerHTML = `<span class="speaker-pill-dot" style="background:var(${speakerColor(name)})"></span>
    <div class="rename-form"><input class="rename-input" maxlength="60"><button class="btn-sm apply">Save</button><button class="btn-sm">Cancel</button></div>`;
  const input = row.querySelector('input'), [save, cancel] = row.querySelectorAll('button');
  input.value = name;
  const commit = () => {
    const v = input.value.trim();
    if (!v || v === name) return renderSpeakers();
    send({type: 'rename_speaker', speaker_id: name, name: v});
    showToast(v in speakerRoster ? `Merged into "${v}"` : `Renamed to "${v}"`);
  };
  input.onkeydown = e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') renderSpeakers(); };
  save.onclick = commit; cancel.onclick = renderSpeakers;
  input.focus(); input.select();
}
$('forget-all-btn').onclick = () => {
  const b = $('forget-all-btn');
  if (!Object.keys(speakerRoster).length) return;
  if (b.dataset.armed !== '1') {           // two-step confirm, no blocking dialog
    b.dataset.armed = '1'; b.textContent = 'Click again to confirm';
    setTimeout(() => { b.dataset.armed = ''; b.textContent = 'Forget all'; }, 3000);
    return;
  }
  b.dataset.armed = ''; b.textContent = 'Forget all';
  send({type: 'reset_speakers'});
};

// ── Panels / tabs ──────────────────────────────────────────
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tabs button').forEach(x => x.classList.toggle('on', x === b));
  $('tab-perf').hidden = b.dataset.tab !== 'perf';
  $('tab-spk').hidden = b.dataset.tab !== 'spk';
  if (b.dataset.tab === 'perf') drawLagChart();
});
const narrow = () => window.matchMedia('(max-width: 1250px)').matches;
$('left-btn').onclick = () => {
  const L = $('layout');
  if (narrow()) { L.classList.remove('show-right'); $('right-btn').classList.remove('active'); $('left-btn').classList.add('active'); return; }
  L.classList.toggle('no-left'); $('left-btn').classList.toggle('active', !L.classList.contains('no-left')); setTimeout(drawLagChart, 0);
};
$('right-btn').onclick = () => {
  const L = $('layout');
  if (narrow()) { L.classList.toggle('show-right'); const on = L.classList.contains('show-right');
    $('right-btn').classList.toggle('active', on); $('left-btn').classList.toggle('active', !on); setTimeout(drawLagChart, 0); return; }
  L.classList.toggle('no-right'); $('right-btn').classList.toggle('active', !L.classList.contains('no-right')); setTimeout(drawLagChart, 0);
};

// ── Helpers ────────────────────────────────────────────────
function setLog(msg) { $('log-strip').textContent = msg; }
function showToast(msg, dur = 2000) {
  const t = $('toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(t._timer); t._timer = setTimeout(() => t.classList.remove('show'), dur);
}
function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

renderStages();
renderSync();
connect();

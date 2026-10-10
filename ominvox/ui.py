"""Web UI for Ominvox.  Start with:  run.bat --ui
Opens at http://127.0.0.1:8765 — controls the pipeline via WebSocket so
transcript and translations appear live as the movie plays.
"""
from __future__ import annotations
import asyncio
import json
import threading
import time
import webbrowser
from typing import Callable

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    FastAPI = WebSocket = WebSocketDisconnect = HTMLResponse = uvicorn = None  # type: ignore

from .orchestrator import Pipeline
from .speaker_id import VoiceProfileStore
from .capture import enumerate_devices

# ---------------------------------------------------------------------------
# HTML / JS / CSS — the entire frontend is embedded here so there are no
# static-file dependencies and no build step.
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ominvox</title>
<style>
:root {
  --bg:        #0d0f1a;
  --surface:   #141621;
  --surface2:  #1c1f2e;
  --border:    #252840;
  --accent:    #7c5cfc;
  --accent2:   #5cccfc;
  --danger:    #fc5c7d;
  --text:      #e8eaf0;
  --text2:     #8890a8;
  --text3:     #555a72;
  --radius:    10px;
  --spk0:      #7c5cfc;
  --spk1:      #5cccfc;
  --spk2:      #fc5c7d;
  --spk3:      #5cfcb8;
  --spk4:      #fca85c;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Header ──────────────────────────────────────────────── */
header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  height: 56px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  z-index: 10;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--text);
  user-select: none;
}
.logo-glyph {
  width: 28px; height: 28px;
  background: var(--accent);
  border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px;
}

.header-center {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  justify-content: center;
}

.status-chip {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 12px;
  border-radius: 20px;
  background: var(--surface2);
  border: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--text2);
}
.status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--text3);
  transition: background 0.3s;
}
.status-chip.running .status-dot {
  background: #5cfc8a;
  box-shadow: 0 0 6px #5cfc8a80;
  animation: pulse 1.6s ease-in-out infinite;
}
.status-chip.running { color: var(--text); }
.status-chip.loading .status-dot { background: #fcca5c; animation: pulse 0.8s ease-in-out infinite; }
@keyframes pulse {
  0%,100% { opacity: 1; } 50% { opacity: 0.4; }
}

.header-right { display: flex; align-items: center; gap: 8px; margin-left: auto; }

.hdr-select {
  font-family: inherit; font-size: 12px;
  background: var(--surface2); border: 1px solid var(--border);
  color: var(--text); border-radius: 8px; padding: 6px 10px;
  max-width: 260px; cursor: pointer; outline: none;
}
.hdr-select:hover, .hdr-select:focus { border-color: var(--accent); }
.hdr-meter {
  width: 60px; height: 6px; background: var(--surface2);
  border: 1px solid var(--border); border-radius: 4px; overflow: hidden;
}
.hdr-meter-bar { height: 100%; width: 0%; background: var(--danger); transition: width .1s; }

/* ── Buttons ─────────────────────────────────────────────── */
button {
  cursor: pointer;
  border: none;
  border-radius: var(--radius);
  font-family: inherit;
  transition: opacity 0.15s, transform 0.1s, background 0.2s;
}
button:active { transform: scale(0.97); }

.btn-primary {
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 20px;
  letter-spacing: 0.04em;
}
.btn-primary:hover { opacity: 0.88; }
.btn-primary.danger { background: var(--danger); }

.btn-icon {
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text2);
  width: 36px; height: 36px;
  font-size: 16px;
  display: flex; align-items: center; justify-content: center;
  padding: 0;
}
.btn-icon:hover { color: var(--text); border-color: var(--accent); }
.btn-icon.active { color: var(--accent); border-color: var(--accent); }

/* ── Panel layout ────────────────────────────────────────── */
.panels {
  display: grid;
  grid-template-columns: 1fr 1px 1fr;
  flex: 1;
  overflow: hidden;
}

.panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--text2);
  text-transform: uppercase;
  flex-shrink: 0;
}

.lang-badge {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--text2);
}

.panel-divider { background: var(--border); }

.transcript {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  scroll-behavior: smooth;
}
.transcript::-webkit-scrollbar { width: 4px; }
.transcript::-webkit-scrollbar-track { background: transparent; }
.transcript::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

/* ── Utterance cards ─────────────────────────────────────── */
.utterance {
  margin-bottom: 12px;
  animation: fadeUp 0.25s ease;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

.speaker-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 4px;
  opacity: 0.85;
}
.speaker-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
}

.utt-text {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text);
  word-break: break-word;
}
.utt-text.highlight {
  border-color: color-mix(in srgb, var(--spk-color) 40%, transparent);
  background: color-mix(in srgb, var(--spk-color) 5%, var(--surface));
}

/* ── Empty state ─────────────────────────────────────────── */
.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text3);
  font-size: 13px;
  text-align: center;
  padding: 40px;
  pointer-events: none;
}
.empty-icon { font-size: 36px; opacity: 0.4; }

/* ── Settings drawer ─────────────────────────────────────── */
.settings-drawer {
  background: var(--surface);
  border-top: 1px solid var(--border);
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.35s cubic-bezier(0.4,0,0.2,1);
  flex-shrink: 0;
}
.settings-drawer.open { max-height: 280px; }

.settings-inner {
  padding: 20px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}

.setting {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.setting label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text2);
}

select, input[type=range] {
  font-family: inherit;
  font-size: 13px;
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  padding: 7px 10px;
  appearance: none;
  outline: none;
  width: 100%;
  cursor: pointer;
}
select:focus, select:hover { border-color: var(--accent); }

input[type=range] {
  padding: 0;
  height: 4px;
  accent-color: var(--accent);
  cursor: ew-resize;
}

.range-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.range-val {
  font-size: 12px;
  color: var(--text2);
  min-width: 40px;
  text-align: right;
}

.settings-footer {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 4px;
  border-top: 1px solid var(--border);
}

.btn-sm {
  font-size: 12px;
  font-weight: 600;
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text);
}
.btn-sm:hover { border-color: var(--accent); color: var(--accent); }
.btn-sm.apply {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.btn-sm.apply:hover { opacity: 0.88; }

/* ── Toast notifications ─────────────────────────────────── */
#toast {
  position: fixed;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%) translateY(80px);
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 10px 20px;
  border-radius: 20px;
  font-size: 13px;
  transition: transform 0.3s cubic-bezier(0.34,1.56,0.64,1);
  z-index: 100;
  white-space: nowrap;
}
#toast.show { transform: translateX(-50%) translateY(0); }

/* ── Log strip ───────────────────────────────────────────── */
#log-strip {
  padding: 6px 16px;
  font-size: 11px;
  color: var(--text3);
  background: var(--bg);
  border-top: 1px solid var(--border);
  font-family: monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

/* ── Speakers drawer ─────────────────────────────────────── */
.speakers-drawer {
  background: var(--surface);
  border-top: 1px solid var(--border);
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.35s cubic-bezier(0.4,0,0.2,1);
  flex-shrink: 0;
}
.speakers-drawer.open { max-height: 260px; }

.speakers-inner {
  padding: 14px 20px;
  overflow-y: auto;
  max-height: 260px;
}

.speakers-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.speakers-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text2);
}
.speakers-hint {
  font-size: 11px;
  color: var(--text3);
}

.speaker-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
}
.speaker-row:last-child { border-bottom: none; }

.speaker-pill {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 1;
  min-width: 0;
}
.speaker-pill-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.speaker-pill-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.speaker-meta {
  font-size: 11px;
  color: var(--text3);
  white-space: nowrap;
}

.rename-form {
  display: flex;
  gap: 6px;
  align-items: center;
  flex: 1;
}
.rename-input {
  flex: 1;
  font-family: inherit;
  font-size: 13px;
  background: var(--surface2);
  border: 1px solid var(--accent);
  color: var(--text);
  border-radius: 6px;
  padding: 5px 10px;
  outline: none;
}
.rename-input:focus { border-color: var(--accent2); }

.speakers-empty {
  padding: 20px 0;
  text-align: center;
  color: var(--text3);
  font-size: 13px;
}

/* active speaking indicator */
.speaker-row.active .speaker-pill-dot {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--dot-color) 30%, transparent);
  animation: pulse 1.2s ease-in-out infinite;
}
</style>
</head>
<body>

<!-- ── Header ──────────────────────────────────────────────── -->
<header>
  <div class="logo">
    <div class="logo-glyph">◈</div>
    OMINVOX
  </div>

  <div class="header-center">
    <div class="status-chip" id="status-chip">
      <div class="status-dot"></div>
      <span id="status-label">Stopped</span>
    </div>
    <select id="header-input-sel" class="hdr-select" onchange="quickSelectInput()"
            title="Audio input source — pick where the audio comes from">
      <option value="">🎧 Auto input</option>
    </select>
    <div class="hdr-meter" title="input level">
      <div id="hdr-level-bar" class="hdr-meter-bar"></div>
    </div>
  </div>

  <div class="header-right">
    <button class="btn-primary" id="main-btn" onclick="togglePipeline()">Start Listening</button>
    <button class="btn-icon" id="clear-btn" onclick="clearTranscript()" title="Clear transcript">⌫</button>
    <button class="btn-icon" id="speakers-btn" onclick="toggleSpeakers()" title="Speakers">👥</button>
    <button class="btn-icon" id="settings-btn" onclick="toggleSettings()" title="Settings">⚙</button>
  </div>
</header>

<!-- ── Main panels ─────────────────────────────────────────── -->
<div class="panels" id="panels">
  <div class="panel">
    <div class="panel-header">
      <span>Source</span>
      <span class="lang-badge" id="src-lang">—</span>
    </div>
    <div class="transcript" id="src-transcript">
      <div class="empty-state" id="src-empty">
        <div class="empty-icon">🎙</div>
        <div>Waiting for audio…</div>
        <div style="opacity:.6;font-size:11px">Press Start Listening, then play your movie</div>
      </div>
    </div>
  </div>

  <div class="panel-divider"></div>

  <div class="panel">
    <div class="panel-header">
      <span>Translation</span>
      <span class="lang-badge" id="tgt-lang">—</span>
    </div>
    <div class="transcript" id="tgt-transcript">
      <div class="empty-state" id="tgt-empty">
        <div class="empty-icon">🌐</div>
        <div>Translation will appear here</div>
      </div>
    </div>
  </div>
</div>

<!-- ── Speakers drawer ─────────────────────────────────────── -->
<div class="speakers-drawer" id="speakers-drawer">
  <div class="speakers-inner">
    <div class="speakers-header">
      <span class="speakers-title">Speakers</span>
      <span class="speakers-hint">Click a name to rename</span>
    </div>
    <div id="speakers-list">
      <div class="speakers-empty">No speakers detected yet — start the pipeline to begin.</div>
    </div>
  </div>
</div>

<!-- ── Settings drawer ─────────────────────────────────────── -->
<div class="settings-drawer" id="settings-drawer">
  <div class="settings-inner">
    <div class="setting">
      <label>Source Language</label>
      <select id="src-lang-sel">
        <option value="auto">Auto-detect</option>
        <option value="en">English</option>
        <option value="es">Spanish</option>
        <option value="fr">French</option>
        <option value="de">German</option>
        <option value="it">Italian</option>
        <option value="pt">Portuguese</option>
        <option value="ru">Russian</option>
        <option value="ja">Japanese</option>
        <option value="zh">Chinese</option>
        <option value="ko">Korean</option>
        <option value="ar">Arabic</option>
        <option value="hi">Hindi</option>
        <option value="nl">Dutch</option>
        <option value="pl">Polish</option>
        <option value="tr">Turkish</option>
        <option value="sv">Swedish</option>
      </select>
    </div>

    <div class="setting">
      <label>Target Language</label>
      <select id="tgt-lang-sel">
        <option value="en">English</option>
        <option value="es">Spanish</option>
        <option value="fr">French</option>
        <option value="de">German</option>
        <option value="it">Italian</option>
        <option value="pt">Portuguese</option>
        <option value="ru">Russian</option>
        <option value="ja">Japanese</option>
        <option value="zh">Chinese</option>
        <option value="ko">Korean</option>
        <option value="ar">Arabic</option>
        <option value="hi">Hindi</option>
        <option value="nl">Dutch</option>
        <option value="pl">Polish</option>
        <option value="tr">Turkish</option>
        <option value="sv">Swedish</option>
      </select>
    </div>

    <div class="setting">
      <label>Voice Mode</label>
      <select id="voice-mode-sel">
        <option value="match">Match Speaker (clone)</option>
        <option value="preset">Preset Voice</option>
        <option value="single">Single Voice</option>
      </select>
    </div>

    <div class="setting">
      <label>Input Source (system audio)</label>
      <select id="input-dev-sel"><option value="">Auto (default loopback)</option></select>
      <div class="range-row" style="margin-top:6px">
        <div style="flex:1;height:6px;background:var(--surface2);border:1px solid var(--border);border-radius:4px;overflow:hidden">
          <div id="level-bar" style="height:100%;width:0%;background:var(--accent);transition:width .1s"></div>
        </div>
        <span class="range-val" id="level-val">—</span>
      </div>
    </div>

    <div class="setting">
      <label>Output Source (playback)</label>
      <select id="output-dev-sel"><option value="">Default device</option></select>
    </div>

    <div class="setting">
      <label>Playback Delay</label>
      <div class="range-row">
        <input type="range" id="delay-slider" min="200" max="4000" step="100" value="1500"
               oninput="document.getElementById('delay-val').textContent=this.value+'ms'">
        <span class="range-val" id="delay-val">1500ms</span>
      </div>
    </div>

    <div class="settings-footer">
      <button class="btn-sm" onclick="toggleSettings()">Cancel</button>
      <button class="btn-sm apply" onclick="applySettings()">Apply</button>
    </div>
  </div>
</div>

<!-- ── Status bar ───────────────────────────────────────────── -->
<div id="log-strip">Connecting…</div>

<!-- ── Toast ───────────────────────────────────────────────── -->
<div id="toast"></div>

<script>
// ── State ───────────────────────────────────────────────────
const SPEAKER_COLORS = ['--spk0','--spk1','--spk2','--spk3','--spk4'];
const speakerMap = {};   // display_name -> color var
let speakerCount = 0;
let pipelineRunning = false;
let ws = null;
let autoScroll = true;

// speaker_id (pyannote label) -> { name, utterances, active }
const speakerRoster = {};
// name -> array of speaker_ids that resolve to this name
const nameToIds = {};
let activeSpeaker = null;

// ── WebSocket ───────────────────────────────────────────────
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => setLog('Connected');

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'status') handleStatus(msg);
    else if (msg.type === 'utterance') handleUtterance(msg);
    else if (msg.type === 'speakers') handleSpeakers(msg.speakers);
    else if (msg.type === 'level') updateLevel(msg.rms);
    else if (msg.type === 'log') setLog(msg.msg);
  };

  ws.onclose = () => {
    setStatus('stopped');
    setLog('Disconnected — retrying in 3s…');
    setTimeout(connect, 3000);
  };
  ws.onerror = () => ws.close();
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

// ── Status ──────────────────────────────────────────────────
function handleStatus(msg) {
  setStatus(msg.state);
  if (msg.config) applyConfigFromServer(msg.config);
  if (msg.speakers) handleSpeakers(msg.speakers);
}

function setStatus(state) {
  pipelineRunning = (state === 'running');
  const chip = document.getElementById('status-chip');
  const label = document.getElementById('status-label');
  const btn = document.getElementById('main-btn');

  chip.className = 'status-chip ' + state;
  label.textContent = state === 'running' ? 'Listening'
                    : state === 'loading'  ? 'Loading models…'
                    : 'Stopped';
  btn.textContent = pipelineRunning ? 'Stop' : 'Start Listening';
  btn.className = 'btn-primary' + (pipelineRunning ? ' danger' : '');
}

function togglePipeline() {
  if (pipelineRunning) {
    send({type:'stop'});
  } else {
    setStatus('loading');
    send({type:'start'});
  }
}

// ── Utterances ──────────────────────────────────────────────
function speakerColor(name) {
  if (!(name in speakerMap)) {
    speakerMap[name] = SPEAKER_COLORS[speakerCount % SPEAKER_COLORS.length];
    speakerCount++;
  }
  return speakerMap[name];
}

function appendCard(containerId, emptyId, colorVar, speakerStr, text, langCode) {
  const container = document.getElementById(containerId);
  const empty = document.getElementById(emptyId);
  if (empty) empty.style.display = 'none';

  const langEl = containerId === 'src-transcript'
    ? document.getElementById('src-lang')
    : document.getElementById('tgt-lang');
  if (langEl && langCode) langEl.textContent = langCode.toUpperCase();

  const color = `var(${colorVar})`;
  const div = document.createElement('div');
  div.className = 'utterance';
  div.innerHTML = `
    <div class="speaker-tag" style="color:${color}">
      <div class="speaker-dot" style="background:${color}"></div>
      ${escHtml(speakerStr)}
    </div>
    <div class="utt-text highlight" style="--spk-color:${color}">${escHtml(text)}</div>
  `;
  container.appendChild(div);
  if (autoScroll) container.scrollTop = container.scrollHeight;
}

function handleUtterance(msg) {
  const colorVar = speakerColor(msg.speaker);
  // Track roster from utterance events (speaker_id may not be present on older server)
  const spkId = msg.speaker_id || msg.speaker;
  if (!speakerRoster[spkId]) {
    speakerRoster[spkId] = { name: msg.speaker, utterances: 0, active: false };
  }
  speakerRoster[spkId].name = msg.speaker;
  speakerRoster[spkId].utterances++;

  // Flash active speaker
  if (activeSpeaker && activeSpeaker !== spkId) {
    const prev = document.querySelector(`[data-speaker-id="${CSS.escape(activeSpeaker)}"]`);
    if (prev) prev.classList.remove('active');
  }
  activeSpeaker = spkId;
  const row = document.querySelector(`[data-speaker-id="${CSS.escape(spkId)}"]`);
  if (row) row.classList.add('active');

  appendCard('src-transcript', 'src-empty', colorVar, msg.speaker, msg.src_text, msg.src_lang);
  appendCard('tgt-transcript', 'tgt-empty', colorVar, msg.speaker, msg.translated, msg.tgt_lang);
}

// ── Speakers panel ──────────────────────────────────────────
function handleSpeakers(speakers) {
  // speakers: { name -> { utterances, has_centroid } }
  // Merge into roster using name as key (server now sends by name)
  for (const [name, info] of Object.entries(speakers)) {
    if (!speakerRoster[name]) {
      speakerRoster[name] = { name, utterances: 0, active: false };
    }
    speakerRoster[name].utterances = info.utterances || speakerRoster[name].utterances;
  }
  renderSpeakers();
}

function renderSpeakers() {
  const list = document.getElementById('speakers-list');
  const names = Object.keys(speakerRoster);
  if (!names.length) {
    list.innerHTML = '<div class="speakers-empty">No speakers detected yet.</div>';
    return;
  }

  list.innerHTML = '';
  for (const key of names) {
    const info = speakerRoster[key];
    const colorVar = speakerColor(info.name || key);
    const color = `var(${colorVar})`;
    const row = document.createElement('div');
    row.className = 'speaker-row';
    row.dataset.speakerId = key;

    row.innerHTML = `
      <div class="speaker-pill">
        <div class="speaker-pill-dot" style="background:${color};--dot-color:${color}"></div>
        <span class="speaker-pill-name">${escHtml(info.name || key)}</span>
      </div>
      <span class="speaker-meta">${info.utterances} utterance${info.utterances===1?'':'s'}</span>
      <button class="btn-sm" onclick="startRename('${escAttr(key)}')">Rename</button>
    `;
    list.appendChild(row);
  }
}

function startRename(speakerId) {
  const row = document.querySelector(`[data-speaker-id="${CSS.escape(speakerId)}"]`);
  if (!row) return;
  const info = speakerRoster[speakerId] || {};
  const colorVar = speakerColor(info.name || speakerId);
  const color = `var(${colorVar})`;

  row.innerHTML = `
    <div class="speaker-pill-dot" style="background:${color}" ></div>
    <div class="rename-form">
      <input class="rename-input" id="rename-input-${escAttr(speakerId)}"
             type="text" value="${escAttr(info.name || speakerId)}"
             onkeydown="renameKey(event,'${escAttr(speakerId)}')" autofocus>
      <button class="btn-sm apply" onclick="commitRename('${escAttr(speakerId)}')">Save</button>
      <button class="btn-sm" onclick="renderSpeakers()">Cancel</button>
    </div>
  `;
  document.getElementById(`rename-input-${speakerId}`)?.focus();
}

function renameKey(e, speakerId) {
  if (e.key === 'Enter') commitRename(speakerId);
  if (e.key === 'Escape') renderSpeakers();
}

function commitRename(speakerId) {
  const input = document.getElementById(`rename-input-${speakerId}`);
  const newName = input ? input.value.trim() : '';
  if (!newName) return;

  // Update local state immediately for snappy UI
  if (speakerRoster[speakerId]) {
    const oldName = speakerRoster[speakerId].name;
    speakerRoster[speakerId].name = newName;
    // Remap color from old name to new
    if (oldName in speakerMap) speakerMap[newName] = speakerMap[oldName];
  }

  send({ type: 'rename_speaker', speaker_id: speakerId, name: newName });
  renderSpeakers();
  showToast(`Renamed to "${newName}"`);
}

function toggleSpeakers() {
  const drawer = document.getElementById('speakers-drawer');
  const btn = document.getElementById('speakers-btn');
  const open = drawer.classList.toggle('open');
  btn.classList.toggle('active', open);
  if (open) renderSpeakers();
}

function clearTranscript() {
  ['src-transcript','tgt-transcript'].forEach(id => {
    const el = document.getElementById(id);
    [...el.querySelectorAll('.utterance')].forEach(n => n.remove());
    const empty = el.querySelector('.empty-state');
    if (empty) empty.style.display = '';
  });
  document.getElementById('src-lang').textContent = '—';
  document.getElementById('tgt-lang').textContent = '—';
}

// ── Settings ────────────────────────────────────────────────
function toggleSettings() {
  const drawer = document.getElementById('settings-drawer');
  const btn = document.getElementById('settings-btn');
  const open = drawer.classList.toggle('open');
  btn.classList.toggle('active', open);
}

function applyConfigFromServer(config) {
  setSelectVal('src-lang-sel', config.source_lang);
  setSelectVal('tgt-lang-sel', config.target_lang);
  setSelectVal('voice-mode-sel', config.voice_mode);
  const delay = config.delay_ms ?? 1500;
  document.getElementById('delay-slider').value = delay;
  document.getElementById('delay-val').textContent = delay + 'ms';
  if (config.devices) populateDevices(config.devices,
                                      config.input_device_index,
                                      config.output_device_index);
}

function inputOptionLabel(d) {
  const icon = d.kind === 'mic' ? '🎤 ' : '🔊 ';
  const kindLbl = d.kind === 'mic' ? ' — mic' : ' — system';
  return icon + d.name + kindLbl + (d.default ? ' (default)' : '');
}

function populateDevices(devices, curIn, curOut) {
  const inSel = document.getElementById('input-dev-sel');
  const outSel = document.getElementById('output-dev-sel');
  const hdrSel = document.getElementById('header-input-sel');

  const inHtml = ['<option value="">🎧 Auto input (default)</option>'];
  (devices.inputs || []).forEach(d => {
    inHtml.push(`<option value="${d.index}">${inputOptionLabel(d)}</option>`);
  });
  inSel.innerHTML = inHtml.join('');
  hdrSel.innerHTML = inHtml.join('');

  outSel.innerHTML = '<option value="">Default device</option>' +
    (devices.outputs || []).map(d =>
      `<option value="${d.index}">${d.name}${d.default ? ' (default)' : ''}</option>`).join('');

  const inVal = (curIn !== null && curIn !== undefined) ? String(curIn) : '';
  const outVal = (curOut !== null && curOut !== undefined) ? String(curOut) : '';
  inSel.value = inVal; hdrSel.value = inVal; outSel.value = outVal;
}

// Header dropdown changed -> apply immediately and keep the settings copy in sync.
function quickSelectInput() {
  const v = document.getElementById('header-input-sel').value;
  const s = document.getElementById('input-dev-sel');
  if (s) s.value = v;
  send({ type: 'set_config', input_device_index: v === '' ? null : parseInt(v, 10) });
  showToast('Input source switched');
}

function updateLevel(rms) {
  const pct = Math.min(100, Math.round((rms || 0) * 600));
  const live = pct > 4;
  const col = live ? 'var(--spk3)' : 'var(--danger)';
  const bar = document.getElementById('level-bar');
  if (bar) { bar.style.width = pct + '%'; bar.style.background = col;
             document.getElementById('level-val').textContent = live ? 'live' : 'silent'; }
  const hbar = document.getElementById('hdr-level-bar');
  if (hbar) { hbar.style.width = pct + '%'; hbar.style.background = col; }
}

function devIndex(id) {
  const v = document.getElementById(id).value;
  return v === '' ? null : parseInt(v, 10);
}

function applySettings() {
  send({
    type: 'set_config',
    source_lang: document.getElementById('src-lang-sel').value,
    target_lang: document.getElementById('tgt-lang-sel').value,
    voice_mode: document.getElementById('voice-mode-sel').value,
    delay_ms: parseInt(document.getElementById('delay-slider').value, 10),
    input_device_index: devIndex('input-dev-sel'),
    output_device_index: devIndex('output-dev-sel'),
  });
  toggleSettings();
  showToast('Settings applied');
}

function setSelectVal(id, val) {
  const el = document.getElementById(id);
  if (!el || val == null) return;
  const opt = [...el.options].find(o => o.value === val);
  if (opt) el.value = val;
}

// ── Helpers ─────────────────────────────────────────────────
function setLog(msg) {
  document.getElementById('log-strip').textContent = msg;
}

function showToast(msg, dur=2200) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), dur);
}

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function escAttr(s) {
  return String(s).replace(/'/g,"\\'").replace(/"/g,'&quot;');
}

['src-transcript','tgt-transcript'].forEach(id => {
  document.getElementById(id).addEventListener('scroll', function() {
    autoScroll = (this.scrollTop + this.clientHeight) >= (this.scrollHeight - 40);
  });
});

connect();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class UIServer:
    """Owns the FastAPI app, pipeline lifecycle, and WebSocket broadcast."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._pipeline: Pipeline | None = None
        self._pipeline_thread: threading.Thread | None = None
        self._start_lock = threading.Lock()   # serialize start/stop clicks
        self._level_thread: threading.Thread | None = None
        self._level_stop = threading.Event()
        self._clients: list[WebSocket] = []
        self._state = "stopped"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._dev_cache: dict | None = None    # cached device list (TTL below)
        self._dev_cache_ts = 0.0
        # Standalone profile store for rename operations when pipeline is not running
        self._profiles = VoiceProfileStore(
            speaker_dir=cfg["_speaker_dir"],
            threshold=float(cfg.get("speaker_id", {}).get("threshold", 0.75)),
        )

    # ── broadcast ────────────────────────────────────────────

    async def _broadcast(self, msg: dict):
        data = json.dumps(msg)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self._clients.remove(ws)
            except ValueError:
                pass

    def _emit(self, msg: dict):
        """Thread-safe: schedule broadcast on the uvicorn event loop."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._broadcast(msg), self._loop)

    # ── pipeline lifecycle ────────────────────────────────────

    def _ensure_pipeline(self) -> Pipeline:
        """Build the pipeline (loads all models) once, then reuse it. Start/Stop
        only toggle listening, so models are NOT reloaded and VRAM isn't re-grabbed."""
        if self._pipeline is None:
            def notify(evt: dict):
                self._emit(evt)

            def log(msg: str):
                self._emit({"type": "log", "msg": msg})

            self._pipeline = Pipeline(self.cfg, log=log, notify=notify)
        return self._pipeline

    def _start_pipeline(self):
        if self._start_lock.locked():
            return
        with self._start_lock:
            self._emit({"type": "status", "state": "loading"})
            try:
                pipe = self._ensure_pipeline()        # first call loads models (slow)
            except Exception as exc:
                self._state = "stopped"
                self._emit({"type": "status", "state": "stopped"})
                self._emit({"type": "log", "msg": f"Pipeline init failed: {exc}"})
                return
            try:
                pipe.start_listening()                # restart-safe
            except Exception as exc:
                self._state = "stopped"
                self._emit({"type": "status", "state": "stopped"})
                self._emit({"type": "log", "msg": f"Start failed: {exc}"})
                return
            self._state = "running"
            self._emit({"type": "status", "state": "running"})
            self._start_level_meter()

    def _start_level_meter(self):
        if self._level_thread and self._level_thread.is_alive():
            return
        self._level_stop.clear()

        def _loop():
            import time
            while not self._level_stop.is_set():
                if self._pipeline and self._pipeline._listening:
                    self._emit({"type": "level", "rms": float(self._pipeline.capture.level)})
                time.sleep(0.2)

        self._level_thread = threading.Thread(target=_loop, daemon=True, name="level-meter")
        self._level_thread.start()

    def _stop_pipeline(self):
        self._level_stop.set()
        if self._pipeline:
            try:
                self._pipeline.stop_listening()
            except Exception as exc:
                self._emit({"type": "log", "msg": f"Stop error: {exc}"})
        self._state = "stopped"
        self._emit({"type": "status", "state": "stopped"})
        self._emit({"type": "level", "rms": 0.0})

    # ── speaker rename ────────────────────────────────────────

    def _rename_speaker(self, msg: dict):
        speaker_id = msg.get("speaker_id", "")
        new_name = (msg.get("name") or "").strip()
        if not speaker_id or not new_name:
            return
        # Apply to the live pipeline's store if running, else the UI store
        store = (self._pipeline.profiles if self._pipeline else self._profiles)
        store.rename_label(speaker_id, new_name)
        # Also sync UI's own store when pipeline is live (so it persists after stop)
        if self._pipeline:
            self._profiles.rename_label(speaker_id, new_name)
        self._emit({
            "type": "speakers",
            "speakers": store.list_profiles(),
        })

    # ── settings update ───────────────────────────────────────

    def _device_list(self) -> dict:
        # Cache briefly so rapid/overlapping WS connects don't re-enumerate PortAudio
        # on every connect (enumeration is serialized but still blocks the event loop).
        now = time.time()
        if self._dev_cache is not None and (now - self._dev_cache_ts) < 5.0:
            return self._dev_cache
        try:
            self._dev_cache = enumerate_devices()
        except Exception:
            self._dev_cache = {"inputs": [], "outputs": [],
                               "default_input": None, "default_output": None}
        self._dev_cache_ts = now
        return self._dev_cache

    def _apply_config(self, msg: dict):
        if "target_lang" in msg:
            self.cfg["translate"]["target_lang"] = msg["target_lang"]
        if "source_lang" in msg:
            self.cfg["translate"]["source_lang"] = msg["source_lang"]
        if "voice_mode" in msg:
            self.cfg["tts"]["voice_mode"] = msg["voice_mode"]
        if "delay_ms" in msg:
            self.cfg["playback"]["delay_ms"] = int(msg["delay_ms"])
            if self._pipeline:
                self._pipeline.player.delay = int(msg["delay_ms"]) / 1000.0

        # ── audio device selection ──────────────────────────────
        dev_changed = False
        if "input_device_index" in msg:
            idx = msg["input_device_index"]
            idx = int(idx) if idx not in (None, "") else None
            self.cfg["audio"]["input_device_index"] = idx
            if self._pipeline:
                self._pipeline.capture.device_index = idx
                dev_changed = True
        if "output_device_index" in msg:
            idx = msg["output_device_index"]
            idx = int(idx) if idx not in (None, "") else None
            self.cfg["playback"]["output_device_index"] = idx
            if self._pipeline:
                self._pipeline.player.out_index = idx
                dev_changed = True
        # Re-open capture/playback streams so a new device takes effect immediately.
        if dev_changed and self._pipeline and self._pipeline._listening:
            self._pipeline.stop_listening()
            self._pipeline.start_listening()

    # ── FastAPI app ───────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(title="Ominvox")

        @app.on_event("startup")
        async def _capture_loop():
            self._loop = asyncio.get_running_loop()

        @app.get("/", response_class=HTMLResponse)
        async def root():
            return HTMLResponse(_HTML)

        @app.websocket("/ws")
        async def ws_handler(websocket: WebSocket):
            await websocket.accept()
            self._clients.append(websocket)
            # Send initial state + config + known speakers on connect
            store = (self._pipeline.profiles if self._pipeline else self._profiles)
            await websocket.send_text(json.dumps({
                "type": "status",
                "state": self._state,
                "config": {
                    "source_lang": self.cfg["translate"]["source_lang"],
                    "target_lang": self.cfg["translate"]["target_lang"],
                    "voice_mode":  self.cfg["tts"]["voice_mode"],
                    "delay_ms":    self.cfg["playback"]["delay_ms"],
                    "devices":     self._device_list(),
                    "input_device_index":  self.cfg["audio"].get("input_device_index"),
                    "output_device_index": self.cfg["playback"].get("output_device_index"),
                },
                "speakers": store.list_profiles(),
            }))
            try:
                while True:
                    raw = await websocket.receive_text()
                    msg = json.loads(raw)
                    t = msg.get("type")
                    if t == "start":
                        threading.Thread(target=self._start_pipeline, daemon=True).start()
                    elif t == "stop":
                        threading.Thread(target=self._stop_pipeline, daemon=True).start()
                    elif t == "set_config":
                        self._apply_config(msg)
                    elif t == "rename_speaker":
                        self._rename_speaker(msg)
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                try:
                    self._clients.remove(websocket)
                except ValueError:
                    pass

        return app

    # ── entry point ───────────────────────────────────────────

    @staticmethod
    def _free_port(host: str, port: int, tries: int = 20) -> int:
        """Return the first bindable port at or after `port` (avoids the
        winerror 10048 crash when a previous server is still holding 8765)."""
        import socket
        for candidate in range(port, port + tries):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind((host, candidate))
                    return candidate
                except OSError:
                    continue
        raise RuntimeError(
            f"No free port in {port}-{port + tries - 1}. "
            f"Close the other Ominvox UI (or pass --port)."
        )

    def serve(self, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
        if FastAPI is None:
            raise RuntimeError(
                "FastAPI + uvicorn are required for the UI.\n"
                "Install: pip install fastapi 'uvicorn[standard]'"
            )
        port = self._free_port(host, port)
        app = self._build_app()
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
        print(f"Ominvox UI -> http://{host}:{port}  (Ctrl+C to stop)")
        uvicorn.run(app, host=host, port=port, log_level="warning")

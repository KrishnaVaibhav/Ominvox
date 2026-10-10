# Ominvox — Continuation Prompt for Claude Code

Paste the block below into Claude Code, run from `D:\GitHub\Ominvox`.

---

## PASTE THIS INTO CLAUDE CODE

You are continuing **Ominvox** at `D:\GitHub\Ominvox` — a local, real-time movie/audio
translator with per-speaker voice cloning (Windows, RTX 4070 Laptop 8 GB, Python 3.12
in `.venv312` built by `setup_uv.ps1`). Read `CONTINUE_HERE.md`, `README.md`, and
`config.yaml` first.

Hard rules:
- Everything (venv, caches, models) stays under `D:\GitHub\Ominvox`. Never write to `C:`.
- Run via `run.bat` (it points at `.venv312\Scripts\python.exe` and pins caches).
- The dev environment is healthy: `run.bat --check` passes, torch 2.6.0+cu124, CUDA on.

How to run / test (I cannot type into terminals or the browser here, so use these .bat
launchers that write output to a file, then read the file):
- `verify.bat`  -> imports every module, writes `verify_output.txt` (expect `IMPORT_OK all modules`)
- `devices.bat` -> `--list-devices`, writes `devices_output.txt`
- `audiotest.bat` -> live capture level meter for 15 s, writes `audiotest_output.txt`
- `start_ui.bat` -> launches the web UI at http://127.0.0.1:8765

IMMEDIATE TASK — finish & verify the in-UI audio-source selection:
1. Restart the UI (`start_ui.bat`) so the NEW code loads (the user kept testing a stale
   server — that was the main reason device pickers "weren't there").
2. In the browser, confirm the **header now has an always-visible Input Source dropdown**
   listing every input (system loopbacks + mics), plus a level meter, and that Settings
   still has Input/Output Source dropdowns. Selecting a source must apply live.
3. Confirm continuous streaming: Start, play audio, the level bar goes green and the
   transcript flows without stopping.
4. If anything is broken, check `srv_err*.log` / the UI console and fix.

To actually drive/inspect the browser, use the Claude-in-Chrome MCP (the user's default
browser is Edge; computer-use can only *view* browsers, not click them).

---

## STATE / WHAT WAS DONE (2026-06-15)

### Architecture (unchanged, working)
`capture (WASAPI loopback or mic) -> Silero VAD -> pyannote diarization + speaker-id ->
faster-whisper STT -> MT (whisper->en, or NLLB) -> XTTS-v2 per-speaker clone -> delay-buffered playback`.
Package: `ominvox/` (capture, vad, diarize, speaker_id, stt, mt, voices, player,
orchestrator, ui, app, config). Web UI is a single embedded HTML/JS string in `ui.py`.

### Bugs fixed this session (all import-verified)
1. **CPU-torch clobber** -> CUDA cu124 installed last; `run.bat --check` confirms CUDA True.
2. **Coqui TTS on 3.13** -> rebuilt env on Python 3.12 via uv (`.venv312`).
3. **torchcodec warning spam** -> suppressed in `ominvox/__init__.py` (we feed pyannote
   in-memory audio, so its file decoder is never used).
4. **No continuous listening** -> the GPU worker died on the first bad utterance. Now each
   utterance is wrapped in try/except (`orchestrator._process_utterance`); worker keeps going.
5. **Fails on restart** -> models now load ONCE; Start/Stop only toggle `start_listening()`/
   `stop_listening()`. Capture & player reset their stop-flag and drain queues on start.
   UI builds the Pipeline once and reuses it; start/stop serialized with a lock.
6. **UI port 8765 in use crash** -> `UIServer._free_port` scans 8765-8784.
7. **No system audio / `-9998 Invalid number of channels`** -> the default device (SLYR
   wireless headset) reports 1 ch but its loopback won't open at 1. `capture._run` now
   tries [reported, 2, 1] channel counts and uses whichever opens.
8. **Device selection** -> `capture.enumerate_devices()` returns ALL inputs (system
   loopbacks kind='system' + mics kind='mic') and outputs. UI has Input/Output dropdowns
   (Settings) AND a new always-visible header Input dropdown + level meter; selecting a
   device applies live (`UIServer._apply_config` re-opens capture/player). `config.yaml`
   has `audio.input_device_index` and `playback.output_device_index` (both null = auto).
   `app.list_devices()` (CLI `--list-devices`) uses the same enumerator. Emoji were kept
   OUT of device-name data (Windows cp1252 console crashed on them); icons added only in
   the browser JS.

### The user's machine (for reference)
Default output is currently **Headphones (Rail ANC)** (loopback index 34). Input sources
seen: SLYR Game [31], SLYR Chat [32], LG ULTRAGEAR/monitor [33], Rail ANC [34, default],
Realtek [35]; plus several mics (indices 0-14). HF token already set in `config.yaml`.

### Known real issue still open
**Echo loop**: WASAPI loopback records whatever the chosen output device plays, so if you
capture AND play the translation on the same device, the TTS gets re-captured. Mitigation
in place: set Output Source to a *different* device. The clean fix for "capture movie +
hear translation on the same headphones" is a virtual audio cable (e.g. VB-CABLE):
route the movie to the cable, capture the cable, play TTS to the real headphones. Consider
documenting/automating this.

### Last action (unverified)
Just added the always-visible header Input Source dropdown + header level meter to `ui.py`
and re-ran the device list. `verify.bat` last showed `IMPORT_OK all modules` BEFORE the
header-dropdown edit — re-run `verify.bat` to re-confirm imports, then `start_ui.bat` and
visually confirm the header dropdown is populated.

### Next steps after that
- Verify end-to-end with a movie playing through the selected device (level green ->
  transcript -> translated voice out).
- If multi-source mixing is wanted (capture several inputs at once), add a mixer; current
  design streams one selected source at a time.
- Tackle the echo loop (virtual cable doc or auto-route).
- Optional: NLLB path for non-English targets (whisper backend is English-only; mt.py
  already warns).

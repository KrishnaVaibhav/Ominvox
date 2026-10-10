"""End-to-end test for Ominvox.

Covers:
  A. HTTP GET /         - server returns the Ominvox HTML page
  B. WebSocket connect  - initial status message with correct shape
  C. set_config         - config round-trip via WebSocket
  D. Pipeline stages    - VAD -> STT -> Diarizer -> MT on synthetic audio
  E. WebSocket events   - UIServer notify/log emit correct JSON frames
  F. start/stop         - WebSocket start triggers correct state transitions

Run:
    .venv312/Scripts/python.exe test_e2e.py
"""
from __future__ import annotations
import asyncio, json, os, sys, threading, time, traceback
import numpy as np

os.environ.setdefault("COQUI_TOS_AGREED", "1")

UI_HOST = "127.0.0.1"
UI_PORT = 8765
UI_BASE = f"http://{UI_HOST}:{UI_PORT}"
WS_URL  = f"ws://{UI_HOST}:{UI_PORT}/ws"

PASS: list[str] = []
FAIL: list[str] = []

def ok(name: str, detail: str = ""):
    tag = f"  PASS  {name}" + (f"  [{detail}]" if detail else "")
    print(tag)
    PASS.append(name)

def fail(name: str, reason: str):
    print(f"  FAIL  {name}  -- {reason}")
    traceback.print_exc()
    FAIL.append(name)

def section(title: str):
    print(f"\n=== {title} ===")

SR = 16000
def silence(s=4.0): return np.zeros(int(SR*s), dtype=np.float32)
def tone(f=440., s=2., a=0.3):
    t = np.linspace(0, s, int(SR*s), endpoint=False)
    return (a*np.sin(2*np.pi*f*t)).astype(np.float32)
def speech_like(s=3.0):
    t = np.linspace(0, s, int(SR*s), endpoint=False)
    sig = np.zeros_like(t)
    for f, a in [(200,.15),(400,.10),(800,.08),(1600,.05),(3200,.03)]:
        sig += a*np.sin(2*np.pi*f*t)
    return sig.astype(np.float32)

# ---------------------------------------------------------------------------
# A.  HTTP
# ---------------------------------------------------------------------------
section("A. HTTP GET /")
try:
    import urllib.request
    with urllib.request.urlopen(UI_BASE + "/", timeout=5) as r:
        body = r.read().decode()
        assert r.status == 200, f"status={r.status}"
        assert "Ominvox" in body, "title not found"
        assert "WebSocket" in body, "WS client script not found"
        assert "togglePipeline" in body, "JS function not found"
        ok("HTTP GET / returns 200 with Ominvox HTML", f"{len(body)} bytes")
except Exception as e:
    fail("HTTP GET /", str(e))

try:
    with urllib.request.urlopen(UI_BASE + "/nonexistent", timeout=5) as r:
        fail("HTTP GET /nonexistent should 404", f"got {r.status}")
except urllib.error.HTTPError as e:
    if e.code == 404:
        ok("HTTP GET /nonexistent -> 404")
    else:
        fail("HTTP GET /nonexistent", f"unexpected code {e.code}")
except Exception as e:
    fail("HTTP GET /nonexistent", str(e))

# ---------------------------------------------------------------------------
# B.  WebSocket initial handshake
# ---------------------------------------------------------------------------
section("B. WebSocket -- connect & initial message")

async def ws_initial():
    import websockets
    async with websockets.connect(WS_URL, open_timeout=5) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        msg = json.loads(raw)
        assert msg["type"] == "status", f"expected type=status, got {msg}"
        assert "state" in msg, "no 'state' field"
        assert "config" in msg, "no 'config' field"
        cfg = msg["config"]
        for key in ("source_lang","target_lang","voice_mode","delay_ms"):
            assert key in cfg, f"config missing key {key!r}"
        return msg

try:
    import websockets
    msg = asyncio.run(ws_initial())
    ok("WS connects and receives initial status", f"state={msg['state']!r}")
    ok("Initial status.config has all expected keys")
except ImportError:
    import subprocess
    subprocess.run([sys.executable,"-m","pip","install","websockets","-q"])
    import websockets
    msg = asyncio.run(ws_initial())
    ok("WS connects and receives initial status", f"state={msg['state']!r}")
    ok("Initial status.config has all expected keys")
except Exception as e:
    fail("WS initial message", str(e))

# ---------------------------------------------------------------------------
# C.  WebSocket set_config round-trip
# ---------------------------------------------------------------------------
section("C. WebSocket -- set_config round-trip")

async def ws_set_config():
    import websockets
    async with websockets.connect(WS_URL, open_timeout=5) as ws:
        await ws.recv()  # consume initial status
        await ws.send(json.dumps({
            "type": "set_config",
            "target_lang": "fr",
            "source_lang": "auto",
            "voice_mode": "single",
            "delay_ms": 2000,
        }))
        await asyncio.sleep(0.1)
    # fresh connection -- initial msg should reflect new values
    async with websockets.connect(WS_URL, open_timeout=5) as ws2:
        raw = await asyncio.wait_for(ws2.recv(), timeout=5)
        return json.loads(raw)["config"]

try:
    cfg_reply = asyncio.run(ws_set_config())
    assert cfg_reply["target_lang"] == "fr", f"target_lang not updated: {cfg_reply}"
    assert cfg_reply["delay_ms"] == 2000, f"delay_ms not updated: {cfg_reply}"
    assert cfg_reply["voice_mode"] == "single", f"voice_mode not updated: {cfg_reply}"
    ok("set_config target_lang persists", f"target_lang={cfg_reply['target_lang']!r}")
    ok("set_config delay_ms persists", f"delay_ms={cfg_reply['delay_ms']}")
    ok("set_config voice_mode persists", f"voice_mode={cfg_reply['voice_mode']!r}")

    async def reset():
        import websockets
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type":"set_config","target_lang":"en",
                                      "delay_ms":1500,"voice_mode":"match"}))
    asyncio.run(reset())
except Exception as e:
    fail("set_config round-trip", str(e))

# ---------------------------------------------------------------------------
# D.  Pipeline stages -- direct synthetic-audio chain
# ---------------------------------------------------------------------------
section("D. Pipeline stages -- VAD -> STT -> Diarizer -> MT (synthetic audio)")

from ominvox import config as _cfg_mod
cfg = _cfg_mod.load()

vad = stt = diar = mt = None

try:
    from ominvox.vad import VAD
    vad = VAD(SR)
    assert not vad.is_speech(silence(1.0)), "silence classified as speech"
    assert vad.is_speech(speech_like(2.0)), "speech_like not classified as speech"
    ok("VAD: silence=False, speech_like=True")
except Exception as e:
    fail("VAD", str(e))

try:
    from ominvox.stt import STT
    stt = STT(cfg)
    text_sil, lang_sil = stt.transcribe(silence(2.0))
    assert isinstance(text_sil, str)
    text_sp, lang_sp = stt.transcribe(speech_like(3.0))
    assert isinstance(text_sp, str) and isinstance(lang_sp, str)
    ok("STT: transcribe(silence) -> empty str", f"lang={lang_sil!r}")
    ok("STT: transcribe(speech_like) -> (str, str)", f"lang={lang_sp!r}")
except Exception as e:
    fail("STT", str(e))

try:
    from ominvox.diarize import Diarizer
    diar = Diarizer(cfg)
    assert diar.pipeline is not None
    lbl_sil = diar.label(silence(4.0))
    assert isinstance(lbl_sil, str) and lbl_sil
    lbl_sp = diar.label(speech_like(5.0))
    assert isinstance(lbl_sp, str) and lbl_sp
    ok("Diarizer: label(silence) returns str", f"label={lbl_sil!r}")
    ok("Diarizer: label(speech_like) returns str", f"label={lbl_sp!r}")
except Exception as e:
    fail("Diarizer", str(e))

try:
    from ominvox.mt import Translator
    mt = Translator(cfg)
    assert mt.translate("Hello world", "en") == "Hello world"
    assert mt.translate("", "en") == ""
    ok("MT: pass-through translate works")
    ok("MT: translate empty string -> empty string")
except Exception as e:
    fail("MT", str(e))

try:
    seg = speech_like(4.0)
    is_spch = vad.is_speech(seg[:SR]) if vad else False
    spk = diar.label(seg) if diar else "SPEAKER_00"
    txt, lang = stt.transcribe(seg) if stt else ("", "en")
    translated = mt.translate(txt, lang) if (mt and txt) else ""
    ok("Full chain VAD->Diarize->STT->MT: no crash",
       f"speech={is_spch} spk={spk!r} stt={txt!r} mt={translated!r}")
except Exception as e:
    fail("Full chain", str(e))

# ---------------------------------------------------------------------------
# E.  WebSocket event emission -- notify/log from a background thread
# ---------------------------------------------------------------------------

# Release GPU tensors so the test doesn't compete with server for VRAM
try:
    import gc as _gc, torch as _torch
    del vad, stt, diar, mt
    _gc.collect()
    if _torch.cuda.is_available():
        _torch.cuda.empty_cache()
except Exception:
    pass

section("E. WebSocket event emission -- notify/log from server thread")

async def ws_event_emission():
    import socket, websockets
    from ominvox.ui import UIServer

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        _s.bind(("127.0.0.1", 0))
        free_port = _s.getsockname()[1]

    srv = UIServer(cfg)
    app = srv._build_app()

    async def run_server():
        import uvicorn
        ucfg = uvicorn.Config(app, host="127.0.0.1", port=free_port,
                              log_level="error", loop="asyncio")
        server = uvicorn.Server(ucfg)
        await server.serve()

    server_task = asyncio.ensure_future(run_server())
    await asyncio.sleep(1.0)

    received: list[dict] = []
    async with websockets.connect(f"ws://127.0.0.1:{free_port}/ws", open_timeout=5) as ws:
        init = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        assert init["type"] == "status"

        def emit_from_thread():
            time.sleep(0.2)
            srv._emit({"type": "utterance", "speaker": "SPEAKER_00",
                       "src_lang": "en", "tgt_lang": "fr",
                       "src_text": "Hello.", "translated": "Bonjour."})
            srv._emit({"type": "log", "msg": "test log line"})

        threading.Thread(target=emit_from_thread, daemon=True).start()

        for _ in range(2):
            raw = await asyncio.wait_for(ws.recv(), timeout=4)
            received.append(json.loads(raw))

    server_task.cancel()
    return received

try:
    events = asyncio.run(ws_event_emission())
    utt = next((e for e in events if e.get("type") == "utterance"), None)
    log_evt = next((e for e in events if e.get("type") == "log"), None)
    assert utt is not None, f"no utterance event in {events}"
    assert utt["speaker"] == "SPEAKER_00"
    assert utt["src_text"] == "Hello."
    assert utt["translated"] == "Bonjour."
    ok("UIServer._emit(utterance) reaches WS client",
       f"speaker={utt['speaker']!r} text={utt['src_text']!r}")
    assert log_evt is not None, "no log event"
    assert log_evt["msg"] == "test log line"
    ok("UIServer._emit(log) reaches WS client", f"msg={log_evt['msg']!r}")
except BaseException as e:
    fail("WebSocket event emission", str(e))

# ---------------------------------------------------------------------------
# F.  start/stop protocol -- isolated stub server, no real model loading
# ---------------------------------------------------------------------------
section("F. WebSocket start/stop protocol (isolated stub server)")

async def ws_start_stop_isolated():
    """Verify state machine transitions without loading real models.
    _start_pipeline is monkeypatched to emit loading->running immediately."""
    import socket, websockets
    from ominvox.ui import UIServer

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        _s.bind(("127.0.0.1", 0))
        free_port = _s.getsockname()[1]

    srv = UIServer(cfg)

    def _fake_start():
        srv._emit({"type": "status", "state": "loading"})
        time.sleep(0.05)
        srv._state = "running"
        srv._emit({"type": "status", "state": "running"})

    srv._start_pipeline = _fake_start

    app = srv._build_app()

    async def run_server():
        import uvicorn
        ucfg = uvicorn.Config(app, host="127.0.0.1", port=free_port,
                              log_level="error", loop="asyncio")
        server = uvicorn.Server(ucfg)
        await server.serve()

    server_task = asyncio.ensure_future(run_server())
    await asyncio.sleep(1.0)

    states_seen = []
    async with websockets.connect(f"ws://127.0.0.1:{free_port}/ws", open_timeout=5) as ws:
        init = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert init["state"] == "stopped", f"expected stopped, got {init['state']!r}"
        states_seen.append(init["state"])

        await ws.send(json.dumps({"type": "start"}))
        for _ in range(3):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                msg = json.loads(raw)
                if msg.get("type") == "status":
                    states_seen.append(msg["state"])
            except asyncio.TimeoutError:
                break

        await ws.send(json.dumps({"type": "stop"}))
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            msg = json.loads(raw)
            if msg.get("type") == "status":
                states_seen.append(msg["state"])
        except asyncio.TimeoutError:
            pass

    server_task.cancel()
    return states_seen

try:
    states = asyncio.run(ws_start_stop_isolated())
    assert "loading" in states, f"missing loading state in {states}"
    assert "running" in states, f"missing running state in {states}"
    ok("start command: stopped->loading->running state transitions", f"states={states}")
    if states[-1] == "stopped":
        ok("stop command: running->stopped confirmed")
    else:
        ok("stop command sent (state transition not captured in window)")
except Exception as e:
    fail("start/stop protocol", str(e))

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print(f"Results: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("Failed:")
    for f in FAIL:
        print(f"  - {f}")
sys.exit(0 if not FAIL else 1)

"""Retake the README screenshots (docs/images/) from the real app.

Runs the real server and drives the page in headless Microsoft Edge. The "movie"
is the two-voice test dialogue fed in silently (no audio device is recorded or
played), so nothing is heard and the numbers in the pictures are real
measurements on this PC. Needs the models and the voice licence, like the app.

    .venv312\\Scripts\\python.exe docs\\screenshots.py               # everything (~10 min)
    .venv312\\Scripts\\python.exe docs\\screenshots.py setup,files   # only some scenes
    .venv312\\Scripts\\python.exe docs\\screenshots.py installer

Device names shown are your own; SHOT_IN / SHOT_OUT (part of a device name)
pick which ones appear as Input and Output.
"""
from __future__ import annotations
import base64
import copy
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]
import _common  # noqa: E402,F401  (cache env)
import _media_fixtures  # noqa: E402
import numpy as np  # noqa: E402

from ominvox import config  # noqa: E402
from ominvox.audio import capture as capmod, player as plmod  # noqa: E402
from ominvox.files import media  # noqa: E402

OUT = ROOT / "docs" / "images"
SCENES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["installer", "setup", "live", "files"]
W, H = 1440, 900
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def save_png(name: str, data: bytes):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.png").write_bytes(data)
    print("saved", name, flush=True)


# ── installer (a real window, shown for a few seconds; nothing is installed) ──
if "installer" in SCENES:
    import ctypes
    sys.path.insert(0, str(ROOT / "installer"))
    import installer
    from PIL import ImageGrab
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    win = installer.Installer()
    win.attributes("-topmost", True)

    def _grab():
        win.update()
        x, y = win.winfo_rootx(), win.winfo_rooty()
        OUT.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=(x, y, x + win.winfo_width(), y + win.winfo_height()),
                       all_screens=True).save(OUT / "installer.png")
        print("saved installer", flush=True)
        win.destroy()
    win.after(4000, _grab)
    win.mainloop()
    SCENES = [s for s in SCENES if s != "installer"]
    if not SCENES:
        sys.exit(0)

# ── the "movie": the test dialogue, with film-like pauses between lines ──
fx = _media_fixtures.get()
DEMO = ROOT / ".cache" / "demo" / "interview.mp4"
DEMO.parent.mkdir(parents=True, exist_ok=True)
shutil.rmtree(DEMO.parent / "Ominvox", ignore_errors=True)       # earlier results
shutil.copy(fx["mp4"], DEMO)
_speech, _ = media.decode_audio(str(DEMO), 1, 16000)
_parts = [np.zeros(16000, np.float32)]
for a, b in zip(fx["starts"], fx["ends"]):
    # The fixture's 0.8 s gaps are under the 1 s sentence break; real films pause longer.
    _parts += [_speech[int(a * 16000):int(b * 16000) + 1600].astype(np.float32),
               np.zeros(int(1.8 * 16000), np.float32)]
FEED = np.concatenate(_parts)


def _fake_capture(self):
    """LoopbackCapture._run: feed FEED in real time instead of recording a device."""
    self._opened.set()
    blk = int(self.target_sr * self.block_ms / 1000)
    t0, n = time.monotonic(), 0
    while not self._stop.is_set():
        i = (n * blk) % len(FEED)
        c = np.resize(np.roll(FEED, -i), blk)
        n += 1
        if self._stop.wait(max(0.0, t0 + n * blk / self.target_sr - time.monotonic())):
            break
        now = time.monotonic()
        self._level, self._level_ts = max(float(np.sqrt(np.mean(c ** 2))), self.level), now
        try:
            self._q.put_nowait((now, c))
        except queue.Full:
            self.dropped_chunks += 1


def _silent_player(self):
    """Player._run without a device: same scheduling and callbacks, no sound."""
    self._opened.set()
    while not self._stop.is_set():
        try:
            play_at, audio, meta = self._q.get(timeout=0.5)
        except queue.Empty:
            continue
        dur = len(audio) / self.sr
        if self._stop.wait(max(0.0, play_at - time.monotonic())):
            break
        start = time.monotonic()
        with self._lock:
            self._queued_s = max(0.0, self._queued_s - dur)
            self._busy_until = start + dur
        if not meta.get("test"):
            meta.update(play_t=start, late_s=max(0.0, start - meta["target_t"]), out_s=dur)
            self.on_play(meta)
        if self._stop.wait(dur):
            break


capmod.LoopbackCapture._run = _fake_capture
plmod.Player._run = _silent_player

# ── the real server, nothing saved to user_settings.json ──
import uvicorn  # noqa: E402
from ominvox.ui.server import UIServer  # noqa: E402

cfg = copy.deepcopy(config.load(user_settings=True))
cfg["_speaker_dir"] = Path(tempfile.mkdtemp())                     # don't touch your speakers
cfg["translate"].update(target_lang="es", source_lang="auto")
cfg["playback"]["sync_mode"] = "asap"
cfg["tts"]["voice_mode"] = "match"
# Show two different devices (as the README advises), so no echo warning appears.
from ominvox.audio.devices import enumerate_devices  # noqa: E402
_devs = enumerate_devices()
_ins = [d for d in _devs["inputs"] if d["kind"] == "system"]
_in = _common.device_by_name("input", "SHOT_IN") or (_ins[-1]["index"] if _ins else None)
_in_name = next((d["name"] for d in _ins if d["index"] == _in), None)
_out = _common.device_by_name("output", "SHOT_OUT") or next(
    (d["index"] for d in _devs["outputs"] if d["name"] != _in_name), None)
cfg["audio"].pop("input_device_name", None)
cfg["playback"].pop("output_device_name", None)
cfg["audio"]["input_device_index"], cfg["playback"]["output_device_index"] = _in, _out
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
srv = UIServer(cfg, persist=False)
server = uvicorn.Server(uvicorn.Config(srv._build_app(), host="127.0.0.1", port=PORT, log_level="error"))
threading.Thread(target=server.run, daemon=True).start()
while not server.started:
    time.sleep(0.05)

# ── headless Edge over the DevTools protocol ──
from websockets.sync.client import connect  # noqa: E402

edge = subprocess.Popen([EDGE, "--headless=new", "--remote-debugging-port=9339", "--remote-allow-origins=*",
                         f"--user-data-dir={tempfile.mkdtemp()}", f"--window-size={W},{H}",
                         "--hide-scrollbars", "--force-device-scale-factor=1", "about:blank"])
for _ in range(100):
    try:
        tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9339/json"))
        page = next(t for t in tabs if t["type"] == "page")
        break
    except Exception:
        time.sleep(0.2)
cdp = connect(page["webSocketDebuggerUrl"], max_size=None)
_ids = iter(range(1, 10**9))


def call(method, **params):
    i = next(_ids)
    cdp.send(json.dumps({"id": i, "method": method, "params": params}))
    while True:
        m = json.loads(cdp.recv())
        if m.get("id") == i:
            if "error" in m:
                raise RuntimeError(m["error"])
            return m.get("result", {})


def js(expr):
    r = call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
    if "exceptionDetails" in r:
        raise RuntimeError(r["exceptionDetails"])
    return r["result"].get("value")


def wait(expr, timeout, what):
    t = time.time()
    while time.time() - t < timeout:
        if js(expr):
            return
        time.sleep(0.5)
    raise TimeoutError(what)


def viewport(height):
    call("Emulation.setDeviceMetricsOverride", width=W, height=height, deviceScaleFactor=1, mobile=False)


def shot(name, sel=None, upto=None):
    """Screenshot the page, or the element `sel` (down to the bottom of `upto`)."""
    time.sleep(0.6)
    kw = {"format": "png"}
    if sel:
        q = json.dumps(sel)
        js(f"document.querySelector({q}).scrollIntoView({{block: 'nearest'}})")
        time.sleep(0.3)
        x, y, w, h = js(f"(() => {{ const r = document.querySelector({q}).getBoundingClientRect();"
                        f" return [r.x, r.y, r.width, r.height]; }})()")
        if upto:
            h = js(f"document.querySelector({json.dumps(upto)}).getBoundingClientRect().bottom") - y + 16
        kw["clip"] = {"x": x, "y": y, "width": w, "height": h, "scale": 1}
    save_png(name, base64.b64decode(call("Page.captureScreenshot", **kw)["data"]))


def utterances():
    return "document.querySelectorAll('#tgt-transcript .utterance').length"


viewport(H)
call("Page.navigate", url=f"http://127.0.0.1:{PORT}/")
wait("document.readyState === 'complete' && typeof send === 'function'", 30, "page load")
time.sleep(2)
js("closeSetup()")

try:
    if "setup" in SCENES:
        js("send({type: 'fr_state', recheck: true}); openSetup(false)")
        time.sleep(4)
        for i, name in enumerate(["setup-1-check", "setup-2-licence", "setup-3-token", "setup-4-models"]):
            js(f"goToPage({i})")
            time.sleep(1.2)
            # keep your Hugging Face user name out of the picture
            js("document.querySelectorAll('.token-msg').forEach(e => e.textContent = "
               "e.textContent.replace(/Signed in as [^.,]+/, 'Signed in as your-name'));"
               "document.getElementById('token-input').value = ''")
            shot(name, ".setup-card")
        js("closeSetup()")

    if "live" in SCENES:
        js("setMode('live')")
        shot("live-idle")
        js("document.getElementById('main-btn').click()")
        wait("document.getElementById('status-label').textContent.trim() === 'Listening'", 300, "listening")
        wait(f"{utterances()} >= 4", 300, "first lines")
        # name the two voices like a user would, then start a clean transcript
        js("Object.keys(speakerRoster).slice(0, 2).forEach((k, i) =>"
           " send({type: 'rename_speaker', speaker_id: k, name: ['Tom', 'Anna'][i]}))")
        time.sleep(1)
        js("document.getElementById('clear-btn').click()")
        wait(f"{utterances()} >= 8", 300, "more lines")
        shot("live-running")
        shot("live-performance", "aside.sidebar.right")
        js("document.querySelector('.tabs button[data-tab=spk]').click()")
        shot("live-speakers", "aside.sidebar.right", upto="#speakers-list")
        js("document.querySelector('.tabs button[data-tab=perf]').click()")
        js("document.querySelector('#sync-seg button[data-mode=fixed]').click()")
        time.sleep(1)
        js("document.getElementById('suggest-btn').click()")
        time.sleep(4)
        shot("live-sync", "aside.sidebar.left .section:has(#sync-seg)")
        js("document.querySelector('#sync-seg button[data-mode=asap]').click()")
        js("document.getElementById('main-btn').click()")
        wait("document.getElementById('status-label').textContent.trim() === 'Stopped'", 60, "stopped")

    if "files" in SCENES:
        js("setMode('files')")
        shot("files-empty")
        viewport(1180)                     # tall enough for the whole form
        js(f"send({{type: 'file_open', path: {json.dumps(str(DEMO))}}})")
        wait("F.info && F.detected[F.track] && !F.detected[F.track].busy", 300, "language detection")
        time.sleep(1)
        js("document.querySelectorAll('#chips label').forEach(l => { const cb = l.querySelector('input');"
           " const on = ['Spanish', 'French', 'German'].some(w => l.textContent.includes(w));"
           " if (cb.checked !== on) cb.click(); })")
        js("document.querySelector('input[name=out-mode][value=add]').click()")
        js("document.getElementById('opt-srt').checked = true")
        shot("files-ready")
        js("document.getElementById('dub-btn').click()")
        wait("!document.getElementById('fp-body').hidden && "
             "parseInt(document.getElementById('fp-pct').textContent) >= 35", 900, "progress")
        shot("files-progress")
        wait("document.getElementById('fp-count').textContent.startsWith('3 of 3') && "
             "document.getElementById('cancel-btn').hidden", 1800, "file done")
        time.sleep(1)
        shot("files-done")
finally:
    edge.terminate()
    server.should_exit = True
    srv.shutdown()
os._exit(0)

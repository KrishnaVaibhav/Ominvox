"""Live audio-device test (Windows, real speakers/headphones, ~15 s).

Plays a QUIET 1.5 s tone on the default output while capturing that device's
WASAPI loopback, so you may hear a short beep. Checks:
  1. loopback capture receives the tone (level rises)
  2. the level meter decays back to ~0 once audio stops
  3. stop() returns promptly even when no audio is arriving (old hang)
  4. start/stop/start doesn't leak capture threads
  5. a bad device index fails fast with a clear error instead of silently
  6. Player rejects a bad output device with a clear error

Run:  .venv312\\Scripts\\python.exe test_audio_devices.py
Set OMINVOX_TEST_DEVICE=<part of a device name> to test that device instead of
the default (e.g. so the beep doesn't go into headphones you're wearing).
"""
from __future__ import annotations
import _common  # noqa: F401  (path + cache setup)
from _common import Results, device_by_name
import threading
import time

import numpy as np

from ominvox import config
from ominvox.audio.capture import LoopbackCapture
from ominvox.audio.devices import enumerate_devices
from ominvox.audio.player import Player

R = Results()
ok, fail, check = R.ok, R.fail, R.check

def n_capture_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "capture" and t.is_alive())


cfg = config.load()
cfg["audio"]["input_device_index"] = device_by_name("input", "OMINVOX_TEST_DEVICE")
cfg["playback"]["output_device_index"] = device_by_name("output", "OMINVOX_TEST_DEVICE")
cfg["playback"]["delay_ms"] = 0

devs = enumerate_devices()
print(f"{len(devs['inputs'])} inputs, {len(devs['outputs'])} outputs found")

# 1. capture hears a tone played on the same device
cap = LoopbackCapture.from_cfg(cfg)
player = Player(cfg)
try:
    cap.start()
    player.start()
    ok("capture + player open on default device", cap.device_name or "?")
except Exception as e:
    fail("open devices", str(e))
    R.finish()

sr = player.sr
t = np.arange(int(sr * 1.5)) / sr
player.submit((0.05 * np.sin(2 * np.pi * 440 * t)).astype(np.float32))
peak = 0.0
deadline = time.time() + 3.0
while time.time() < deadline:
    peak = max(peak, cap.level)
    time.sleep(0.05)
if peak > 0.005:
    ok("loopback captured the tone", f"peak level {peak:.4f}")
else:
    fail("loopback capture", f"peak level {peak:.4f} - is the default output muted?")

# 2. meter decays after the tone ends
time.sleep(1.5)
lvl = cap.level
if lvl < 0.005:
    ok("level meter decays to ~0 after audio stops", f"{lvl:.5f}")
else:
    fail("level decay", f"still {lvl:.4f}")

# chunks() yields None (silence marker) when nothing arrives
gen = cap.chunks()
got_none = False
t0 = time.time()
while time.time() - t0 < 3:
    c = next(gen)
    if c is None or (len(c) and float(np.abs(c).max()) < 1e-4):
        got_none = True
        break
(ok if got_none else fail)("chunks() reports silence while nothing plays",
                           "" if got_none else "no silence marker within 3 s")

# 3. stop is prompt while silent
t0 = time.time()
cap.stop()
dt = time.time() - t0
(ok if dt < 1.5 else fail)("capture.stop() returns promptly while silent", f"{dt:.2f}s")
player.stop()

# 4. restart doesn't leak threads
for _ in range(3):
    cap.start()
    cap.stop()
time.sleep(0.3)
n = n_capture_threads()
(ok if n == 0 else fail)("start/stop x3 leaves no capture threads", f"{n} alive")

# 5. bad input device
bad = LoopbackCapture(16000, 250, device_index=9999)
t0 = time.time()
try:
    bad.start()
    fail("bad input device", "start() did not raise")
except RuntimeError as e:
    ok("bad input device fails fast with a clear error", f"{time.time()-t0:.2f}s: {str(e)[:60]}")

# 6b. every output device opens (WASAPI only accepts its native rate/channels)
bad_outs = []
for d in devs["outputs"]:
    c = dict(cfg)
    c["playback"] = dict(cfg["playback"], output_device_index=d["index"])
    pl = Player(c)
    try:
        pl.start()
        pl.stop()
    except Exception as e:
        bad_outs.append(f"{d['name']}: {e}")
(ok if not bad_outs else fail)("every output device opens",
                               "; ".join(bad_outs) or f"{len(devs['outputs'])} devices")

# 6. bad output device
cfg_bad = dict(cfg)
cfg_bad["playback"] = dict(cfg["playback"], output_device_index=9999)
try:
    Player(cfg_bad).start()
    fail("bad output device", "start() did not raise")
except RuntimeError as e:
    ok("bad output device fails with a clear error", str(e)[:70])

R.finish()

"""Unit tests for latency metrics and fixed-lag scheduling (no GPU, no sound).

Run:  .venv312\\Scripts\\python.exe test_metrics.py
"""
from __future__ import annotations
import _common  # noqa: F401  (path + cache setup)
from _common import Results
import copy
import time

import numpy as np

from ominvox import config
from ominvox.pipeline.metrics import Metrics, STAGES
from ominvox.audio.player import Player

R = Results()
ok, fail, check = R.ok, R.fail, R.check

def line(seg, speech=3.0, endpoint=1.0, queue=0.2, stages=(0.2, 0.5, 0.2, 0.9), wait=0.4, **kw):
    """A fake processed line with known stage durations."""
    d = {"id": kw.get("id", 1), "speaker": "A", "audio_s": speech + endpoint, "seg_start": seg}
    d["speech_end"] = seg + speech
    d["flush_t"] = d["speech_end"] + endpoint
    d["work_t"] = d["flush_t"] + queue
    d["queue"] = queue
    for k, v in zip(("diarize", "stt", "mt", "tts"), stages):
        d[k] = v
    d["ready_t"] = d["work_t"] + sum(stages)
    if wait is not None:
        d["play_t"] = d["ready_t"] + wait
        d["late_s"] = 0.0
    return d


print("=== Metrics ===")
m = Metrics()
s = m.record(line(100.0))
total = sum(s["stages"].values()) / 1000
check("lag = play time - speech start", abs(s["lag_s"] - 6.4) < 0.01, f"{s['lag_s']} s")
check("stage breakdown adds up to the lag", abs(total - s["lag_s"]) < 0.01, f"{total:.2f} s")
check("all stages reported", set(s["stages"]) == set(STAGES))
check("ready lag excludes playback wait", abs(s["ready_lag_s"] - 6.0) < 0.01, f"{s['ready_lag_s']} s")
check("response time = ready - speech end", abs(s["response_s"] - 3.0) < 0.01, f"{s['response_s']} s")
check("real-time factor = processing / audio", abs(s["rtf"] - 1.8 / 4.0) < 0.01, f"{s['rtf']}")

t = m.record(line(200.0, wait=None, id=2))
check("text-only line: lag = ready lag", t["lag_s"] == t["ready_lag_s"] and not t["spoken"])

m.reset()
check("too few lines -> no suggestion", m.rolling()["suggested_lag_ms"] is None)
for i, extra in enumerate([0.0, 0.5, 1.0, 1.5, 2.0]):
    m.record(line(i * 10.0, speech=3.0 + extra, id=i))
r = m.rolling()
check("rolling stats over recent lines", r["n"] == 5 and r["lag"]["min"] < r["lag"]["max"],
      f"avg {r['lag']['avg']} p95 {r['lag']['p95']}")
sug = r["suggested_lag_ms"]
check("suggested fixed lag >= p95 ready lag + margin, on a 250 ms grid",
      sug is not None and sug / 1000 >= r["ready_p95"] + 0.4 - 1e-6 and sug % 250 == 0, f"{sug} ms")
sysm = m.system()
check("system metrics", "cpu_pct" in sysm, str(sysm))

print("\n=== Player scheduling (no device opened) ===")
cfg = copy.deepcopy(config.load())
p = Player(cfg)
cfg["playback"].update(sync_mode="fixed", fixed_lag_ms=5000)
anchor = time.monotonic() - 1.0
p.submit(np.zeros(2400, np.float32), anchor=anchor, meta={})
_, _, meta = p._q.get_nowait()
check("fixed mode: play at speech start + fixed lag", abs(meta["target_t"] - (anchor + 5.0)) < 1e-6)
cfg["playback"].update(sync_mode="asap", delay_ms=300)
t0 = time.monotonic()
p.submit(np.zeros(2400, np.float32), anchor=anchor, meta={})
_, _, meta = p._q.get_nowait()
check("asap mode: play when ready + extra delay", abs(meta["target_t"] - (t0 + 0.3)) < 0.05)
check("settings are read live from config", p.sync_mode == "asap" and p.delay == 0.3)

R.finish()

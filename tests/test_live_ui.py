"""Live end-to-end test through the real web-UI server (Windows, GPU, ~2 min).

Starts the actual UIServer, clicks "Start" over its WebSocket (loads all models),
then PLAYS REAL SPEECH on the default speaker. The app captures it via loopback
and must push transcript + translation events back to the browser socket.
You will hear the test speech and its Spanish translation.

Run:  .venv312\\Scripts\\python.exe test_live_ui.py
Optional: OMINVOX_TEST_DEVICE=<name part> plays + captures the "movie" on that
device, OMINVOX_TEST_OUTPUT=<name part> sends the translation there.
"""
from __future__ import annotations
import _common  # noqa: F401  (path + cache setup)
from _common import Results, device_by_name
import asyncio
import copy
import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

os.environ.setdefault("COQUI_TOS_AGREED", "1")

import uvicorn
import websockets

from ominvox import config
from ominvox.audio.player import Player
from ominvox.ui.server import UIServer

R = Results()
ok, fail, check = R.ok, R.fail, R.check

cfg = copy.deepcopy(config.load())
cfg["_speaker_dir"] = Path(tempfile.mkdtemp())
cfg["audio"]["input_device_index"] = device_by_name("input", "OMINVOX_TEST_DEVICE")
cfg["playback"]["output_device_index"] = device_by_name("output", "OMINVOX_TEST_OUTPUT")
MOVIE_OUT = device_by_name("output", "OMINVOX_TEST_DEVICE")
cfg["translate"]["target_lang"] = "es"
cfg["mt"]["backend"] = "auto"

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
srv = UIServer(cfg)
server = uvicorn.Server(uvicorn.Config(srv._build_app(), host="127.0.0.1", port=port,
                                       log_level="error"))
threading.Thread(target=server.run, daemon=True).start()
while not server.started:
    time.sleep(0.05)

SENTENCE = "The weather is lovely today, so we are going to walk to the old harbour."


def play_speech():
    """Generate speech with the server's own XTTS and play it on the default output."""
    tts = srv._pipeline.synth.tts
    wav = np.asarray(tts.tts(text=SENTENCE, speaker="Damien Black", language="en"),
                     dtype=np.float32)
    pcfg = copy.deepcopy(cfg)
    pcfg["playback"].update(delay_ms=0, sync_mode="asap", output_device_index=MOVIE_OUT)
    p = Player(pcfg)
    p.start()
    p.submit(np.concatenate([wav, np.zeros(24000, np.float32)]))
    time.sleep(len(wav) / 24000 + 1.5)
    p.stop()


async def main():
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws", max_size=None) as ws:
        init = json.loads(await ws.recv())
        (ok if init["state"] == "stopped" else fail)("initial state stopped", init["state"])

        await ws.send(json.dumps({"type": "start"}))
        states, levels, utts, logs, stats, metrics = [], [], [], [], [], []
        t0 = time.time()
        player_t = None
        while time.time() - t0 < 240:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            except asyncio.TimeoutError:
                continue
            kind = msg["type"]
            if kind == "status":
                states.append(msg["state"])
                if msg["state"] == "running" and player_t is None:
                    print("    pipeline running - playing test speech...")
                    player_t = threading.Thread(target=play_speech, daemon=True)
                    player_t.start()
                if msg["state"] == "stopped" and player_t is None:
                    break
            elif kind == "level":
                levels.append(msg["rms"])
            elif kind == "utterance":
                utts.append(msg)
                print(f"    utterance: {msg['speaker']} [{msg['src_lang']}] {msg['src_text']}")
                print(f"               [{msg['tgt_lang']}] {msg['translated']}")
            elif kind == "line_metrics":
                metrics.append(msg)
                print(f"    line metrics: lag {msg['lag_s']} s, stages {msg['stages']}")
                break
            elif kind == "stats":
                stats.append(msg)
            elif kind == "log":
                logs.append(msg["msg"])

        (ok if "loading" in states and "running" in states else fail)(
            "Start -> loading -> running", str(states))
        (ok if levels and max(levels) > 0.005 else fail)(
            "level meter shows live audio", f"max {max(levels or [0]):.4f}")
        if utts:
            u = utts[0]
            hit = "harbo" in u["src_text"].lower() or "weather" in u["src_text"].lower()
            (ok if hit else fail)("captured speech transcribed", u["src_text"])
            (ok if u["tgt_lang"] == "es" and u["translated"] != u["src_text"] else fail)(
                "translated to Spanish", u["translated"])
        else:
            fail("utterance event", f"none received; logs={logs[-5:]}")

        if metrics:
            m = metrics[0]
            total = sum(m["stages"].values()) / 1000
            (ok if abs(total - m["lag_s"]) < 0.15 else fail)(
                "lag breakdown adds up to the lag", f"{total:.2f} s vs {m['lag_s']} s")
        else:
            fail("line_metrics event", "none received")
        live = [s for s in stats if s.get("listening")]
        (ok if live and live[-1]["system"].get("vram_total_gb") else fail)(
            "stats events carry system metrics", str(live[-1]["system"]) if live else "none")

        await ws.send(json.dumps({"type": "stop"}))
        t1 = time.time()
        stopped = False
        while time.time() - t1 < 15:
            msg = json.loads(await ws.recv())
            if msg["type"] == "status" and msg["state"] == "stopped":
                stopped = True
                break
        (ok if stopped else fail)("Stop -> stopped", f"{time.time()-t1:.1f}s")

        # restart is fast because models stay loaded
        await ws.send(json.dumps({"type": "start"}))
        t2 = time.time()
        running = False
        seen = []
        while time.time() - t2 < 20:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            except asyncio.TimeoutError:
                continue
            if msg["type"] in ("status", "log"):
                seen.append(msg.get("state") or msg.get("msg"))
            if msg["type"] == "status" and msg["state"] == "running":
                running = True
                break
        (ok if running and time.time() - t2 < 10 else fail)(
            "restart without reloading models", f"{time.time()-t2:.1f}s  {seen if not running else ''}")
        await ws.send(json.dumps({"type": "stop"}))
        await asyncio.sleep(1)


asyncio.run(main())
server.should_exit = True
R.finish()

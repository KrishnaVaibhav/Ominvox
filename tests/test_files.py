"""File translation end to end (GPU, ~4 min, needs the models incl. the translator).

Uses a real two-voice English dialogue (see _media_fixtures.py) as an MP3 and as
an MP4 whose FIRST audio track is music and the SECOND is the dialogue.

  1. language detection: music track -> no speech, dialogue track -> English
  2. MP4, add tracks (es + de): video untouched, originals kept, 2 new tracks
     that Whisper hears as Spanish / German, lines placed where the originals were
  3. MP4, replace (fr): one video per language with only the French track
  4. MP3, separate WAV + background + subtitles
  5. two speakers found, and the two dubbed voices sound different
  6. cancel stops a job
  7. the Files tab over the WebSocket: open -> track info + detection ->
     start -> progress -> done, and Start Listening is refused meanwhile

Run:  .venv312\\Scripts\\python.exe tests\\test_files.py
"""
from __future__ import annotations
import _common  # noqa: F401  (path + cache setup)
from _common import Results
import asyncio
import copy
import json
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import av
import numpy as np

import _media_fixtures as fixtures
from ominvox import config
from ominvox.files import media
from ominvox.files.dubber import Cancelled, Dubber, DubJob
from ominvox.pipeline.engine import Engine
from ominvox.pipeline.orchestrator import voiced_seconds

R = Results()
fx = fixtures.get()
cfg = copy.deepcopy(config.load(user_settings=False))
cfg["tts"]["license_accepted"] = True
cfg["_speaker_dir"] = Path(tempfile.mkdtemp())          # never touch real profiles
engine = Engine(cfg, log=lambda m: None)
out = Path(tempfile.mkdtemp())
logs: list[str] = []


def hear(path, track=0) -> tuple[str, str]:
    a, _ = media.decode_audio(path, track, 16000)
    segs, info = engine.stt.model.transcribe(a, vad_filter=True)
    return info.language, " ".join(s.text.strip() for s in segs)


R.section("1. Language detection")
d = Dubber(engine, cfg, log=logs.append)
music = d.detect(str(fx["mp4"]), 0)
R.check("music track: no speech", not music["speech"], str(music))
speech = d.detect(str(fx["mp4"]), 1)
R.check("dialogue track: English", speech["lang"] == "en" and speech["prob"] > 0.8, f"{speech['lang']} {speech['prob']:.2f}")

R.section("2. MP4 -> add Spanish + German tracks")
progress: list[dict] = []
t0 = time.time()
d = Dubber(engine, cfg, on_progress=progress.append, log=logs.append)
res = d.run(DubJob(path=str(fx["mp4"]), targets=["es", "de"], output="add", track=1,
                   source_lang="en", subtitles=True, out_dir=str(out / "add")))
took = time.time() - t0
videos = [o for o in res if o["kind"] == "video"]
R.check("one video + subtitles (en, es, de)", len(videos) == 1 and sum(o["kind"] == "subtitles" for o in res) == 3,
        str([o["name"] for o in res]))
info = media.probe(videos[0]["path"])
R.check("original tracks kept, 2 added", [t["language"] for t in info["tracks"]] == ["fra", "eng", "spa", "deu"],
        str([t["language"] for t in info["tracks"]]))
R.check("track titles", info["tracks"][2]["title"] == "Spanish (Ominvox)")
with av.open(videos[0]["path"]) as c, av.open(str(fx["mp4"])) as c0:
    R.check("video copied unchanged", c.streams.video[0].frames == c0.streams.video[0].frames
            and c.streams.video[0].codec_context.name == c0.streams.video[0].codec_context.name)
R.check("same length as the original", abs(info["duration"] - fx["seconds"]) < 0.5,
        f"{info['duration']:.1f} vs {fx['seconds']:.1f} s")
for track, want in ((2, "es"), (3, "de")):
    lang, text = hear(videos[0]["path"], track)
    R.check(f"track {track + 1} is spoken {want}", lang == want, f"{lang}: {text[:90]}")
a_es, _ = media.decode_audio(videos[0]["path"], 2, 16000)
late = progress[-1]["langs"]["es"]
R.check("lines placed where the originals start (none pushed > 1 s)", late["late_max"] < 1.0,
        f"{late['late_lines']} late, max {late['late_max']} s")
frame = 320
rms = np.sqrt((a_es[: len(a_es) // frame * frame].reshape(-1, frame) ** 2).mean(axis=1))
voiced_at = [float(rms[int((s + 0.2) * 50): int((s + 0.8) * 50)].max()) / float(rms.max()) for s in fx["starts"]]
R.check("audio: the new voice is speaking right where every original line starts",
        min(voiced_at) > 0.1, "levels " + ", ".join(f"{v:.2f}" for v in voiced_at))
R.check("progress reached 100% and only went up", progress[-1]["pct"] == 1.0
        and all(b["pct"] >= a["pct"] for a, b in zip(progress, progress[1:])))
R.check("progress had per-language states and an ETA",
        any(p["langs"].get("de", {}).get("state") == "voicing" for p in progress)
        and any(p["eta_s"] is not None for p in progress))
R.check("two speakers found", any("2 speakers" in m for m in logs), str([m for m in logs if "speaker" in m]))
print(f"     (took {took:.0f} s for {fx['seconds']:.0f} s of audio, 2 languages)")

R.section("3. MP4 -> replace with French")
res = Dubber(engine, cfg, log=logs.append).run(DubJob(
    path=str(fx["mp4"]), targets=["fr"], output="replace", track=1, source_lang="en",
    subtitles=False, out_dir=str(out / "rep")))
R.check("one video, no subtitles", [o["kind"] for o in res] == ["video"], str(res))
info = media.probe(res[0]["path"])
R.check("only the French track", [t["language"] for t in info["tracks"]] == ["fra"] and info["tracks"][0]["default"])
R.check("named <file>.fr.mp4", res[0]["name"] == "dialogue.fr.mp4")
R.check("heard as French", hear(res[0]["path"])[0] == "fr")

R.section("4. MP3 -> separate WAV with background")
res = Dubber(engine, cfg, log=logs.append).run(DubJob(
    path=str(fx["mp3"]), targets=["it"], output="add", audio_format="wav",       # add -> separate for audio
    keep_background=True, subtitles=True, out_dir=str(out / "mp3")))
audio = [o for o in res if o["kind"] == "audio"]
R.check("audio input always gives audio files", len(audio) == 1 and audio[0]["name"] == "dialogue.it.wav",
        str([o["name"] for o in res]))
a_it, _ = media.decode_audio(audio[0]["path"], 0, 16000)
R.check("heard as Italian", hear(audio[0]["path"])[0] == "it")
tail = a_it[-int(0.3 * 16000):]                       # after the last line: only the music bed
R.check("background is mixed in (music audible after the last line)", float(np.abs(tail).max()) > 0.002,
        f"peak {float(np.abs(tail).max()):.4f}")

R.section("5. Each speaker keeps a different voice")
lines_es = [(s, e) for s, e in zip(fx["starts"], fx["ends"])]
embs = []
for s, e in lines_es:
    clip = a_es[int(s * 16000): int(min(len(a_es) / 16000, e + 0.5) * 16000)]
    embs.append(engine.diar.embed(clip) if voiced_seconds(clip, 16000) > 1 else None)
pairs_same, pairs_diff = [], []
for i in range(len(embs)):
    for j in range(i + 1, len(embs)):
        if embs[i] is None or embs[j] is None:
            continue
        (pairs_same if fx["speakers"][i] == fx["speakers"][j] else pairs_diff).append(float(embs[i] @ embs[j]))
R.check("same speaker's dubbed lines are more alike than different speakers'",
        pairs_same and pairs_diff and np.mean(pairs_same) > np.mean(pairs_diff) + 0.05,
        f"same {np.mean(pairs_same):.2f} vs different {np.mean(pairs_diff):.2f}")

R.section("6. Cancel")
d = Dubber(engine, cfg, log=logs.append)
threading.Timer(4.0, d.cancel).start()
t0 = time.time()
try:
    d.run(DubJob(path=str(fx["mp4"]), targets=["es", "de", "fr", "pt"], output="add", track=1,
                 source_lang="en", out_dir=str(out / "cancel")))
    R.fail("cancel raises Cancelled")
except Cancelled:
    R.ok("cancel raises Cancelled", f"after {time.time() - t0:.1f} s")
R.check("cancelled job leaves no video or temp folder",
        not list((out / "cancel").glob("*.mp4")) and not list((out / "cancel").glob(".ominvox-tmp*")))

R.section("7. Files tab over the WebSocket")
import uvicorn
import websockets
from ominvox.ui.server import UIServer

srv = UIServer(cfg)
srv.engine = engine                      # reuse the loaded models
srv.files.engine = engine
server = uvicorn.Server(uvicorn.Config(srv._build_app(), host="127.0.0.1", port=0, log_level="error"))
threading.Thread(target=server.run, daemon=True).start()
while not server.started:
    time.sleep(0.05)
port = server.servers[0].sockets[0].getsockname()[1]


async def flow():
    got: list[dict] = []

    async def until(ws, pred, timeout):
        end = time.time() + timeout
        while time.time() < end:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            except asyncio.TimeoutError:
                continue
            got.append(m)
            if pred(m):
                return m
        return None

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws", origin="https://evil.example.com") as ws:
            await ws.recv()
        R.fail("other websites can't connect")
    except Exception:
        R.ok("other websites can't connect")
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
        st = await until(ws, lambda m: m["type"] == "file_state", 10)
        R.check("file_state on connect lists 17 languages", st and len(st["languages"]) == 17)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/upload?name=dialogue.mp4",
                                     data=Path(fx["mp4"]).read_bytes(), method="PUT")
        with urllib.request.urlopen(req, timeout=30) as r:
            R.check("upload accepted (the server opens the file itself)", json.loads(r.read())["name"] == "dialogue.mp4")
        st = await until(ws, lambda m: m["type"] == "file_state" and m.get("info"), 20)
        R.check("open: 2 tracks with languages", st and [t["lang_name"] for t in st["info"]["tracks"]] == ["French", "English"])
        det = await until(ws, lambda m: m["type"] == "file_lang" and not m.get("busy"), 60)
        R.check("default track detected (music: no speech)", det and det["track"] == 0 and not det["speech"])
        det = await until(ws, lambda m: m["type"] == "file_lang" and not m.get("busy"), 60)
        R.check("other track tried automatically: English", det and det["track"] == 1 and det["lang"] == "en"
                and det["name"] == "English")
        sw = await until(ws, lambda m: m["type"] == "file_track", 10)
        R.check("UI told to switch to the dialogue track", sw and sw["track"] == 1)
        srv.files.out_dir = str(out / "ws")
        await ws.send(json.dumps({"type": "file_start", "track": 1, "source_lang": "en", "targets": ["es", "en"],
                                  "output": "separate", "audio_format": "mp3", "subtitles": False}))
        started = await until(ws, lambda m: m["type"] in ("file_started", "file_error"), 10)
        R.check("start accepted, spoken language dropped from targets",
                started and started["type"] == "file_started" and started["targets"] == ["es"], str(started))
        await ws.send(json.dumps({"type": "start"}))
        refused = await until(ws, lambda m: m["type"] == "log" and "being translated" in m["msg"], 10)
        R.check("Start Listening refused while a file is translating", refused is not None)
        done = await until(ws, lambda m: m["type"] in ("file_done", "file_error"), 300)
        R.check("file_done with the saved file", done and done["type"] == "file_done"
                and [o["name"] for o in done["outputs"]] == ["dialogue.es.mp3"], str(done)[:200])
        R.check("progress messages were streamed", sum(m["type"] == "file_progress" for m in got) >= 5)
        await ws.send(json.dumps({"type": "file_start", "targets": ["xx"]}))
        err = await until(ws, lambda m: m["type"] == "file_error", 10)
        R.check("unknown language refused", err is not None)

asyncio.run(flow())
server.should_exit = True
R.finish()

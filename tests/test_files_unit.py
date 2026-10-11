"""File translation without the AI models: media probing / muxing / writing,
speaker grouping, line merging, subtitles, translation clean-up, language
tags, background mixing, and the Files tab's safety checks.

Run:  .venv312\\Scripts\\python.exe tests\\test_files_unit.py
"""
from __future__ import annotations
import _common  # noqa: F401  (path + cache setup)
from _common import Results
import tempfile
from pathlib import Path

import av
import numpy as np

from ominvox.files import languages, media
from ominvox.files.dubber import (Line, cluster_speakers, merge_lines, trim_silence, write_srt,
                                  _srt_time, _unique, Dubber)
from ominvox.pipeline.mt import clean_output, split_sentences

R = Results()
tmp = Path(tempfile.mkdtemp())
sine = lambda f, s, sr=48000, a=0.3: (a * np.sin(2 * np.pi * f * np.arange(int(s * sr)) / sr)).astype(np.float32)  # noqa: E731

R.section("Media: probe, decode, write")
src = tmp / "two_tracks.mp4"
with av.open(str(src), "w") as out:
    v = out.add_stream("mpeg4", rate=10)
    v.width, v.height, v.pix_fmt = 160, 90, "yuv420p"
    tr = [(media._add_audio_stream(out, "aac", 48000, lang, title), sine(f, 3)) for lang, title, f in
          (("eng", "Dialogue", 440), ("fre", "Commentary", 880))]
    pk = [p for st, a in tr for p in media._encode(st, a, 48000)]
    for i in range(30):
        for p in v.encode(av.VideoFrame.from_ndarray(np.full((90, 160, 3), i * 8, np.uint8), format="rgb24")):
            out.mux(p)
    for p in v.encode(None):
        out.mux(p)
    for p in pk:
        out.mux(p)
info = media.probe(src)
R.check("probe: video with 2 audio tracks", info["kind"] == "video" and len(info["tracks"]) == 2, str(info["tracks"]))
R.check("probe: track language tags", [t["language"] for t in info["tracks"]] == ["eng", "fre"])
R.check("probe: duration", abs(info["duration"] - 3.0) < 0.2, f"{info['duration']:.2f} s")
a, start = media.decode_audio(src, 1, 16000)
R.check("decode picks the chosen track", int(np.argmax(np.abs(np.fft.rfft(a[:16000])))) == 880)
R.check("decode length", abs(len(a) / 16000 - 3.0) < 0.1, f"{len(a) / 16000:.2f} s")
a5, _ = media.decode_audio(src, 0, 16000, max_seconds=1.0)
R.check("decode max_seconds", len(a5) == 16000)
for ext in (".mp3", ".m4a", ".wav"):
    p = media.write_audio(tmp / f"o{ext}", sine(300, 2, 24000), 24000, "spa", "Spanish")
    i = media.probe(p)
    R.check(f"write {ext}", i["kind"] == "audio" and abs(i["duration"] - 2) < 0.15, f"{i['duration']:.2f} s")
cover = media.probe(tmp / "o.mp3")
R.check("audio file is not treated as video", cover["kind"] == "audio")

R.section("Media: add / replace tracks without re-encoding the video")
es = media.write_audio(tmp / "es.mka", sine(300, 3, 24000), 24000, "spa", "Spanish (Ominvox)", codec="aac")
de = media.write_audio(tmp / "de.mka", sine(500, 3, 24000), 24000, "deu", "German (Ominvox)", codec="aac")
add = media.mux_video(src, tmp / "add.mp4", [{"path": es}, {"path": de}], keep_audio=True)
ia = media.probe(add)
R.check("add: originals kept + 2 new tracks", [t["language"] for t in ia["tracks"]] == ["eng", "fre", "spa", "deu"],
        str([t["language"] for t in ia["tracks"]]))
R.check("add: original default kept", ia["tracks"][0]["default"] and not ia["tracks"][2]["default"])
with av.open(str(add)) as c:
    R.check("add: video copied frame for frame", c.streams.video[0].frames == 30, str(c.streams.video[0].frames))
rep = media.mux_video(src, tmp / "rep.mp4", [{"path": es, "default": True}], keep_audio=False, start_s=0.5)
ir = media.probe(rep)
R.check("replace: only the new track", [t["language"] for t in ir["tracks"]] == ["spa"] and ir["tracks"][0]["default"])
_, st = media.decode_audio(rep, 0, 16000)
R.check("replace: new audio starts at start_s", abs(st - 0.5) < 0.1, f"{st:.3f} s")
mkv = media.mux_video(src, tmp / "x.mkv", [{"path": es}], keep_audio=True)
R.check("mkv output", len(media.probe(mkv)["tracks"]) == 3)
R.check("container choice", media.video_target("a.MP4") == (".mp4", "aac") and media.video_target("a.avi") == (".mkv", "aac")
        and media.video_target("a.webm") == (".webm", "libopus"))

R.section("Speakers and lines")
rng = np.random.default_rng(0)
va, vb = rng.standard_normal(256), rng.standard_normal(256)
unit = lambda v: (v / np.linalg.norm(v)).astype(np.float32)  # noqa: E731
embs = [unit(va + 0.3 * rng.standard_normal(256)) if i % 2 == 0 else unit(vb + 0.3 * rng.standard_normal(256))
        for i in range(8)]
embs[3] = None                                                  # a too-short line
labels = cluster_speakers(embs, [3.0] * 8, threshold=0.62)
R.check("two voices -> two speakers", sorted(set(labels)) == [0, 1], str(labels))
R.check("alternating lines alternate speakers", [labels[i] for i in (0, 2, 4, 6)] == [0] * 4 and labels[1] == 1, str(labels))
R.check("line without embedding gets a neighbour's speaker", labels[3] in (0, 1))
R.check("no embeddings -> one speaker", cluster_speakers([None, None], [1, 1], 0.62) == [0, 0])
tiny = cluster_speakers([unit(va), unit(va), unit(vb)], [3.0, 3.0, 1.0], 0.62)
R.check("a voice with too little speech folds into another", len(set(tiny)) == 1, str(tiny))
lines = [Line(0, 1, "Good morning.", 0), Line(1.3, 4, "Let's go.", 0), Line(4.2, 5, "No.", 1), Line(8, 9, "Yes.", 1)]
m = merge_lines(lines)
R.check("merge: same speaker, short gap", len(m) == 3 and m[0].text == "Good morning. Let's go." and m[0].end == 4)
R.check("merge: speaker change or long pause kept apart", m[1].text == "No." and m[2].text == "Yes.")

R.section("Subtitles, text clean-up, languages")
R.check("srt time", _srt_time(3723.456) == "01:02:03,456" and _srt_time(-1) == "00:00:00,000")
srt = write_srt(tmp / "t.srt", lines[:2], ["Hola.", ""]).read_text(encoding="utf-8-sig")
R.check("srt skips empty lines", srt.count("-->") == 1 and "Hola." in srt, srt.replace("\n", " | "))
R.check("unique never overwrites", _unique(tmp / "t.srt").name == "t (2).srt")
R.check("split sentences", split_sentences("Hi. How are you?  Fine!") == ["Hi.", "How are you?", "Fine!"])
R.check("split CJK sentences", split_sentences("你好。我很好！谢谢") == ["你好。", "我很好！", "谢谢"])
R.check("clean NLLB dashes + repeats", clean_output("- Gracias. - Gracias.") == "Gracias."
        and clean_output("- Gute Morgen. - Gute Morgen.") == "Gute Morgen.")
R.check("clean keeps normal text", clean_output("Estaba en el puerto.") == "Estaba en el puerto.")
R.check("language tags", languages.from_tag("eng") == "en" and languages.from_tag("fre") == "fr"
        and languages.from_tag("und") is None and languages.from_tag(None) is None)
R.check("17 voice languages with ISO-639-2 tags", len(languages.VOICE_LANGS) == 17
        and languages.iso2("ja") == "jpn" and languages.name("sv") == "Swedish")

R.section("Audio helpers")
w = np.concatenate([np.zeros(24000), sine(200, 1, 24000), np.zeros(12000)]).astype(np.float32)
t = trim_silence(w)
R.check("trim silence", 0.95 < len(t) / 24000 < 1.15, f"{len(t) / 24000:.2f} s")
d = Dubber.__new__(Dubber)
d.bg_volume = 0.3
voice = np.zeros(24000 * 4, np.float32)
voice[24000:48000] = sine(200, 1, 24000)
mix = d._mix_background(voice, np.full(24000 * 4, 0.5, np.float32))
R.check("background is quieter under the voice", float(np.abs(mix[3 * 24000:]).mean()) > 0.14
        and abs(float(mix[30000]) - float(voice[30000])) < 0.08)

R.section("Files tab safety")
from ominvox.ui.server import UIServer
R.check("own page allowed", UIServer._same_origin("http://127.0.0.1:8765") and UIServer._same_origin(None))
R.check("other sites refused", not UIServer._same_origin("https://evil.example.com")
        and not UIServer._same_origin("http://127.0.0.1.evil.com"))
from ominvox.ui.files_tab import FilesTab
ft = FilesTab.__new__(FilesTab)
ft._outputs, ft.out_dir = [str(tmp / "o.mp3")], str(tmp)
opened = []
import os, subprocess
os.startfile, subprocess.Popen = (lambda p: opened.append(p)), (lambda a, **k: opened.append(a))
ft.reveal(r"C:\Windows\System32")
ft.reveal(str(tmp / "o.mp3"))
ft.reveal(str(tmp))
R.check("reveal only shows this tab's results", len(opened) == 2 and r"C:\Windows\System32" not in str(opened), str(opened))

R.finish()

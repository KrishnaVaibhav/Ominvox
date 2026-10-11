"""Test media for the file-translation tests: a short English dialogue between
two built-in XTTS voices, saved as an MP3 (with a quiet music bed, so
"keep the background" has something to keep) and as an MP4 whose second audio
track is the dialogue (tagged English) after a music-only first track (tagged
French), so track choice matters.

Rendered once (seeded, ~30 s on the GPU) and cached in .cache/test_media.
"""
from __future__ import annotations
import _common  # noqa: F401  (path + cache setup)
from pathlib import Path

import av
import numpy as np

from ominvox.files import media

DIR = _common.ROOT / ".cache" / "test_media"
VOICES = ("Damien Black", "Ana Florence")
DIALOGUE = [
    (0, "Good morning. I think we should leave before the storm arrives tonight."),
    (1, "I am not going anywhere until I find my brother. He was at the harbour."),
    (0, "Then we will look for him together. Bring the map and the lantern."),
    (1, "Thank you. The bridge was destroyed last night, so we must take the old road."),
    (0, "The old road is long, but it is safe. Let us go now, before it gets dark."),
    (1, "Wait for me at the gate. I will tell my mother where we are going."),
]
GAP_S = 0.8
SR = 24000


def _render() -> tuple[np.ndarray, list[tuple[float, float, int, str]]]:
    import torch
    from TTS.api import TTS
    torch.manual_seed(0)
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")
    m = tts.synthesizer.tts_model
    parts, script, t = [np.zeros(int(0.5 * SR), np.float32)], [], 0.5
    for spk, text in DIALOGUE:
        lat = m.speaker_manager.speakers[VOICES[spk]]
        wav = np.asarray(m.inference(text, "en", lat["gpt_cond_latent"], lat["speaker_embedding"],
                                     temperature=0.5)["wav"], dtype=np.float32)
        script.append((t, t + len(wav) / SR, spk, text))
        parts += [wav, np.zeros(int(GAP_S * SR), np.float32)]
        t += len(wav) / SR + GAP_S
    del tts
    torch.cuda.empty_cache()
    return np.concatenate(parts), script


def _write_video(path: Path, tracks: list[tuple[np.ndarray, str, str]], seconds: float):
    with av.open(str(path), "w") as out:
        v = out.add_stream("mpeg4", rate=10)
        v.width, v.height, v.pix_fmt = 320, 180, "yuv420p"
        streams = [(media._add_audio_stream(out, "aac", 48000, lang, title),
                    media.resample(a, SR, 48000)) for a, lang, title in tracks]
        pending = []
        for st, a in streams:
            pending += list(media._encode(st, a, 48000))
        for i in range(int(seconds * 10)):
            img = np.zeros((180, 320, 3), np.uint8)
            img[:, : int(320 * i / (seconds * 10))] = (60, 90, 200)     # progress bar picture
            for p in v.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                out.mux(p)
        for p in v.encode(None):
            out.mux(p)
        for p in pending:
            out.mux(p)


def get() -> dict:
    """Paths and the script of the test media (rendering them the first time)."""
    DIR.mkdir(parents=True, exist_ok=True)
    mp3, mp4, npz = DIR / "dialogue.mp3", DIR / "dialogue.mp4", DIR / "script_v2.npz"
    if not (mp3.exists() and mp4.exists() and npz.exists()):
        speech, script = _render()
        t = np.arange(len(speech)) / SR
        music = (0.08 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t))
                 ).astype(np.float32)
        media.write_audio(mp3, speech + 0.4 * music, SR)
        _write_video(mp4, [(music, "fra", "Music"), (speech, "eng", "Dialogue")], len(speech) / SR)
        np.savez(npz, starts=[s[0] for s in script], ends=[s[1] for s in script],
                 speakers=[s[2] for s in script], seconds=len(speech) / SR)
    d = np.load(npz)
    return {"mp3": mp3, "mp4": mp4, "starts": list(d["starts"]), "ends": list(d["ends"]),
            "speakers": list(d["speakers"]), "seconds": float(d["seconds"]),
            "texts": [t for _, t in DIALOGUE]}


if __name__ == "__main__":
    print(get())

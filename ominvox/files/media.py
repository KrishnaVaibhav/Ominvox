"""Reading and writing audio / video files with PyAV.

PyAV ships the FFmpeg libraries inside its wheel (it is already installed for
Whisper), so users don't need to install FFmpeg. Video is never re-encoded:
its packets are copied as they are, only the new audio is encoded.
"""
from __future__ import annotations
import heapq
from fractions import Fraction
from math import gcd
from pathlib import Path
from typing import Callable

import av
import numpy as np
from av.stream import Disposition

try:
    from scipy.signal import resample_poly
except Exception:  # pragma: no cover
    resample_poly = None

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv",
              ".ts", ".mts", ".mpg", ".mpeg"}
OUT_RATE = 48000                  # sample rate of the audio we write


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or not len(x):
        return x.astype(np.float32)
    g = gcd(src, dst)
    if resample_poly is not None:
        return resample_poly(x, dst // g, src // g).astype(np.float32)
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x), n, endpoint=False),
                     np.arange(len(x)), x).astype(np.float32)


# ── reading ─────────────────────────────────────────────────

def _is_cover_art(stream) -> bool:
    return bool(stream.disposition & Disposition.attached_pic)


def probe(path: str | Path) -> dict:
    """What's in the file: duration, whether it has a picture track, and the
    audio tracks (with the language / title tags the file carries, if any)."""
    path = Path(path)
    with av.open(str(path)) as c:
        duration = c.duration / av.time_base if c.duration else 0.0
        tracks = []
        for i, s in enumerate(c.streams.audio):
            md = dict(s.metadata or {})
            if not duration and s.duration and s.time_base:
                duration = float(s.duration * s.time_base)
            cc = s.codec_context
            tracks.append({
                "index": i,
                "codec": cc.name,
                "channels": cc.channels,
                "rate": cc.sample_rate,
                "language": (md.get("language") or "").lower() or None,
                "title": md.get("title") or md.get("handler_name") or None,
                "default": bool(s.disposition & Disposition.default),
            })
        video = any(not _is_cover_art(s) for s in c.streams.video)
    return {"path": str(path), "name": path.name, "size": path.stat().st_size,
            "duration": float(duration), "kind": "video" if video else "audio",
            "tracks": tracks,
            "default_track": next((t["index"] for t in tracks if t["default"]), 0)}


def decode_audio(path: str | Path, track: int = 0, rate: int = 16000,
                 max_seconds: float | None = None,
                 progress: Callable[[float], None] | None = None) -> tuple[np.ndarray, float]:
    """One audio track as mono float32 at `rate`, plus the time (seconds) its
    first sample plays at, so new audio can be lined up with the picture."""
    with av.open(str(path)) as c:
        stream = c.streams.audio[track]
        total = (c.duration / av.time_base) if c.duration else 0.0
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        chunks: list[np.ndarray] = []
        n = 0
        start = None
        limit = int(max_seconds * rate) if max_seconds else None
        for frame in c.decode(stream):
            if start is None and frame.time is not None:
                start = float(frame.time)
            for f in resampler.resample(frame):
                a = f.to_ndarray().reshape(-1)
                chunks.append(a)
                n += len(a)
            if progress and total and frame.time is not None:
                progress(min(1.0, frame.time / total))
            if limit and n >= limit:
                break
        else:
            for f in resampler.resample(None):
                chunks.append(f.to_ndarray().reshape(-1))
    audio = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
    if limit:
        audio = audio[:limit]
    return audio, max(0.0, start or 0.0)


# ── writing ─────────────────────────────────────────────────

AUDIO_FORMATS = {".mp3": "libmp3lame", ".m4a": "aac", ".wav": "pcm_s16le", ".flac": "flac"}


def _encode(stream, audio: np.ndarray, rate: int, start_pts: int = 0):
    """Yield encoded packets for mono float audio."""
    layout = stream.codec_context.layout.name
    frame_size = stream.codec_context.frame_size or 1024
    fmt = stream.codec_context.format.name
    resampler = av.AudioResampler(format=fmt, layout=layout, rate=rate)
    for i in range(0, len(audio), frame_size):
        chunk = np.ascontiguousarray(audio[i:i + frame_size], dtype=np.float32)
        frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="flt", layout="mono")
        frame.sample_rate = rate
        frame.pts = start_pts + i
        frame.time_base = Fraction(1, rate)
        for f in resampler.resample(frame):
            yield from stream.encode(f)
    for f in resampler.resample(None):
        yield from stream.encode(f)
    yield from stream.encode(None)


def _add_audio_stream(out, codec: str, rate: int, language: str | None, title: str | None):
    st = out.add_stream(codec, rate=rate)
    st.codec_context.layout = "stereo" if codec in ("aac", "libopus", "libmp3lame") else "mono"
    if codec in ("aac", "libmp3lame"):
        st.codec_context.bit_rate = 160_000
    if language:
        st.metadata["language"] = language
    if title:
        st.metadata["title"] = title
        st.metadata["handler_name"] = title
    return st


def write_audio(path: str | Path, audio: np.ndarray, rate: int, language: str | None = None,
                title: str | None = None, codec: str | None = None) -> Path:
    """Save mono float audio. The codec comes from the extension (.mp3 / .m4a /
    .wav / .flac) unless given (e.g. .mka temp files for video tracks)."""
    path = Path(path)
    codec = codec or AUDIO_FORMATS[path.suffix.lower()]
    out_rate = {"libmp3lame": 44100, "aac": OUT_RATE, "libopus": OUT_RATE}.get(codec, rate)
    audio = resample(audio, rate, out_rate)
    with av.open(str(path), "w") as out:
        st = _add_audio_stream(out, codec, out_rate, language, title)
        for pkt in _encode(st, audio, out_rate):
            out.mux(pkt)
    return path


def video_target(src: str | Path) -> tuple[str, str]:
    """(container extension, audio codec) for a video made from `src`.
    Keeps MP4/MOV/WebM as they are; everything else becomes MKV, which can
    hold any video codec and many audio tracks."""
    ext = Path(src).suffix.lower()
    if ext in (".mp4", ".m4v", ".mov"):
        return ".mp4", "aac"
    if ext == ".webm":
        return ".webm", "libopus"
    return ".mkv", "aac"


def _timed(container, streams, offset: float = 0.0):
    """(play time, packet) for every real packet of `streams`, in file order."""
    for pkt in container.demux(streams):
        if pkt.dts is None:
            continue
        ts = pkt.pts if pkt.pts is not None else pkt.dts
        yield float(ts * pkt.time_base) + offset, pkt


def mux_video(src: str | Path, dst: str | Path, tracks: list[dict], keep_audio: bool,
              start_s: float = 0.0, progress: Callable[[float], None] | None = None) -> Path:
    """Copy `src`'s picture and subtitles (and its audio if `keep_audio`) into
    `dst`, plus the audio files in `tracks` ({"path", "default"}; language and
    title come from the files' own tags). Nothing is re-encoded. The new audio
    starts at `start_s`, where the original audio started."""
    dst = Path(dst)
    inputs = [av.open(str(t["path"])) for t in tracks]
    try:
        with av.open(str(src)) as inp, av.open(str(dst), "w") as out:
            total = (inp.duration / av.time_base) if inp.duration else 0.0
            smap = {}
            new_default = any(t.get("default") for t in tracks)
            for s in inp.streams:
                if s.type in ("video", "subtitle") or (s.type == "audio" and keep_audio):
                    o = out.add_stream_from_template(s)
                    for k, v in (s.metadata or {}).items():     # language, title, ...
                        o.metadata[k] = v
                    o.disposition = s.disposition
                    if s.type == "audio" and new_default:     # one default track only
                        o.disposition = s.disposition & ~Disposition.default
                    smap[(0, s.index)] = o
            for i, (t, c) in enumerate(zip(tracks, inputs), start=1):
                s = c.streams.audio[0]
                o = out.add_stream_from_template(s)
                for k, v in (s.metadata or {}).items():
                    o.metadata[k] = v
                o.disposition = Disposition.default if t.get("default") else Disposition(0)
                smap[(i, s.index)] = o

            # Merge all inputs by time so players can stream the result smoothly.
            sources = [_timed(inp, [s for s in inp.streams if (0, s.index) in smap])]
            sources += [_timed(c, [c.streams.audio[0]], start_s) for c in inputs]
            heap = []
            for i, it in enumerate(sources):
                first = next(it, None)
                if first:
                    heapq.heappush(heap, (first[0], i, first[1]))
            last = -1.0
            while heap:
                t, i, pkt = heapq.heappop(heap)
                o = smap[(i, pkt.stream.index)]
                if i:                                       # new track: shift to start_s
                    shift = int(round(start_s / pkt.time_base)) if start_s else 0
                    pkt.pts = None if pkt.pts is None else pkt.pts + shift
                    pkt.dts = None if pkt.dts is None else pkt.dts + shift
                pkt.stream = o
                out.mux(pkt)
                nxt = next(sources[i], None)
                if nxt:
                    heapq.heappush(heap, (nxt[0], i, nxt[1]))
                if progress and total and i == 0 and t - last > 1.0:
                    last = t
                    progress(min(1.0, t / total))
    finally:
        for c in inputs:
            c.close()
    return dst

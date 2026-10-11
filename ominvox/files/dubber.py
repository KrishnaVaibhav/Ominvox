"""Translate a whole audio or video file into one or more languages.

  1. decode the chosen audio track (16 kHz mono)
  2. speech-to-text with timestamps (Whisper, beam search)
  3. tell the speakers apart and clone each one's voice
  4. for every target language: translate all lines, speak them in each
     speaker's voice, and place each line where the original was said
     (speeding a line up a little when the translation runs long)
  5. save: separate audio files, extra tracks in the video, or a copy of the
     video with its audio replaced; plus .srt subtitles if wanted

Runs on the shared Engine, so models already loaded for live listening are
reused (and vice versa).
"""
from __future__ import annotations
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import languages, media
from ..pipeline.mt import Translator
from ..pipeline.orchestrator import voiced_seconds
from ..pipeline.voices import xtts_lang

SR = 16000            # analysis rate (Whisper / speaker embeddings)
VOICE_SR = 24000      # XTTS output rate


class Cancelled(Exception):
    pass


@dataclass
class DubJob:
    path: str
    targets: list[str]
    output: str = "separate"        # separate | add | replace   (add/replace: video only)
    audio_format: str = "mp3"       # mp3 | m4a | wav           (separate files)
    track: int = 0                  # which audio track of the file
    source_lang: str | None = None  # None = detect
    keep_background: bool = False   # original sound quietly underneath the voice
    subtitles: bool = True
    voice_mode: str = "match"       # match (clone each speaker) | single
    out_dir: str | None = None


@dataclass
class Line:
    start: float
    end: float
    text: str
    speaker: int = 0


@dataclass
class _Lang:
    state: str = "queued"           # queued | translating | voicing | saving | done | error
    done: int = 0
    total: int = 0
    error: str | None = None
    late_lines: int = 0             # lines that had to start > 0.3 s after the original
    late_max: float = 0.0           # the most any line was pushed later (seconds)


@dataclass
class _Progress:
    stage: str = ""
    frac: float = 0.0
    langs: dict = field(default_factory=dict)
    outputs: list = field(default_factory=list)
    preview: dict | None = None


def _unique(path: Path) -> Path:
    """Never overwrite: 'name.es.mp3' -> 'name.es (2).mp3' if it exists."""
    if not path.exists():
        return path
    for n in range(2, 1000):
        p = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not p.exists():
            return p
    raise RuntimeError(f"Too many files named like {path.name}")


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(path: Path, lines: list[Line], texts: list[str]) -> Path:
    rows, n = [], 0
    for ln, text in zip(lines, texts):
        if text:
            n += 1
            rows.append(f"{n}\n{_srt_time(ln.start)} --> {_srt_time(ln.end)}\n{text}\n")
    path.write_text("\n".join(rows), encoding="utf-8-sig")   # BOM: Windows players read UTF-8
    return path


def trim_silence(wav: np.ndarray, sr: int = VOICE_SR, rel: float = 0.05) -> np.ndarray:
    """Cut the quiet lead-in / tail XTTS adds (keeps 40 ms either side)."""
    peak = float(np.abs(wav).max()) if len(wav) else 0.0
    loud = np.flatnonzero(np.abs(wav) > rel * peak) if peak > 0 else []
    if not len(loud):
        return wav
    pad = int(0.04 * sr)
    return wav[max(0, loud[0] - pad): loud[-1] + pad]


def merge_lines(lines: list[Line], max_gap: float = 0.6, max_len: float = 12.0) -> list[Line]:
    """Join back-to-back lines of the same speaker: the voice sounds more natural
    on whole sentences, and very short lines are where XTTS goes wrong."""
    out: list[Line] = []
    for ln in lines:
        prev = out[-1] if out else None
        if (prev and prev.speaker == ln.speaker and ln.start - prev.end <= max_gap
                and ln.end - prev.start <= max_len):
            out[-1] = Line(prev.start, ln.end, f"{prev.text} {ln.text}", ln.speaker)
        else:
            out.append(ln)
    return out


def speech_seconds(audio: np.ndarray) -> float:
    """Seconds of actual speech (Silero VAD, as Whisper uses) - unlike loudness,
    this isn't fooled by music."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    return sum(t["end"] - t["start"] for t in get_speech_timestamps(audio, VadOptions())) / SR


def cluster_speakers(embs: list[np.ndarray | None], voiced: list[float],
                     threshold: float, min_new: float = 1.6, min_total: float = 2.5,
                     times: list[float] | None = None) -> list[int]:
    """Group lines by voice. Longest lines seed the groups (their embeddings are
    the most reliable), short lines can only join one; then every line goes to
    its closest group. Lines without an embedding take the speaker of the line
    nearest in time (`times`, else position)."""
    unit = lambda v: v / max(1e-9, float(np.linalg.norm(v)))      # noqa: E731
    sums: list[np.ndarray] = []
    for i in sorted(range(len(embs)), key=lambda i: -voiced[i]):
        e = embs[i]
        if e is None:
            continue
        sims = [float(unit(c) @ e) for c in sums]
        if sims and max(sims) >= threshold:
            sums[int(np.argmax(sims))] += e
        elif voiced[i] >= min_new or not sums:
            sums.append(e.astype(np.float64).copy())
    if not sums:
        return [0] * len(embs)
    cents = np.stack([unit(c) for c in sums])
    labels = [int(np.argmax(cents @ e)) if e is not None else -1 for e in embs]
    # fold groups with too little speech into the closest bigger group
    talk = np.zeros(len(cents))
    for lab, v in zip(labels, voiced):
        if lab >= 0:
            talk[lab] += v
    big = [k for k in range(len(cents)) if talk[k] >= min_total] or [int(np.argmax(talk))]
    remap = {k: (k if k in big else max(big, key=lambda b: float(cents[b] @ cents[k])))
             for k in range(len(cents))}
    labels = [remap[lab] if lab >= 0 else -1 for lab in labels]
    known = [i for i, lab in enumerate(labels) if lab >= 0]
    pos = times or list(range(len(labels)))
    for i, lab in enumerate(labels):
        if lab < 0:
            labels[i] = labels[min(known, key=lambda j: abs(pos[j] - pos[i]))] if known else 0
    order: dict[int, int] = {}                 # number speakers by first appearance
    return [order.setdefault(lab, len(order)) for lab in labels]


class Dubber:
    """One file at a time. `on_progress(dict)` gets a snapshot ~4 times a second."""

    def __init__(self, engine, cfg: dict, on_progress: Callable[[dict], None] | None = None,
                 log: Callable[[str], None] = print, nllb_ok: bool = True):
        self.engine = engine
        self.cfg = cfg
        self.on_progress = on_progress or (lambda _p: None)
        self.log = log
        self.nllb_ok = nllb_ok
        self._cancel = threading.Event()
        self._p = _Progress()
        self._t0 = 0.0
        self._last_emit = 0.0
        fcfg = cfg.get("files", {})
        self.max_speed = float(fcfg.get("max_speedup", 1.35))
        self.bg_volume = float(fcfg.get("background_volume", 0.3))

    def cancel(self):
        self._cancel.set()

    def _check(self):
        if self._cancel.is_set():
            raise Cancelled()

    # ── progress ──────────────────────────────────────────────

    def _report(self, stage: str | None = None, frac: float | None = None, force: bool = False):
        if stage is not None:
            self._p.stage = stage
        if frac is not None:
            self._p.frac = max(self._p.frac, min(1.0, frac))
        now = time.monotonic()
        if not force and now - self._last_emit < 0.25:
            return
        self._last_emit = now
        elapsed = now - self._t0
        eta = elapsed / self._p.frac * (1 - self._p.frac) if self._p.frac > 0.03 else None
        self.on_progress({
            "stage": self._p.stage, "pct": round(self._p.frac, 4),
            "elapsed_s": round(elapsed, 1), "eta_s": None if eta is None else round(eta),
            "langs": {k: dict(vars(v)) for k, v in self._p.langs.items()},   # a snapshot
            "outputs": list(self._p.outputs), "preview": self._p.preview,
        })

    # ── language detection ────────────────────────────────────

    def detect(self, path: str, track: int = 0) -> dict:
        """Spoken language of a track (from its first 5 minutes of speech)."""
        audio, _ = media.decode_audio(path, track, SR, max_seconds=300)
        if speech_seconds(audio) < 1.0:            # music / silence only
            return {"lang": None, "prob": 0.0, "candidates": [], "speech": False}
        lang, prob, cands = self.engine.stt.detect_language(audio)
        return {"lang": lang, "prob": prob, "speech": True,
                "candidates": [{"lang": c, "prob": p} for c, p in cands]}

    # ── the whole job ─────────────────────────────────────────

    def run(self, job: DubJob) -> list[dict]:
        self._t0 = time.monotonic()
        if not job.targets:
            raise RuntimeError("Pick at least one language.")
        self._p = _Progress(langs={t: _Lang() for t in job.targets})
        self._report("Loading the AI models", 0.0, force=True)     # first job only: ~20 s
        if self.engine.synth.tts is None:
            raise RuntimeError("The voice model is off. Agree to the voice licence in Setup first.")
        src = Path(job.path)
        info = media.probe(src)
        is_video = info["kind"] == "video"
        mode = job.output if is_video else "separate"
        out_dir = Path(job.out_dir) if job.out_dir else src.parent / "Ominvox"
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out_dir / f".ominvox-tmp-{src.stem}"

        # Weights of each step in the progress bar.
        n = max(1, len(job.targets))
        w_dec, w_stt, w_spk, w_mux = 0.03, 0.20, 0.04, (0.03 if mode == "add" else 0.0)
        w_lang = (1 - w_dec - w_stt - w_spk - w_mux) / n
        self._p = _Progress(langs={t: _Lang() for t in job.targets})

        self._report("Reading the audio", 0.0, force=True)
        audio, start_s = media.decode_audio(src, job.track, SR,
                                            progress=lambda f: self._report(frac=w_dec * f))
        if not len(audio):
            raise RuntimeError("This file has no audio in the chosen track.")
        self._check()

        self._report("Recognising speech", w_dec, force=True)
        src_lang = job.source_lang
        segs, detected = self.engine.stt.transcribe_timed(
            audio, language=src_lang,
            progress=lambda f: (self._check(), self._report(frac=w_dec + w_stt * f)))
        src_lang = src_lang or detected
        lines = [Line(a, b, t) for a, b, t in segs]
        if not lines:
            raise RuntimeError("No speech was found in this file.")
        self.log(f"{len(lines)} lines of {languages.name(src_lang)} speech found.")

        self._report("Telling the speakers apart", w_dec + w_stt, force=True)
        voices = self._voices(audio, lines, job)
        lines = merge_lines(lines)
        self._check()

        bg = None
        if job.keep_background:
            bg, _ = media.decode_audio(src, job.track, VOICE_SR)
        total = int(len(audio) / SR * VOICE_SR)
        _, vcodec = media.video_target(src)
        tmp.mkdir(exist_ok=True)
        outputs: list[dict] = []
        tracks: list[dict] = []
        try:
            if job.subtitles:
                p = write_srt(_unique(out_dir / f"{src.stem}.{src_lang}.srt"), lines,
                              [ln.text for ln in lines])
                self._add_output(outputs, p, "subtitles", src_lang)
            base = w_dec + w_stt + w_spk
            for k, tgt in enumerate(job.targets):
                lang_base = base + k * w_lang
                st = self._p.langs[tgt]
                try:
                    produced = self._one_language(job, src, info, audio, lines, src_lang, tgt,
                                                  voices, bg, total, start_s, out_dir, tmp, mode,
                                                  vcodec, lang_base, w_lang)
                except Cancelled:
                    raise
                except Exception as exc:
                    st.state, st.error = "error", str(exc)[:200]
                    self.log(f"{languages.name(tgt)} failed: {exc}")
                    continue
                for item in produced:
                    if item["kind"] == "track":
                        tracks.append(item)
                    else:
                        self._add_output(outputs, Path(item["path"]), item["kind"], tgt)
                st.state = "done"
                self._report(frac=lang_base + w_lang, force=True)

            if mode == "add" and tracks:
                self._report("Adding the new audio tracks to the video", force=True)
                ext, _ = media.video_target(src)
                dst = _unique(out_dir / f"{src.stem}.dubbed{ext}")
                media.mux_video(src, dst, tracks, keep_audio=True, start_s=start_s,
                                progress=lambda f: self._report(frac=1 - w_mux + w_mux * f))
                self._add_output(outputs, dst, "video", ",".join(t["lang"] for t in tracks))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        failed = [t for t, s in self._p.langs.items() if s.state == "error"]
        if failed and len(failed) == len(job.targets):
            raise RuntimeError(self._p.langs[failed[0]].error or "Every language failed.")
        self._report("Done", 1.0, force=True)
        return outputs

    def _add_output(self, outputs: list, path: Path, kind: str, lang: str):
        item = {"path": str(path), "name": path.name, "kind": kind, "lang": lang}
        outputs.append(item)
        self._p.outputs.append(item)

    # ── speakers / voices ─────────────────────────────────────

    def _voices(self, audio: np.ndarray, lines: list[Line], job: DubJob) -> dict[int, tuple]:
        """Assign a speaker to every line and get a voice (XTTS latents) for each."""
        synth = self.engine.synth
        diar = self.engine.diar
        clips = [audio[int(ln.start * SR): int(ln.end * SR)] for ln in lines]
        voiced = [voiced_seconds(c, SR) for c in clips]
        if diar.pipeline is not None and job.voice_mode == "match":
            embs = []
            for i, c in enumerate(clips):
                self._check()
                # Short lines (a word or two) can still be matched to a voice that
                # longer lines established; they just never start a new speaker.
                embs.append(diar.embed(c) if voiced[i] >= 0.5 else None)
            thr = float(self.cfg.get("speaker_id", {}).get("threshold", 0.62))
            labels = cluster_speakers(embs, voiced, thr, times=[ln.start for ln in lines])
        else:
            labels = [0] * len(lines)
        for ln, lab in zip(lines, labels):
            ln.speaker = lab
        n_spk = max(labels) + 1
        self.log(f"{n_spk} speaker{'s' if n_spk > 1 else ''} found.")

        voices: dict[int, tuple] = {}
        for spk in range(n_spk):
            self._check()
            lat = None
            if job.voice_mode == "match":
                # Reference: the speaker's longest lines, up to ~15 s.
                mine = sorted((i for i in range(len(lines)) if labels[i] == spk),
                              key=lambda i: -voiced[i])
                ref, got = [], 0.0
                for i in mine:
                    ref.append(clips[i])
                    got += len(clips[i]) / SR
                    if got >= 15:
                        break
                if got >= 3:
                    lat = synth.latents_from_audio(np.concatenate(ref), SR, f"file_speaker_{spk}")
            if lat is None:                     # too little audio, or one-voice mode
                lat = synth.preset_latents(f"file:Speaker {spk + 1}")
            if lat is None:
                raise RuntimeError("Could not prepare a voice.")
            voices[spk] = lat
        return voices

    # ── one target language ───────────────────────────────────

    def _one_language(self, job, src, info, audio, lines, src_lang, tgt, voices, bg, total,
                      start_s, out_dir, tmp, mode, vcodec, base, weight) -> list[dict]:
        st = self._p.langs[tgt]
        name = languages.name(tgt)
        st.state, st.total = "translating", len(lines)
        self._report(f"{name}: translating", base, force=True)
        texts = self._translate(audio, lines, src_lang, tgt)
        self._check()

        st.state = "voicing"
        track = self._voice_track(lines, texts, tgt, voices, total, st, base + 0.1 * weight,
                                  0.85 * weight, name)
        if bg is not None:
            track = self._mix_background(track, bg)

        st.state = "saving"
        self._report(f"{name}: saving", base + 0.95 * weight, force=True)
        title = f"{name} (Ominvox)"
        out: list[dict] = []
        if mode == "separate":
            ext = "." + job.audio_format.lower().lstrip(".")
            p = _unique(out_dir / f"{src.stem}.{tgt}{ext}")
            media.write_audio(p, track, VOICE_SR, languages.iso2(tgt), title)
            out.append({"path": str(p), "kind": "audio"})
        else:
            tpath = tmp / f"{tgt}.mka"
            media.write_audio(tpath, track, VOICE_SR, languages.iso2(tgt), title, codec=vcodec)
            if mode == "add":
                out.append({"path": str(tpath), "kind": "track", "lang": tgt})
            else:                               # replace: one video per language
                ext, _ = media.video_target(src)
                dst = _unique(out_dir / f"{src.stem}.{tgt}{ext}")
                media.mux_video(src, dst, [{"path": tpath, "default": True}],
                                keep_audio=False, start_s=start_s)
                out.append({"path": str(dst), "kind": "video"})
        if job.subtitles:
            p = write_srt(_unique(out_dir / f"{src.stem}.{tgt}.srt"), lines, texts)
            out.append({"path": str(p), "kind": "subtitles"})
        return out

    def _translate(self, audio, lines, src_lang, tgt) -> list[str]:
        texts = [ln.text for ln in lines]
        if tgt == src_lang:
            return texts
        if tgt == "en":                 # Whisper translates to English best, no download
            return self._whisper_english(audio, lines, src_lang)
        if not self.nllb_ok:
            raise RuntimeError("Needs the translator - download it in Setup.")
        if not Translator.supports(src_lang):        # go through English
            texts, src_lang = self._whisper_english(audio, lines, src_lang), "en"
        out = self.engine.mt.translate_batch(texts, src_lang, tgt, beams=4)
        if out is None:
            raise RuntimeError("The translator could not be loaded.")
        return out

    def _whisper_english(self, audio, lines, src_lang) -> list[str]:
        """Whisper's own translate-to-English, line by line (no translator needed)."""
        model = self.engine.stt.model
        out = []
        for ln in lines:
            self._check()
            clip = audio[int(ln.start * SR): int(ln.end * SR)]
            segs, _ = model.transcribe(clip, language=src_lang, task="translate", beam_size=5,
                                       condition_on_previous_text=False)
            out.append(" ".join(s.text.strip() for s in segs).strip())
        return out

    def _voice_track(self, lines, texts, tgt, voices, total, st, base, weight, name) -> np.ndarray:
        """Speak every line and place it where the original line started. Lines that
        come out longer than the gap before the next line are re-spoken faster
        (up to max_speedup); anything still too long pushes the next line later."""
        synth = self.engine.synth
        lang = xtts_lang(tgt)
        if lang is None:
            raise RuntimeError(f"The voice model can't speak {name}.")
        limit = 200 if lang not in ("zh-cn", "ja", "ko") else 70
        track = np.zeros(total, np.float32)
        cursor = 0.0
        spc = None                                       # seconds per character at speed 1
        for i, (ln, text) in enumerate(zip(lines, texts)):
            self._check()
            st.done = i
            self._report(f"{name}: voice {i + 1} of {len(lines)}", base + weight * i / len(lines))
            if not text:
                continue
            start = max(ln.start, cursor)
            # the last line must fit before the file ends
            slot_end = lines[i + 1].start if i + 1 < len(lines) else max(ln.end, total / VOICE_SR - 0.1)
            slot = max(0.4, slot_end - start)
            speed = 1.0
            if spc:
                speed = float(np.clip(len(text) * spc / slot, 1.0, self.max_speed))
            lat = voices.get(ln.speaker) or next(iter(voices.values()))
            wav = self._speak(synth, text, lang, lat, speed, limit)
            if wav is None or not len(wav):
                continue
            dur = len(wav) / VOICE_SR
            est = dur * speed / max(1, len(text))
            spc = est if spc is None else 0.7 * spc + 0.3 * est
            if dur > slot * 1.1 and speed < self.max_speed:
                faster = min(self.max_speed, speed * dur / slot)
                again = self._speak(synth, text, lang, lat, faster, limit)
                if again is not None and len(again):
                    wav = again
            late = start - ln.start
            if late > 0.3:
                st.late_lines += 1
                st.late_max = round(max(st.late_max, late), 2)
            a = int(start * VOICE_SR)
            if a + len(wav) > len(track):
                track = np.concatenate([track, np.zeros(a + len(wav) - len(track), np.float32)])
            track[a:a + len(wav)] += wav
            cursor = start + len(wav) / VOICE_SR + 0.05
            self._p.preview = {"lang": tgt, "speaker": f"Speaker {ln.speaker + 1}",
                               "src": ln.text, "text": text, "at": round(ln.start, 1)}
        st.done = len(lines)
        peak = float(np.abs(track).max()) if len(track) else 0.0
        return track / peak * 0.95 if peak > 0.95 else track

    def _speak(self, synth, text, lang, lat, speed, limit) -> np.ndarray | None:
        """One line of speech. XTTS sometimes babbles on after short text, so an
        implausibly long result is re-spoken once and, if still too long, cut."""
        per_char = 0.3 if lang in ("zh-cn", "ja", "ko") else 0.12
        longest = (1.0 + len(text) * per_char) / speed
        best = None
        for _ in range(2):
            wav = synth.speak_latents(text, lang, lat, speed=speed, split=len(text) > limit)
            if wav is None or not len(wav):
                return best
            wav = trim_silence(wav)
            if best is None or len(wav) < len(best):
                best = wav
            if len(best) <= longest * VOICE_SR:
                return best
        cut = int(longest * VOICE_SR)
        fade = min(cut, int(0.03 * VOICE_SR))
        best = best[:cut].copy()
        best[cut - fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        return best

    def _mix_background(self, voice: np.ndarray, bg: np.ndarray) -> np.ndarray:
        """Original sound underneath, turned further down while the voice speaks.
        The loudness envelope is worked out in 10 ms blocks (cheap on long films)."""
        n = len(voice)
        bg = bg[:n]
        if len(bg) < n:
            bg = np.concatenate([bg, np.zeros(n - len(bg), np.float32)])
        block = VOICE_SR // 100
        nb = -(-n // block)
        padded = np.zeros(nb * block, np.float32)
        padded[:n] = np.abs(voice)
        talking = (padded.reshape(nb, block).max(axis=1) > 1e-3).astype(np.float32)
        env = np.convolve(talking, np.ones(51, np.float32) / 51, mode="same")   # ±0.25 s
        gain = self.bg_volume * (1 - 0.6 * np.minimum(1.0, env * 3))
        mix = voice + bg * np.repeat(gain.astype(np.float32), block)[:n]
        peak = float(np.abs(mix).max())
        return mix / peak * 0.95 if peak > 0.95 else mix

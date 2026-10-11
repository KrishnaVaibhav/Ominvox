"""Ties the stages together: capture -> VAD -> diarize -> STT -> MT -> TTS -> play.

Threads:
  seg-builder   groups VAD-gated capture chunks into whole utterances  -> _seg_q
  gpu-worker    text stage (speaker ID -> speech-to-text -> translation),
                then voice stage (XTTS)                                -> player
  player        plays each clip (asap or fixed-lag schedule)

One GPU worker on purpose. Measured on an 8 GB card: a second worker (text and
voice in parallel) and loading the models in parallel each cost ~0.6 GB more
VRAM (per-thread CUDA workspaces), pushing the card into shared memory -
voice synthesis went from ~1.0 s to ~3.6 s per line, and a 12-line burst took
28 s instead of 18 s.
"""
from __future__ import annotations
import itertools
import queue
import threading
import time
import numpy as np

from ..audio.capture import LoopbackCapture
from ..audio.player import Player
from .engine import Engine
from .speaker_id import VoiceProfileStore
from .metrics import Metrics


def voiced_seconds(audio: np.ndarray, sr: int) -> float:
    """Seconds of actual voice in a clip (20 ms frames with real energy). Segments
    carry trailing silence, so their raw length overstates how much speech
    the speaker embedding had to work with."""
    frame = max(1, sr // 50)
    n = len(audio) // frame
    if n == 0:
        return 0.0
    rms = np.sqrt((audio[: n * frame].reshape(n, frame) ** 2).mean(axis=1))
    return float((rms > max(0.1 * rms.max(), 1e-4)).sum()) * frame / sr


class Pipeline:
    def __init__(self, cfg: dict, log=print, notify=None, engine: Engine | None = None):
        self.cfg = cfg
        self.log = log
        self._notify = notify or (lambda _evt: None)
        self.capture = LoopbackCapture.from_cfg(cfg)
        log("Loading models…")
        self.engine = engine or Engine(cfg, log=log)
        self.engine.load_all()
        self.metrics = Metrics()
        self.player = Player(cfg, on_play=self._on_play)
        self._ids = itertools.count(1)
        log("Pipeline ready — play your movie.")
        # (audio, timing) pairs; timing holds monotonic seg_start / speech_end / flush_t
        self._seg_q: queue.Queue[tuple[np.ndarray, dict]] = queue.Queue(maxsize=8)
        self._done = threading.Event()
        # Restartable listening state. Models above stay loaded across start/stop
        # so toggling Listen does NOT reload Whisper/pyannote/XTTS or re-grab VRAM.
        self._listening = False
        self._workers: list[threading.Thread] = []

        vad_cfg = cfg.get("vad", {})
        self._silence_thresh: int = int(vad_cfg.get("silence_chunks", 5))
        self._max_seg_s: float = float(vad_cfg.get("max_segment_s", 8.0))

        sid_cfg = cfg.get("speaker_id", {})
        self.profiles = VoiceProfileStore(
            speaker_dir=cfg["_speaker_dir"],
            threshold=float(sid_cfg.get("threshold", VoiceProfileStore.DEFAULT_THRESHOLD)),
        )
        # Lines with less actual speech than this give unreliable voice
        # embeddings (measured: one-word lines have <= 1.45 s of voiced audio).
        self._min_id_seconds = float(sid_cfg.get("min_seconds", 1.6))

    # The models live in the shared Engine (file translation uses them too).
    vad = property(lambda self: self.engine.vad)
    diar = property(lambda self: self.engine.diar)
    stt = property(lambda self: self.engine.stt)
    mt = property(lambda self: self.engine.mt)
    synth = property(lambda self: self.engine.synth)

    # ------------------------------------------------------------------
    # Segment accumulator (runs in main thread)
    # ------------------------------------------------------------------

    def _build_segments(self):
        """Group VAD-gated chunks into utterances and put them in _seg_q.
        Tracks when each utterance's speech started/ended (capture timestamps)."""
        sr = self.cfg["audio"]["sample_rate"]
        max_samples = int(self._max_seg_s * sr)
        buf: list[np.ndarray] = []
        buf_len = 0   # running sample count — avoids O(n) sum() every chunk
        silence_run = 0
        seg_start = speech_end = 0.0

        def flush():
            nonlocal buf, buf_len, silence_run
            self._flush(buf, {"seg_start": seg_start, "speech_end": speech_end})
            buf, buf_len, silence_run = [], 0, 0

        for t_end, chunk in self.capture.chunks(with_time=True):
            if self._done.is_set():
                break

            if chunk is None:
                # No audio arrived (source paused). Count it as silence so the
                # last sentence before a pause is flushed instead of stuck.
                if buf:
                    silence_run += 1
                    if silence_run >= self._silence_thresh:
                        flush()
                continue

            if self.vad.is_speech(chunk):
                if not buf:
                    seg_start = t_end - len(chunk) / sr
                speech_end = t_end
                buf.append(chunk)
                buf_len += len(chunk)
                silence_run = 0
                if buf_len >= max_samples:
                    flush()
            else:
                if buf:
                    silence_run += 1
                    buf.append(chunk)
                    buf_len += len(chunk)
                    if silence_run >= self._silence_thresh:
                        flush()
                # If no speech buffered yet, skip silent chunks entirely

    def _flush(self, chunks: list[np.ndarray], timing: dict | None = None):
        audio = np.concatenate(chunks)
        timing = dict(timing or {})
        timing["flush_t"] = time.monotonic()
        try:
            self._seg_q.put((audio, timing), timeout=2.0)
        except queue.Full:
            # drop on sustained backpressure to avoid falling ever further behind
            self.metrics.count("segments_dropped")

    # ------------------------------------------------------------------
    # GPU worker (separate thread)
    # ------------------------------------------------------------------

    def _gpu_worker(self):
        """Drain _seg_q: text stage, then voice stage, one utterance at a time."""
        while not self._done.is_set():
            try:
                audio, timing = self._seg_q.get(timeout=0.5)
            except queue.Empty:
                continue
            # Never let one bad utterance kill the worker (the pipeline would go
            # deaf after the first hiccup). Log it and keep going.
            try:
                self._process_utterance(audio, timing)
            except Exception as exc:
                self.metrics.count("errors")
                self.log(f"[worker] skipped an utterance ({type(exc).__name__}: {exc})")

    def _process_utterance(self, audio: np.ndarray, timing: dict | None = None):
        """Run one utterance through every stage."""
        job = self._text_stage(audio, timing)
        if job is not None:
            self._voice_stage(job)

    def _text_stage(self, audio: np.ndarray, timing: dict | None = None) -> dict | None:
        sr = self.cfg["audio"]["sample_rate"]
        now = time.monotonic
        t0 = now()
        timing = timing or {}
        line = {"audio_s": len(audio) / sr, "work_t": t0}
        # Without capture timestamps (tests / direct calls) treat "now" as the start.
        line["seg_start"] = timing.get("seg_start") or t0 - len(audio) / sr
        line["speech_end"] = timing.get("speech_end") or t0
        line["flush_t"] = timing.get("flush_t", t0)
        line["queue"] = t0 - line["flush_t"]

        pyannote_label, embedding = self.diar.label_and_embed(audio)
        display_name = self.profiles.resolve(
            pyannote_label, embedding,
            reliable=voiced_seconds(audio, sr) >= self._min_id_seconds)
        # TTS voice cloning keyed on display name so named speakers share a voice
        self.synth.registry.add_audio(display_name, audio)
        t1 = now(); line["diarize"] = t1 - t0

        text, src = self.stt.transcribe(audio, translate_to_en=self.mt.whisper_handles())
        t2 = now(); line["stt"] = t2 - t1
        if not text:
            self.metrics.count("lines_empty")
            return None

        translated, tgt = self.mt.translate_ex(text, src)
        t3 = now(); line["mt"] = t3 - t2

        line_id = next(self._ids)
        line.update(id=line_id, speaker=display_name)
        self.log(f"[{display_name}] {src}->{tgt}: {translated}")
        self._notify({
            "type": "utterance",
            "id": line_id,
            "speaker": display_name,
            "speaker_id": pyannote_label,
            "src_lang": src,
            "tgt_lang": tgt,
            "src_text": text,
            "translated": translated,
        })
        self._notify({"type": "speakers", "speakers": self.profiles.list_profiles()})
        return {"line": line, "text": translated, "speaker": display_name, "lang": tgt}

    def _voice_stage(self, job: dict):
        line = job["line"]
        t3 = time.monotonic()
        wav = self.synth.speak(job["text"], job["speaker"], language=job["lang"])
        t4 = time.monotonic(); line["tts"] = t4 - t3
        line["ready_t"] = t4
        if wav is None:
            self._emit_line(line)          # text only: no playback to wait for
        else:
            self.player.submit(wav, anchor=line["seg_start"], meta=line)

    def _on_play(self, line: dict):
        """Player callback: the translated line just started playing."""
        self._emit_line(line)

    def _emit_line(self, line: dict):
        summary = self.metrics.record(line)
        self._notify({"type": "line_metrics", **summary})

    def stats(self) -> dict:
        """Snapshot for the UI performance panel (called ~1x per second)."""
        return {
            "type": "stats",
            **self.metrics.rolling(),
            "system": self.metrics.system(),
            "queue_depth": self._seg_q.qsize(),
            "backlog_s": round(self.player.backlog_seconds(), 2),
            "sync_mode": self.player.sync_mode,
            "fixed_lag_ms": int(self.player.fixed_lag * 1000),
            "input_device": self.capture.device_name,
            "output_device": self.player.device_name,
            "input_dropped": self.capture.dropped_chunks,
            "listening": self._listening,
        }

    # ------------------------------------------------------------------
    # Speaker management (called from the UI thread)
    # ------------------------------------------------------------------

    def rename_speaker(self, old: str, new: str) -> bool:
        if not self.profiles.rename_profile(old, new):
            return False
        self.synth.registry.rename(old, new)
        return True

    def reload_diarizer(self):
        self.engine.reload_diarizer()

    def reload_voice(self):
        self.engine.reload_voice()

    def reset_speakers(self):
        self.profiles.clear()
        self.synth.registry.clear()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def start_listening(self):
        """Begin capture + processing. Safe to call again after stop_listening()
        — models stay loaded, only the capture/worker threads restart."""
        if self._listening:
            return
        self._done.clear()
        self.metrics.reset()
        try:                                     # drop anything left from last session
            while True:
                self._seg_q.get_nowait()
        except queue.Empty:
            pass
        self.capture.start()          # raises if the input device won't open
        try:
            self.player.start()       # raises if the output device won't open
        except Exception:
            self.capture.stop()
            raise
        self._workers = [
            threading.Thread(target=fn, daemon=True, name=name)
            for fn, name in ((self._gpu_worker, "gpu-worker"), (self._build_segments, "seg-builder"))]
        for t in self._workers:
            t.start()
        self._listening = True
        self.log("Ominvox listening. Play your movie.")

    def stop_listening(self):
        """Stop capture + processing but keep models loaded for a fast restart."""
        if not self._listening:
            return
        self._done.set()
        self.capture.stop()
        for t in self._workers:
            t.join(timeout=5)
        self.player.stop()
        self._listening = False
        self.log("Stopped listening.")

    def run(self):
        """Console entry point: listen until Ctrl+C."""
        self.start_listening()
        self.log("Running. Ctrl+C to stop.")
        try:
            while not self._done.is_set():
                time.sleep(0.3)
        except KeyboardInterrupt:
            self.log("Stopping...")
        finally:
            self.stop_listening()

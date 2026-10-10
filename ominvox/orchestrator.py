"""Ties the stages together: capture -> VAD -> diarize -> STT -> MT -> TTS -> play.

Architecture (Phase 3):
  Main thread: VAD-gated segment accumulation — groups raw 1-s chunks into full
               utterances (flush on silence or max length), puts them in _seg_q.
  GPU worker thread: drains _seg_q one utterance at a time:
               diarize -> STT -> MT -> TTS -> player.submit().
  Player thread: already runs independently with delay buffer.

This means accumulation and GPU processing overlap, and STT sees full utterances
(much better quality than per-chunk 1-s windows).
"""
from __future__ import annotations
import queue
import threading
import time
import numpy as np

from .capture import LoopbackCapture
from .vad import VAD
from .diarize import Diarizer
from .stt import STT
from .mt import Translator
from .voices import VoiceSynth
from .player import Player
from .speaker_id import VoiceProfileStore


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
    def __init__(self, cfg: dict, log=print, notify=None):
        self.cfg = cfg
        self.log = log
        self._notify = notify or (lambda _evt: None)
        log("Initialising capture…")
        self.capture = LoopbackCapture.from_cfg(cfg)
        log("Loading VAD…")
        self.vad = VAD(cfg["audio"]["sample_rate"])
        log("Loading diarizer…")
        self.diar = Diarizer(cfg)
        if self.diar.enabled and self.diar.pipeline is None:
            log("Speaker separation is OFF (Hugging Face token missing or not accepted) "
                "- everyone will share one voice. See README step 4-5.")
        log("Loading STT (Whisper)…")
        self.stt = STT(cfg)
        log("Preparing translation…")
        self.mt = Translator(cfg)
        log("Loading TTS (XTTS-v2)…")
        self.synth = VoiceSynth(cfg)
        self.player = Player(cfg)
        log("Pipeline ready — play your movie.")
        self._seg_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=8)
        self._done = threading.Event()
        # Restartable listening state. Models above stay loaded across start/stop
        # so toggling Listen does NOT reload Whisper/pyannote/XTTS or re-grab VRAM.
        self._listening = False
        self._gpu_t: threading.Thread | None = None
        self._builder_t: threading.Thread | None = None

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

    # ------------------------------------------------------------------
    # Segment accumulator (runs in main thread)
    # ------------------------------------------------------------------

    def _build_segments(self):
        """Group VAD-gated chunks into utterances and put them in _seg_q."""
        sr = self.cfg["audio"]["sample_rate"]
        max_samples = int(self._max_seg_s * sr)
        buf: list[np.ndarray] = []
        buf_len = 0   # running sample count — avoids O(n) sum() every chunk
        silence_run = 0

        for chunk in self.capture.chunks():
            if self._done.is_set():
                break

            if chunk is None:
                # No audio arrived (source paused). Count it as silence so the
                # last sentence before a pause is flushed instead of stuck.
                if buf:
                    silence_run += 1
                    if silence_run >= self._silence_thresh:
                        self._flush(buf)
                        buf = []
                        buf_len = 0
                        silence_run = 0
                continue

            if self.vad.is_speech(chunk):
                buf.append(chunk)
                buf_len += len(chunk)
                silence_run = 0
                if buf_len >= max_samples:
                    self._flush(buf)
                    buf = []
                    buf_len = 0
                    silence_run = 0
            else:
                if buf:
                    silence_run += 1
                    buf.append(chunk)
                    buf_len += len(chunk)
                    if silence_run >= self._silence_thresh:
                        self._flush(buf)
                        buf = []
                        buf_len = 0
                        silence_run = 0
                # If no speech buffered yet, skip silent chunks entirely

    def _flush(self, chunks: list[np.ndarray]):
        audio = np.concatenate(chunks)
        try:
            self._seg_q.put(audio, timeout=2.0)
        except queue.Full:
            pass  # drop on sustained backpressure to avoid falling ever further behind

    # ------------------------------------------------------------------
    # GPU worker (separate thread)
    # ------------------------------------------------------------------

    def _gpu_worker(self):
        """Drain _seg_q: diarize -> speaker-ID -> STT -> MT -> TTS -> player."""
        while not self._done.is_set():
            try:
                audio = self._seg_q.get(timeout=0.5)
            except queue.Empty:
                continue

            # CRITICAL: never let one bad utterance kill the worker. A raised
            # exception here used to stop ALL further processing (the pipeline
            # would "go deaf" after the first hiccup). Catch, log, keep going.
            try:
                self._process_utterance(audio)
            except Exception as exc:
                self.log(f"[worker] skipped an utterance ({type(exc).__name__}: {exc})")
                continue

    def _process_utterance(self, audio: np.ndarray):
        pyannote_label, embedding = self.diar.label_and_embed(audio)
        display_name = self.profiles.resolve(
            pyannote_label, embedding,
            reliable=voiced_seconds(audio, self.cfg["audio"]["sample_rate"]) >= self._min_id_seconds)

        # TTS voice cloning keyed on display name so named speakers share a voice
        self.synth.registry.add_audio(display_name, audio)

        text, src = self.stt.transcribe(audio, translate_to_en=self.mt.whisper_handles())
        if not text:
            return

        translated, tgt = self.mt.translate_ex(text, src)
        self.log(f"[{display_name}] {src}->{tgt}: {translated}")
        self._notify({
            "type": "utterance",
            "speaker": display_name,
            "speaker_id": pyannote_label,
            "src_lang": src,
            "tgt_lang": tgt,
            "src_text": text,
            "translated": translated,
        })
        # Broadcast updated speaker roster after each utterance
        self._notify({
            "type": "speakers",
            "speakers": {
                name: info
                for name, info in self.profiles.list_profiles().items()
            },
        })

        wav = self.synth.speak(translated, display_name, language=tgt)
        if wav is not None:
            self.player.submit(wav)

    # ------------------------------------------------------------------
    # Speaker management (called from the UI thread)
    # ------------------------------------------------------------------

    def rename_speaker(self, old: str, new: str) -> bool:
        if not self.profiles.rename_profile(old, new):
            return False
        self.synth.registry.rename(old, new)
        return True

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
        # Drop any stale segments left from a previous session.
        try:
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
        self._gpu_t = threading.Thread(target=self._gpu_worker, daemon=True, name="gpu-worker")
        self._gpu_t.start()
        self._builder_t = threading.Thread(target=self._build_segments, daemon=True, name="seg-builder")
        self._builder_t.start()
        self._listening = True
        self.log("Ominvox listening. Play your movie.")

    def stop_listening(self):
        """Stop capture + processing but keep models loaded for a fast restart."""
        if not self._listening:
            return
        self._done.set()
        self.capture.stop()
        if self._builder_t:
            self._builder_t.join(timeout=5)
        if self._gpu_t:
            self._gpu_t.join(timeout=5)
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

"""The AI models, loaded once and shared by live listening and file translation.

Each model loads on first use, so e.g. detecting a file's language only loads
Whisper. `load_all()` loads the rest (in the order the live pipeline needs them)
and warms them up. Only one job uses the models at a time (the UI refuses to
start file translation while listening, and the other way round): two jobs on
an 8 GB card push it into shared memory and both slow down several times.
"""
from __future__ import annotations
import threading
import numpy as np

from .vad import VAD
from .diarize import Diarizer
from .stt import STT
from .mt import Translator
from .voices import VoiceSynth


class Engine:
    def __init__(self, cfg: dict, log=print):
        self.cfg = cfg
        self.log = log
        self._vad = self._diar = self._stt = self._mt = self._synth = None
        self._lock = threading.RLock()
        self._warm = False

    # Lazy accessors: the first caller loads the model, later callers share it.
    def _get(self, attr: str, factory):
        if getattr(self, attr) is None:
            with self._lock:
                if getattr(self, attr) is None:
                    setattr(self, attr, factory())
        return getattr(self, attr)

    @property
    def vad(self) -> VAD:
        return self._get("_vad", lambda: VAD(self.cfg["audio"]["sample_rate"]))

    @property
    def diar(self) -> Diarizer:
        return self._get("_diar", lambda: Diarizer(self.cfg))

    @property
    def stt(self) -> STT:
        return self._get("_stt", lambda: STT(self.cfg))

    @property
    def mt(self) -> Translator:
        return self._get("_mt", lambda: Translator(self.cfg))

    @property
    def synth(self) -> VoiceSynth:
        return self._get("_synth", lambda: VoiceSynth(self.cfg))

    def load_all(self, warmup: bool = True):
        with self._lock:
            for name in ("vad", "diar", "stt", "mt", "synth"):
                getattr(self, name)
            if self.diar.enabled and self.diar.pipeline is None:
                self.log("Speaker separation is OFF (Hugging Face token missing or not accepted) "
                         "- everyone will share one voice. Open Setup to add it.")
            if self.synth.tts is None:
                self.log("Voice is OFF (licence not agreed) - translations are shown as text. "
                         "Open Setup to turn it on.")
            if warmup and not self._warm:
                self._warmup()
                self._warm = True

    def _warmup(self):
        """Run every model once so the first real line isn't slowed by CUDA kernel
        compilation / lazy loading (measured: first line 13.5 s vs ~5.5 s after)."""
        self.log("Warming up models…")
        sr = self.cfg["audio"]["sample_rate"]
        noise = (np.random.default_rng(0).standard_normal(sr * 2) * 0.01).astype(np.float32)
        for name, fn in (
            ("speaker ID", lambda: self.diar.label_and_embed(noise)),
            ("speech-to-text", lambda: self.stt.transcribe(noise)),
            ("translation", lambda: self.mt.translate_ex("Hello there.", "en")
                if not self.mt.whisper_handles() else None),
            ("voice", lambda: self.synth.speak("Hello there.", "__warmup__")),
        ):
            try:
                fn()
            except Exception as exc:
                self.log(f"Warm-up of {name} failed ({exc}) - continuing.")

    # ── reloads after the setup screen changes something ──────

    def reload_diarizer(self):
        self._diar = Diarizer(self.cfg)

    def reload_voice(self):
        self._synth = VoiceSynth(self.cfg)

    @property
    def diar_loaded(self) -> Diarizer | None:
        return self._diar

    @property
    def synth_loaded(self) -> VoiceSynth | None:
        return self._synth

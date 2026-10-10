"""Speech-to-text with faster-whisper. Returns (text, source_lang).
Can also do the cheap translate-to-English path."""
from __future__ import annotations
import numpy as np

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover
    WhisperModel = None


class STT:
    def __init__(self, cfg: dict):
        self.cfg = cfg["stt"]
        self.source_lang = cfg["translate"]["source_lang"]
        self.model = None
        if WhisperModel is not None:
            self.model = WhisperModel(
                self.cfg["model"],
                device=self.cfg["device"],
                compute_type=self.cfg["compute_type"],
                download_root=str(cfg["_cache_dir"] / "whisper"),
            )

    def transcribe(self, audio: np.ndarray, translate_to_en: bool = False):
        if self.model is None:
            return "", "en"
        lang = None if self.source_lang == "auto" else self.source_lang
        segments, info = self.model.transcribe(
            audio,
            language=lang,
            task="translate" if translate_to_en else "transcribe",
            vad_filter=True,
            beam_size=1,          # fast/greedy for live use
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language

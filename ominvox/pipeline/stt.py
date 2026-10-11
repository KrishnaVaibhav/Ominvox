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
        self._translate_cfg = cfg["translate"]   # read live: the UI can change it
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
        src = self._translate_cfg.get("source_lang", "auto")
        lang = None if src in (None, "", "auto") else src
        segments, info = self.model.transcribe(
            audio,
            language=lang,
            task="translate" if translate_to_en else "transcribe",
            vad_filter=True,
            beam_size=1,          # fast/greedy for live use
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language

    # ── whole files ───────────────────────────────────────────

    def detect_language(self, audio: np.ndarray) -> tuple[str, float, list[tuple[str, float]]]:
        """(language, probability, top candidates) from the speech in `audio`
        (silence and music are skipped, so a quiet intro doesn't fool it)."""
        if self.model is None:
            return "en", 0.0, []
        lang, prob, all_probs = self.model.detect_language(
            audio, vad_filter=True, language_detection_segments=4)
        return lang, float(prob), [(l, float(p)) for l, p in all_probs[:5]]

    def transcribe_timed(self, audio: np.ndarray, language: str | None = None,
                         task: str = "transcribe", progress=None):
        """Timed lines for a whole file: ([(start_s, end_s, text)], language).
        Uses beam search (more accurate than the live path; speed matters less)
        and word timestamps: lines start and end exactly where the words do, and
        a segment is split where one sentence ends and a pause follows (that is
        usually where the speaker changes). `progress(fraction)` is called as
        segments come out."""
        if self.model is None:
            return [], language or "en"
        segments, info = self.model.transcribe(
            audio, language=language, task=task, vad_filter=True, beam_size=5,
            word_timestamps=True,
            condition_on_previous_text=False)   # avoids repeated-line loops on long files
        total = max(1e-6, len(audio) / 16000)
        out = []
        for seg in segments:                     # generator: decoding happens here
            out += _split_at_pauses(seg)
            if progress:
                progress(min(1.0, seg.end / total))
        return out, info.language


def _split_at_pauses(seg, min_pause: float = 0.25) -> list[tuple[float, float, str]]:
    words = [w for w in (seg.words or []) if w.word.strip()]
    if not words:
        text = seg.text.strip()
        return [(float(seg.start), float(seg.end), text)] if text else []
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        ends_sentence = w.word.strip()[-1:] in ".!?。！？"
        if nxt is None or (ends_sentence and nxt.start - w.end >= min_pause):
            text = "".join(x.word for x in cur).strip()
            if text:
                lines.append((float(cur[0].start), float(cur[-1].end), text))
            cur = []
    return lines

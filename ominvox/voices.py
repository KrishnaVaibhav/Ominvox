"""Per-speaker voice registry + TTS (XTTS-v2).

Collects reference audio per speaker, saves it as a WAV, then caches the XTTS
conditioning latents (gpt_cond_latent + speaker_embedding) so subsequent lines
from the same speaker skip the latent-computation step entirely.

Until a speaker has enough reference audio to be cloned (tts.min_ref_seconds),
their lines are spoken with one of XTTS's built-in voices, picked per speaker so
different people still sound different during the warm-up.
"""
from __future__ import annotations
import re
import sys
import threading
import zlib
from pathlib import Path
import numpy as np
import soundfile as sf

try:
    import torch
    from TTS.api import TTS as CoquiTTS
except Exception:  # pragma: no cover
    torch = None
    CoquiTTS = None

# Languages XTTS-v2 can speak (its config.json "languages").
XTTS_LANGS = {"en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl",
              "cs", "ar", "zh-cn", "hu", "ko", "ja", "hi"}

# Built-in XTTS voices used before a speaker can be cloned (mixed male/female).
BUILTIN_POOL = ["Andrew Chipper", "Claribel Dervla", "Damien Black", "Ana Florence",
                "Craig Gutsy", "Daisy Studious", "Viktor Eka", "Sofia Hellen"]
DEFAULT_BUILTIN = "Claribel Dervla"


def xtts_lang(code: str | None) -> str | None:
    """ISO code -> XTTS language code, or None if XTTS can't speak it."""
    if not code:
        return None
    code = code.lower()
    if code in ("zh", "zh-cn", "zh-hans"):
        return "zh-cn"
    return code if code in XTTS_LANGS else None


def safe_filename(name: str) -> str:
    """Speaker names come from the UI; keep only filesystem-safe characters."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned[:80] or "speaker"


class SpeakerRegistry:
    """Accumulates reference audio per speaker until we have enough to clone."""

    def __init__(self, cfg: dict):
        self.sr = cfg["audio"]["sample_rate"]
        self.min_ref = cfg["tts"]["min_ref_seconds"]
        self.dir = Path(cfg["_speaker_dir"])
        self._buf: dict[str, list[np.ndarray]] = {}
        self._ref: dict[str, Path] = {}
        # Cached XTTS conditioning latents: key -> (gpt_cond_latent, speaker_embedding)
        self._latents: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def add_audio(self, speaker: str, audio: np.ndarray):
        with self._lock:
            if speaker in self._ref:
                return
            self._buf.setdefault(speaker, []).append(audio)
            total = sum(len(a) for a in self._buf[speaker]) / self.sr
            if total >= self.min_ref:
                ref = np.concatenate(self._buf[speaker])
                self.dir.mkdir(parents=True, exist_ok=True)
                path = self.dir / f"{safe_filename(speaker)}.wav"
                sf.write(path, ref, self.sr)
                self._ref[speaker] = path
                self._buf[speaker] = []

    def reference(self, speaker: str) -> Path | None:
        return self._ref.get(speaker)

    def latents(self, key: str) -> tuple | None:
        return self._latents.get(key)

    def set_latents(self, key: str, gpt_cond_latent, speaker_embedding):
        self._latents[key] = (gpt_cond_latent, speaker_embedding)

    def rename(self, old: str, new: str):
        """Carry collected audio / cloned voice over to the new display name."""
        with self._lock:
            if old in self._buf:
                self._buf.setdefault(new, []).extend(self._buf.pop(old))
            if old in self._ref and new not in self._ref:
                self._ref[new] = self._ref.pop(old)
            old_key, new_key = f"ref:{old}", f"ref:{new}"
            if old_key in self._latents and new_key not in self._latents:
                self._latents[new_key] = self._latents.pop(old_key)

    def clear(self):
        with self._lock:
            self._buf.clear()
            self._ref.clear()
            self._latents.clear()


class VoiceSynth:
    def __init__(self, cfg: dict):
        self.cfg = cfg["tts"]
        self._root_cfg = cfg
        self.registry = SpeakerRegistry(cfg)
        self.tts = None
        self._warned_langs: set[str] = set()
        if CoquiTTS is not None and self.cfg["backend"] == "xtts":
            self.tts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2")
            if torch is not None and torch.cuda.is_available():
                self.tts.to("cuda")

    @property
    def target(self) -> str:
        # Read live so a target change in the UI applies without a restart.
        return self._root_cfg["translate"]["target_lang"]

    # ── voice selection ───────────────────────────────────────

    def _builtin_names(self) -> list[str]:
        try:
            return list(self.tts.synthesizer.tts_model.speaker_manager.speakers)
        except Exception:
            return []

    def _builtin_for(self, speaker: str) -> str | None:
        names = self._builtin_names()
        if not names:
            return None
        if self.cfg["voice_mode"] == "single":
            wanted = self.cfg.get("fallback_voice") or DEFAULT_BUILTIN
            return wanted if wanted in names else names[0]
        pool = [n for n in BUILTIN_POOL if n in names] or names
        return pool[zlib.crc32(speaker.encode("utf-8")) % len(pool)]

    def _voice_for(self, speaker: str) -> tuple[str, str] | None:
        """Pick the voice for this speaker: ('wav', path) or ('builtin', name)."""
        mode = self.cfg["voice_mode"]
        preset = self.cfg.get("preset_voice") or ""
        if mode in ("single", "preset") and preset and Path(preset).is_file():
            return "wav", preset
        if mode == "match":
            ref = self.registry.reference(speaker)
            if ref:
                return "wav", str(ref)
        name = self._builtin_for(speaker)
        return ("builtin", name) if name else None

    def _latents_for(self, kind: str, value: str, speaker: str) -> tuple | None:
        key = f"ref:{speaker}" if (kind == "wav" and self.cfg["voice_mode"] == "match") \
            else f"{kind}:{value}"
        cached = self.registry.latents(key)
        if cached is not None:
            return cached
        try:
            m = self.tts.synthesizer.tts_model
            if kind == "builtin":
                spk = m.speaker_manager.speakers[value]
                lat = (spk["gpt_cond_latent"], spk["speaker_embedding"])
            else:
                c = self.tts.synthesizer.tts_config
                lat = m.get_conditioning_latents(
                    audio_path=[value],
                    gpt_cond_len=c.gpt_cond_len,
                    max_ref_length=c.max_ref_len,
                    sound_norm_refs=c.sound_norm_refs,
                )
        except Exception:
            return None
        self.registry.set_latents(key, *lat)
        return lat

    # ── synthesis ─────────────────────────────────────────────

    def speak(self, text: str, speaker: str, language: str | None = None) -> np.ndarray | None:
        """Translated text -> waveform at the XTTS native sample rate (24 kHz).
        `language` is the language `text` is actually in (defaults to the target)."""
        if not text or self.tts is None:
            return None
        lang = xtts_lang(language or self.target)
        if lang is None:
            code = language or self.target
            if code not in self._warned_langs:
                self._warned_langs.add(code)
                print(f"[tts] XTTS cannot speak '{code}' - showing text only. "
                      f"Supported: {', '.join(sorted(XTTS_LANGS))}", file=sys.stderr)
            return None

        voice = self._voice_for(speaker)
        if voice is None:
            return None
        kind, value = voice

        latents = self._latents_for(kind, value, speaker)
        if latents is not None:
            try:
                gpt_latent, spk_embed = latents
                out = self.tts.synthesizer.tts_model.inference(
                    text=text,
                    language=lang,
                    gpt_cond_latent=gpt_latent,
                    speaker_embedding=spk_embed,
                    temperature=0.7,
                )
                return np.asarray(out["wav"], dtype=np.float32)
            except Exception:
                pass  # fall through to the high-level API if the low-level one changed

        # Fallback: high-level API (slower, no latent cache)
        if kind == "builtin":
            wav = self.tts.tts(text=text, speaker=value, language=lang)
        else:
            wav = self.tts.tts(text=text, speaker_wav=value, language=lang)
        return np.asarray(wav, dtype=np.float32)

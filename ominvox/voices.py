"""Per-speaker voice registry + TTS (XTTS-v2).

Collects reference audio per speaker, saves it as a WAV, then caches the XTTS
conditioning latents (gpt_cond_latent + speaker_embedding) so subsequent lines
from the same speaker skip the latent-computation step entirely.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import soundfile as sf

try:
    import torch
    from TTS.api import TTS as CoquiTTS
except Exception:  # pragma: no cover
    torch = None
    CoquiTTS = None


class SpeakerRegistry:
    """Accumulates reference audio per speaker until we have enough to clone."""

    def __init__(self, cfg: dict):
        self.sr = cfg["audio"]["sample_rate"]
        self.min_ref = cfg["tts"]["min_ref_seconds"]
        self.dir = cfg["_speaker_dir"]
        self._buf: dict[str, list[np.ndarray]] = {}
        self._ref: dict[str, Path] = {}
        # Cached XTTS conditioning latents: speaker -> (gpt_cond_latent, speaker_embedding)
        self._latents: dict[str, tuple] = {}

    def add_audio(self, speaker: str, audio: np.ndarray):
        if speaker in self._ref:
            return
        self._buf.setdefault(speaker, []).append(audio)
        total = sum(len(a) for a in self._buf[speaker]) / self.sr
        if total >= self.min_ref:
            ref = np.concatenate(self._buf[speaker])
            path = self.dir / f"{speaker}.wav"
            sf.write(path, ref, self.sr)
            self._ref[speaker] = path
            self._buf[speaker] = []

    def reference(self, speaker: str) -> Path | None:
        return self._ref.get(speaker)

    def latents(self, speaker: str) -> tuple | None:
        return self._latents.get(speaker)

    def set_latents(self, speaker: str, gpt_cond_latent, speaker_embedding):
        self._latents[speaker] = (gpt_cond_latent, speaker_embedding)


class VoiceSynth:
    def __init__(self, cfg: dict):
        self.cfg = cfg["tts"]
        self.target = cfg["translate"]["target_lang"]
        self.registry = SpeakerRegistry(cfg)
        self.tts = None
        if CoquiTTS is not None and self.cfg["backend"] == "xtts":
            self.tts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2")
            if torch is not None and torch.cuda.is_available():
                self.tts.to("cuda")

    def _ref_for(self, speaker: str) -> str | None:
        mode = self.cfg["voice_mode"]
        if mode in ("single", "preset"):
            return self.cfg.get("preset_voice") or None
        ref = self.registry.reference(speaker)  # mode == "match"
        return str(ref) if ref else (self.cfg.get("preset_voice") or None)

    def _compute_latents(self, ref: str, speaker: str) -> tuple | None:
        """Compute and cache XTTS conditioning latents from a reference wav."""
        try:
            m = self.tts.synthesizer.tts_model
            c = self.tts.synthesizer.tts_config
            gpt_latent, spk_embed = m.get_conditioning_latents(
                audio_path=[ref],
                gpt_cond_len=c.gpt_cond_len,
                max_ref_length=c.max_ref_len,
                sound_norm_refs=c.sound_norm_refs,
            )
            self.registry.set_latents(speaker, gpt_latent, spk_embed)
            return gpt_latent, spk_embed
        except Exception:
            return None

    def speak(self, text: str, speaker: str) -> np.ndarray | None:
        """Translated text -> waveform at the XTTS native sample rate (24 kHz)."""
        if not text or self.tts is None:
            return None

        # Fast path: use cached conditioning latents (skip wav reload + latent recompute)
        cached = self.registry.latents(speaker)
        if cached is not None:
            try:
                gpt_latent, spk_embed = cached
                out = self.tts.synthesizer.tts_model.inference(
                    text=text,
                    language=self.target,
                    gpt_cond_latent=gpt_latent,
                    speaker_embedding=spk_embed,
                    temperature=0.7,
                )
                return np.asarray(out["wav"], dtype=np.float32)
            except Exception:
                pass  # fall through to wav-path if low-level API changed

        # Slow path: first synthesis for this speaker (or fallback if low-level API fails)
        ref = self._ref_for(speaker)
        if ref is None:
            return None  # not enough reference yet

        # Try to compute latents and use low-level inference (caches for next call)
        latents = self._compute_latents(ref, speaker)
        if latents is not None:
            try:
                gpt_latent, spk_embed = latents
                out = self.tts.synthesizer.tts_model.inference(
                    text=text,
                    language=self.target,
                    gpt_cond_latent=gpt_latent,
                    speaker_embedding=spk_embed,
                    temperature=0.7,
                )
                return np.asarray(out["wav"], dtype=np.float32)
            except Exception:
                pass

        # Ultimate fallback: high-level API (always works, no embedding cache benefit)
        wav = self.tts.tts(text=text, speaker_wav=ref, language=self.target)
        return np.asarray(wav, dtype=np.float32)

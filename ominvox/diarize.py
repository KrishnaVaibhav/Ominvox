"""Speaker diarization (pyannote). Returns a speaker label for an audio segment so
each movie voice gets its own cloned output voice.

Also exposes embed() — extracts a speaker embedding vector from the audio using
pyannote's internal WeSpeaker ResNet34 model (already in GPU memory from the
diarization pipeline, so no extra VRAM cost beyond initial setup).
"""
from __future__ import annotations
import os
import numpy as np

try:
    import torch
    from pyannote.audio import Pipeline, Inference
except Exception:  # pragma: no cover
    torch = None
    Pipeline = None
    Inference = None


class Diarizer:
    def __init__(self, cfg: dict):
        self.sr = cfg["audio"]["sample_rate"]
        self.enabled = cfg["diarize"]["enabled"]
        self._hf_token = cfg["diarize"].get("hf_token") or os.environ.get("HF_TOKEN") or None
        self.pipeline = None
        self._embed_infer = None  # lazy-initialised in embed()

        if self.enabled and Pipeline is not None:
            self.pipeline = Pipeline.from_pretrained(
                cfg["diarize"]["model"], token=self._hf_token
            )
            if torch is not None and torch.cuda.is_available():
                self.pipeline.to(torch.device("cuda"))

    # ── diarization ────────────────────────────────────────────

    def label(self, audio: np.ndarray) -> str:
        """Dominant speaker label for this segment ('SPEAKER_00', ...)."""
        if self.pipeline is None:
            return "SPEAKER_00"
        wav = torch.from_numpy(audio.copy()).unsqueeze(0)
        diar = self.pipeline({"waveform": wav, "sample_rate": self.sr})
        annotation = getattr(diar, "speaker_diarization",
                    getattr(diar, "annotation", diar))
        durations: dict[str, float] = {}
        for turn, _, spk in annotation.itertracks(yield_label=True):
            durations[spk] = durations.get(spk, 0.0) + turn.duration
        return max(durations, key=durations.get) if durations else "SPEAKER_00"

    # ── embedding ──────────────────────────────────────────────

    def _init_embed_infer(self):
        """Lazy-init: build an Inference object for whole-clip embedding.

        Tries to reuse the WeSpeaker model already loaded inside the diarization
        pipeline (no extra VRAM). Falls back to loading it independently (uses the
        HF cache — no re-download needed).
        """
        if Inference is None or torch is None:
            return

        # Attempt 1: extract the model object from pyannote's internal SpeakerEmbedding
        # sub-pipeline. Attribute names vary by pyannote.audio version so we try several.
        inner_model = None
        for attr in ("_embedding", "embedding"):
            sub = getattr(self.pipeline, attr, None)
            if sub is None:
                continue
            # sub may be a SpeakerEmbedding Pipeline that wraps a Model
            for model_attr in ("model_", "model", "_model"):
                m = getattr(sub, model_attr, None)
                if m is not None and hasattr(m, "parameters"):
                    inner_model = m
                    break
            # sub itself may already be an Inference/Model
            if inner_model is None and hasattr(sub, "parameters"):
                inner_model = sub
            if inner_model is not None:
                break

        try:
            if inner_model is not None:
                infer = Inference(inner_model, window="whole")
            else:
                # Load from HF cache (downloaded as a diarizer dependency)
                infer = Inference(
                    "pyannote/wespeaker-voxceleb-resnet34-LM",
                    window="whole",
                    use_auth_token=self._hf_token or True,
                )
            # Move to GPU if available (shares CUDA context with diarizer)
            if torch.cuda.is_available():
                infer.to(torch.device("cuda"))
            self._embed_infer = infer
        except Exception:
            self._embed_infer = None

    def embed(self, audio: np.ndarray) -> np.ndarray | None:
        """Return a unit-normalized speaker embedding vector, or None on failure."""
        if self.pipeline is None or torch is None:
            return None

        if self._embed_infer is None:
            self._init_embed_infer()
        if self._embed_infer is None:
            return None

        try:
            wav = torch.from_numpy(audio.copy()).unsqueeze(0)
            emb = self._embed_infer({"waveform": wav, "sample_rate": self.sr})
            arr = np.array(emb).flatten().astype(np.float32)
            norm = np.linalg.norm(arr)
            return arr / norm if norm > 1e-9 else arr
        except Exception:
            return None

    # ── combined ───────────────────────────────────────────────

    def label_and_embed(self, audio: np.ndarray) -> tuple[str, np.ndarray | None]:
        """Run diarization and embedding extraction in one call.

        Returns (pyannote_label, embedding) where embedding may be None if the
        embedding model is unavailable.
        """
        return self.label(audio), self.embed(audio)

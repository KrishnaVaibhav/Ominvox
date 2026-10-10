"""Silero VAD gate - only let speech through to the heavy stages."""
from __future__ import annotations
import numpy as np

try:
    import torch
except Exception:  # pragma: no cover
    torch = None


class VAD:
    def __init__(self, sample_rate: int = 16000, threshold: float = 0.5):
        self.sr = sample_rate
        self.threshold = threshold
        self.model = None
        if torch is not None:
            self.model, _ = torch.hub.load(
                "snakers4/silero-vad", "silero_vad", trust_repo=True
            )

    def is_speech(self, chunk: np.ndarray) -> bool:
        if self.model is None:
            return True  # no VAD available -> pass everything
        # Silero wants 512-sample (16k) frames; check a few across the chunk.
        win = 512
        probs = []
        for i in range(0, max(1, len(chunk) - win), win):
            seg = chunk[i:i + win]
            if len(seg) < win:
                break
            t = torch.from_numpy(seg.copy())
            probs.append(self.model(t, self.sr).item())
        return bool(probs) and max(probs) >= self.threshold

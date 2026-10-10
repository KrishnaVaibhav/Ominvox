"""Voice profile store: enroll, identify, and persist named speaker profiles.

Embeddings are extracted by the diarizer (pyannote's WeSpeaker sub-model).
Identification compares a new embedding against profile centroids using cosine
similarity. The match must exceed `threshold` to be accepted.

Persistence: JSON at {speaker_dir}/profiles.json — base64-encoded float32 arrays.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


# ── Embedding helpers ──────────────────────────────────────────────────────

def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.clip(np.dot(_unit(a), _unit(b)), -1.0, 1.0))

def _emb_to_b64(emb: np.ndarray) -> str:
    return base64.b64encode(emb.astype(np.float32).tobytes()).decode()

def _b64_to_emb(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=np.float32)


# ── Profile ────────────────────────────────────────────────────────────────

@dataclass
class SpeakerProfile:
    name: str
    embeddings: list[np.ndarray] = field(default_factory=list)
    MAX_STORED = 50  # cap per-profile memory

    @property
    def centroid(self) -> np.ndarray | None:
        if not self.embeddings:
            return None
        return _unit(np.mean(self.embeddings, axis=0))

    def add(self, emb: np.ndarray):
        emb = _unit(emb.flatten().astype(np.float32))
        self.embeddings.append(emb)
        if len(self.embeddings) > self.MAX_STORED:
            # Keep the most recent embeddings; they reflect the current voice best
            self.embeddings = self.embeddings[-self.MAX_STORED:]


# ── Store ──────────────────────────────────────────────────────────────────

class VoiceProfileStore:
    """Manages named speaker profiles with cosine-similarity identification.

    Flow inside the pipeline (per utterance):
      pyannote_label, embedding = diarizer.label_and_embed(audio)
      display_name = store.resolve(pyannote_label, embedding)
      # emit display_name to UI; store auto-updates the matched profile
    """

    PROFILES_FILE = "profiles.json"
    DEFAULT_THRESHOLD = 0.75

    def __init__(self, speaker_dir: Path, threshold: float = DEFAULT_THRESHOLD):
        self.dir = Path(speaker_dir)
        self.threshold = threshold
        self._profiles: dict[str, SpeakerProfile] = {}
        # pyannote label → display name (within session AND across sessions for named profiles)
        self._label_map: dict[str, str] = {}
        self._next_unknown = 1
        self._load()

    # ── persistence ────────────────────────────────────────────

    def _path(self) -> Path:
        return self.dir / self.PROFILES_FILE

    def _load(self):
        p = self._path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for name, info in data.get("profiles", {}).items():
                prof = SpeakerProfile(name=name)
                for b64 in info.get("embeddings", []):
                    try:
                        prof.embeddings.append(_b64_to_emb(b64))
                    except Exception:
                        pass
                self._profiles[name] = prof
            self._label_map = data.get("label_map", {})
            self._next_unknown = data.get("next_unknown", 1)
        except Exception:
            pass

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "threshold": self.threshold,
            "next_unknown": self._next_unknown,
            "profiles": {
                name: {"embeddings": [_emb_to_b64(e) for e in prof.embeddings]}
                for name, prof in self._profiles.items()
            },
            "label_map": self._label_map,
        }
        self._path().write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── identification ─────────────────────────────────────────

    def identify(self, embedding: np.ndarray) -> str | None:
        """Return name of best matching profile, or None if below threshold."""
        best_name, best_sim = None, self.threshold - 1e-9
        flat = embedding.flatten()
        for name, prof in self._profiles.items():
            c = prof.centroid
            if c is None:
                continue
            sim = _cosine(flat, c)
            if sim > best_sim:
                best_sim, best_name = sim, name
        return best_name

    def resolve(self, pyannote_label: str, embedding: np.ndarray | None) -> str:
        """Map a pyannote label to a display name.

        Priority:
          1. Manual label_map entry (user renamed this label)
          2. Embedding cosine match against enrolled profiles
          3. Auto-assign "Unknown N" (session-scoped, preserved across restarts)
        """
        # 1. Manual rename wins
        if pyannote_label in self._label_map:
            name = self._label_map[pyannote_label]
            if embedding is not None and name in self._profiles:
                prof = self._profiles[name]
                c = prof.centroid
                # Only update the profile with embeddings that are consistent with
                # the existing centroid — guards against pyannote mislabelling
                if c is None or _cosine(embedding.flatten(), c) >= self.threshold:
                    prof.add(embedding)
            return name

        # 2. Embedding match
        if embedding is not None:
            name = self.identify(embedding)
            if name:
                self._label_map[pyannote_label] = name
                self._profiles[name].add(embedding)
                return name

        # 3. Auto-assign Unknown N
        auto = f"Unknown {self._next_unknown}"
        self._next_unknown += 1
        self._label_map[pyannote_label] = auto
        self._profiles[auto] = SpeakerProfile(name=auto)
        if embedding is not None:
            self._profiles[auto].add(embedding)
        self.save()
        return auto

    # ── enrollment ─────────────────────────────────────────────

    def enroll(self, name: str, embedding: np.ndarray | None = None,
               pyannote_label: str | None = None):
        """Create/update a named profile; optionally bind a pyannote label to it."""
        if name not in self._profiles:
            self._profiles[name] = SpeakerProfile(name=name)
        if embedding is not None:
            self._profiles[name].add(embedding)
        if pyannote_label:
            # Remove any previous binding for this label
            old_name = self._label_map.get(pyannote_label)
            if old_name and old_name != name and old_name in self._profiles:
                # Don't delete old profile; just repoint the label
                pass
            self._label_map[pyannote_label] = name
        self.save()

    def rename_label(self, pyannote_label: str, new_name: str,
                     accumulated_embeddings: list[np.ndarray] | None = None):
        """Rename a pyannote label to a display name and transfer any accumulated embeddings."""
        old_name = self._label_map.get(pyannote_label)

        # Move embeddings from old auto-profile to new named profile (if old was Unknown N)
        if old_name and old_name != new_name and old_name.startswith("Unknown "):
            old_prof = self._profiles.pop(old_name, None)
            if old_prof:
                if new_name not in self._profiles:
                    self._profiles[new_name] = SpeakerProfile(name=new_name)
                self._profiles[new_name].embeddings.extend(old_prof.embeddings)

        if new_name not in self._profiles:
            self._profiles[new_name] = SpeakerProfile(name=new_name)

        if accumulated_embeddings:
            for emb in accumulated_embeddings:
                self._profiles[new_name].add(emb)

        self._label_map[pyannote_label] = new_name
        self.save()

    def delete_profile(self, name: str):
        self._profiles.pop(name, None)
        self._label_map = {k: v for k, v in self._label_map.items() if v != name}
        self.save()

    # ── queries ────────────────────────────────────────────────

    def list_profiles(self) -> dict[str, dict]:
        """Return per-profile summary for UI display."""
        return {
            name: {"utterances": len(prof.embeddings), "has_centroid": prof.centroid is not None}
            for name, prof in self._profiles.items()
        }

    def get_label_map(self) -> dict[str, str]:
        return dict(self._label_map)

    @property
    def profile_names(self) -> list[str]:
        return list(self._profiles.keys())

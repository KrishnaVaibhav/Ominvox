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
        if self.embeddings and self.embeddings[0].shape != emb.shape:
            # Embedding model changed (or stale test data): old vectors can't be
            # compared with new ones, so start this profile over.
            self.embeddings = []
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
    # Tuned by replaying a 4-voice dialogue (incl. two similar female voices)
    # through resolve(), 7 independent renders: 0.62 gave 0 splits / 1 merge;
    # 0.60 -> 0/2, 0.64 -> 1/1, 0.66 -> 2/1, 0.68 -> 2+ splits.
    DEFAULT_THRESHOLD = 0.62

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
                        prof.add(_b64_to_emb(b64))
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

    def best_match(self, embedding: np.ndarray) -> tuple[str | None, float]:
        """(closest profile name, cosine similarity) regardless of threshold."""
        best_name, best_sim = None, -1.0
        flat = embedding.flatten()
        for name, prof in self._profiles.items():
            c = prof.centroid
            if c is None or c.shape != flat.shape:   # different embedding model
                continue
            sim = _cosine(flat, c)
            if sim > best_sim:
                best_sim, best_name = sim, name
        return best_name, best_sim

    def identify(self, embedding: np.ndarray) -> str | None:
        """Return name of best matching profile, or None if below threshold."""
        name, sim = self.best_match(embedding)
        return name if name is not None and sim >= self.threshold else None

    def resolve(self, pyannote_label: str, embedding: np.ndarray | None,
                reliable: bool = True) -> str:
        """Map an utterance to a display name.

        pyannote diarizes each utterance on its own, so its labels restart at
        SPEAKER_00 every call and say nothing about identity across utterances.
        The voice embedding is therefore the source of truth:
          1. Embedding cosine match against known profiles
          2. No match -> new "Unknown N" profile
        The pyannote label is only used as a fallback when no embedding exists.

        reliable=False marks a short clip (a word or two). Its embedding is too
        noisy to trust: it is matched to the closest known speaker without being
        learned from, and never creates a new speaker unless none exist yet.
        """
        if embedding is not None and not reliable:
            name, _ = self.best_match(embedding)
            if name:
                return name
            return self._new_unknown(embedding)

        if embedding is not None:
            name = self.identify(embedding)
            if name:
                prof = self._profiles[name]
                prof.add(embedding)
                if len(prof.embeddings) % 5 == 0:   # persist learning without a write per line
                    self.save()
                return name
            return self._new_unknown(embedding)

        # No embedding model available: best effort via the label map.
        if pyannote_label in self._label_map:
            return self._label_map[pyannote_label]
        name = self._new_unknown(None)
        self._label_map[pyannote_label] = name
        self.save()
        return name

    def _new_unknown(self, embedding: np.ndarray | None) -> str:
        name = f"Unknown {self._next_unknown}"
        while name in self._profiles:
            self._next_unknown += 1
            name = f"Unknown {self._next_unknown}"
        self._next_unknown += 1
        self._profiles[name] = SpeakerProfile(name=name)
        if embedding is not None:
            self._profiles[name].add(embedding)
        self.save()
        return name

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

    def rename_profile(self, old_name: str, new_name: str) -> bool:
        """Rename a profile. If new_name already exists the two are merged
        (useful when one person was split into two "Unknown" profiles)."""
        if old_name == new_name or old_name not in self._profiles:
            return False
        old = self._profiles.pop(old_name)
        if new_name in self._profiles:
            for emb in old.embeddings:
                self._profiles[new_name].add(emb)
        else:
            old.name = new_name
            self._profiles[new_name] = old
        self._label_map = {k: (new_name if v == old_name else v)
                           for k, v in self._label_map.items()}
        self.save()
        return True

    def has_profile(self, name: str) -> bool:
        return name in self._profiles

    def clear(self):
        """Forget every speaker (e.g. when switching to a different movie)."""
        self._profiles.clear()
        self._label_map.clear()
        self._next_unknown = 1
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

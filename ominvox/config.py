"""Load config.yaml and pin all caches inside the project folder (never C:)."""
from __future__ import annotations
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent  # D:\GitHub\Ominvox


def _pin_caches(cache_dir: Path) -> None:
    """Force HF / torch / TTS downloads into the project-local cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    hf = cache_dir / "huggingface"
    os.environ.setdefault("HF_HOME", str(hf))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hf / "hub"))
    os.environ.setdefault("TORCH_HOME", str(cache_dir / "torch"))
    os.environ.setdefault("TTS_HOME", str(cache_dir / "tts"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))


def load(path: str | os.PathLike | None = None) -> dict:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cache_dir = (ROOT / cfg["paths"]["cache_dir"]).resolve()
    _pin_caches(cache_dir)
    cfg["_root"] = ROOT
    cfg["_cache_dir"] = cache_dir
    cfg["_speaker_dir"] = (ROOT / cfg["paths"]["speaker_dir"]).resolve()
    cfg["_speaker_dir"].mkdir(parents=True, exist_ok=True)
    return cfg

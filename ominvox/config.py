"""Load config.yaml and pin all caches inside the project folder (never C:)."""
from __future__ import annotations
import json
import os
import threading
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent  # D:\GitHub\Ominvox
# Choices made in the UI (devices, languages, sync) are saved here and applied
# on top of config.yaml at the next start. Gitignored; delete it to reset.
USER_SETTINGS = ROOT / "user_settings.json"
_save_lock = threading.Lock()


def _deep_update(base: dict, extra: dict) -> dict:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def load_user_settings() -> dict:
    try:
        return json.loads(USER_SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_user_settings(changes: dict) -> None:
    """Merge `changes` ({section: {key: value}}) into user_settings.json."""
    with _save_lock:
        data = _deep_update(load_user_settings(), changes)
        tmp = USER_SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(USER_SETTINGS)


def _pin_caches(cache_dir: Path) -> None:
    """Force HF / torch / TTS downloads into the project-local cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    hf = cache_dir / "huggingface"
    os.environ.setdefault("HF_HOME", str(hf))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hf / "hub"))
    os.environ.setdefault("TORCH_HOME", str(cache_dir / "torch"))
    os.environ.setdefault("TTS_HOME", str(cache_dir / "tts"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))


def _load_dotenv(env_path: Path) -> None:
    """Read KEY=VALUE lines from .env (gitignored) into os.environ, without overriding."""
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load(path: str | os.PathLike | None = None, user_settings: bool = False) -> dict:
    _load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if user_settings:
        _deep_update(cfg, load_user_settings())

    cache_dir = (ROOT / cfg["paths"]["cache_dir"]).resolve()
    _pin_caches(cache_dir)
    cfg["_root"] = ROOT
    cfg["_cache_dir"] = cache_dir
    cfg["_speaker_dir"] = (ROOT / cfg["paths"]["speaker_dir"]).resolve()
    cfg["_speaker_dir"].mkdir(parents=True, exist_ok=True)
    return cfg

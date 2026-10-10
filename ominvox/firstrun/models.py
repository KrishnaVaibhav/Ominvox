"""The AI models Ominvox needs: what they are, whether they're downloaded, and
downloading them with live progress (for the first-run screen).

Progress is measured from bytes on disk in each model's cache folder, so it
works the same for Hugging Face, Coqui and torch.hub downloads.
"""
from __future__ import annotations
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

GB, MB = 2**30, 2**20
WHISPER_SIZES = {"tiny": 75 * MB, "base": 145 * MB, "small": 484 * MB,
                 "medium": 1.53 * GB, "large-v3": 3.09 * GB}
PYANNOTE_REPOS = ("pyannote/speaker-diarization-3.1", "pyannote/segmentation-3.0",
                  "pyannote/wespeaker-voxceleb-resnet34-LM")
XTTS = "tts_models/multilingual/multi-dataset/xtts_v2"
NLLB_FILES = ["*.json", "*.model", "pytorch_model.bin"]


def _hub_cache() -> str:
    # Passed explicitly: huggingface_hub fixes its default cache path at import time.
    return os.environ["HUGGINGFACE_HUB_CACHE"]


def _hub_dir(repo: str) -> Path:
    return Path(_hub_cache()) / ("models--" + repo.replace("/", "--"))


def _dir_bytes(paths: list[Path]) -> int:
    total = 0
    for p in paths:
        if p.is_dir():
            for f in p.rglob("*"):
                try:
                    if f.is_file() and not f.is_symlink():
                        total += f.stat().st_size
                except OSError:
                    pass
    return total


def _hub_present(repo: str, **kw) -> bool:
    from huggingface_hub import snapshot_download
    try:
        snapshot_download(repo, cache_dir=_hub_cache(), local_files_only=True, **kw)
        return True
    except Exception:
        return False


@dataclass
class Model:
    id: str
    name: str
    purpose: str
    size: int                                  # expected download, bytes
    dirs: Callable[[], list[Path]]             # cache folders (for progress)
    present: Callable[[], bool]
    download: Callable[[], None]
    needs: str | None = None                   # "token" | "license" | None
    optional: bool = False
    state: str = "unknown"                     # missing|present|queued|downloading|done|error|blocked
    done_bytes: int = 0
    error: str | None = None
    _base: int = field(default=0, repr=False)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("id", "name", "purpose", "size", "needs", "optional", "state", "done_bytes", "error")}


class ModelManager:
    def __init__(self, cfg: dict, on_update: Callable[[dict], None] | None = None):
        self.cfg = cfg
        self.cache = Path(cfg["_cache_dir"])
        self.on_update = on_update or (lambda _msg: None)
        self._thread: threading.Thread | None = None
        self._active = False                   # cleared before the final update is sent
        self._lock = threading.Lock()
        self.models = self._registry()

    # ── registry ──────────────────────────────────────────────

    def _registry(self) -> list[Model]:
        cache = self.cache
        wsize = self.cfg["stt"]["model"]
        whisper_dir = cache / "whisper"

        def whisper_present():
            if wsize not in WHISPER_SIZES:          # custom path / repo: can't check, assume ok
                return True
            from faster_whisper import download_model
            try:
                download_model(wsize, cache_dir=str(whisper_dir), local_files_only=True)
                return True
            except Exception:
                return False

        def whisper_download():
            from faster_whisper import download_model
            download_model(wsize, cache_dir=str(whisper_dir))

        torch_hub = Path(os.environ.get("TORCH_HOME", cache / "torch")) / "hub"

        def vad_download():
            import torch
            torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)

        def pyannote_download():
            from huggingface_hub import snapshot_download
            for repo in PYANNOTE_REPOS:
                snapshot_download(repo, cache_dir=_hub_cache(), token=os.environ.get("HF_TOKEN"))

        xtts_dir = Path(os.environ.get("TTS_HOME", cache / "tts")) / "tts" / XTTS.replace("/", "--")

        def xtts_present():
            f = xtts_dir / "model.pth"
            return f.is_file() and f.stat().st_size > 1 * GB and (xtts_dir / "config.json").is_file()

        def xtts_download():
            os.environ["COQUI_TOS_AGREED"] = "1"     # only reached after the user accepted
            from TTS.utils.manage import ModelManager as CoquiManager
            CoquiManager(progress_bar=False).download_model(XTTS)

        nllb = self.cfg["mt"]["nllb_model"]

        def nllb_download():
            from huggingface_hub import snapshot_download
            snapshot_download(nllb, cache_dir=_hub_cache(), allow_patterns=NLLB_FILES)

        return [
            Model("vad", "Voice detection", "Notices when someone is speaking", 20 * MB,
                  lambda: [torch_hub], lambda: (torch_hub / "snakers4_silero-vad_master").is_dir(),
                  vad_download),
            Model("stt", f"Speech recognition (Whisper {wsize})", "Turns speech into text",
                  int(WHISPER_SIZES.get(wsize, 0)),
                  lambda: [whisper_dir], whisper_present, whisper_download),
            Model("speakers", "Speaker separation", "Tells different voices apart", 32 * MB,
                  lambda: [_hub_dir(r) for r in PYANNOTE_REPOS],
                  lambda: all(_hub_present(r) for r in PYANNOTE_REPOS), pyannote_download,
                  needs="token"),
            Model("voice", "Voice (XTTS-v2)", "Speaks the translation in each speaker's voice",
                  int(1.87 * GB), lambda: [xtts_dir], xtts_present, xtts_download, needs="license"),
            Model("translator", "Translator (NLLB)", "Needed only for output languages other than English",
                  int(2.46 * GB), lambda: [_hub_dir(nllb)],
                  lambda: _hub_present(nllb, allow_patterns=NLLB_FILES), nllb_download, optional=True),
        ]

    # ── status ────────────────────────────────────────────────

    def refresh(self, token_ok: bool, license_ok: bool) -> list[dict]:
        for m in self.models:
            if m.state in ("queued", "downloading"):
                continue
            if m.present():
                m.state = "present"
            elif (m.needs == "token" and not token_ok) or (m.needs == "license" and not license_ok):
                m.state = "blocked"
            else:
                m.state = "missing"
        return [m.to_dict() for m in self.models]

    def get(self, id_: str) -> Model:
        return next(m for m in self.models if m.id == id_)

    def missing_bytes(self, include_optional: bool) -> int:
        return sum(m.size for m in self.models
                   if m.state in ("missing", "blocked") and (include_optional or not m.optional))

    def required_ready(self) -> bool:
        """Everything needed to start (blocked = user chose to skip that feature)."""
        return all(m.state in ("present", "done", "blocked") for m in self.models if not m.optional)

    @property
    def busy(self) -> bool:
        return self._active

    # ── downloading ───────────────────────────────────────────

    def download(self, ids: list[str]) -> bool:
        """Download the given models one after another in the background."""
        with self._lock:
            if self.busy:
                return False
            todo = [m for m in self.models if m.id in ids and m.state in ("missing", "error")]
            for m in todo:
                m.state, m.error, m.done_bytes = "queued", None, 0
            self._active = True
            self._thread = threading.Thread(target=self._run, args=(todo,), daemon=True,
                                            name="model-download")
            self._thread.start()
            return True

    def _emit(self, finished: bool = False):
        self.on_update({"type": "models", "models": [m.to_dict() for m in self.models],
                        "busy": not finished})

    def _run(self, todo: list[Model]):
        for m in todo:
            m.state, m._base = "downloading", _dir_bytes(m.dirs())
            stop = threading.Event()

            def watch(model=m):
                while not stop.wait(0.5):
                    grown = _dir_bytes(model.dirs()) - model._base
                    model.done_bytes = max(0, min(grown, int(model.size * 0.99)))
                    self._emit()

            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            try:
                m.download()
                m.state, m.done_bytes = ("done" if m.present() else "error"), m.size
                if m.state == "error":
                    m.error = "Download finished but the files are incomplete. Try again."
            except Exception as exc:
                m.state, m.error = "error", _friendly(exc)
            finally:
                stop.set()
                watcher.join(timeout=1)
            self._emit()
        self._active = False
        self._emit(finished=True)


def _friendly(exc: Exception) -> str:
    text = str(exc)
    if "401" in text or "403" in text or "gated" in text.lower():
        return "Access denied - check the token and that you accepted the model pages."
    if "No space" in text or "disk" in text.lower():
        return "Not enough disk space."
    if any(s in text for s in ("ConnectionError", "Max retries", "timed out", "getaddrinfo")):
        return "No connection to the download server. Check your internet and try again."
    return f"{type(exc).__name__}: {text[:160]}"

"""Server side of the Files tab: pick a file, choose its audio track, detect the
spoken language, translate into one or many languages, and report progress.
The UI talks to it with file_* messages."""
from __future__ import annotations
import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

from .. import config as config_mod
from ..files import languages, media
from ..files.dubber import Cancelled, Dubber, DubJob
from . import dialogs

PREF_KEYS = ("targets", "output", "audio_format", "keep_background", "subtitles", "voice_mode")
DEFAULT_PREFS = {"targets": ["es"], "output": "add", "audio_format": "mp3",
                 "keep_background": False, "subtitles": True, "voice_mode": "match"}


class FilesTab:
    def __init__(self, cfg: dict, engine, onboarding, emit: Callable[[dict], None],
                 log: Callable[[str], None], persist: bool, is_live: Callable[[], bool]):
        self.cfg, self.engine, self.onboarding = cfg, engine, onboarding
        self.emit, self.log, self.persist, self.is_live = emit, log, persist, is_live
        self.info: dict | None = None             # the chosen file (media.probe)
        self.detected: dict = {}                  # track -> detection result
        self.track = 0                            # the track picked (kept for reconnects)
        self.out_dir: str | None = None
        self.uploads = Path(cfg["_cache_dir"]) / "uploads"
        self._job: Dubber | None = None
        self._thread: threading.Thread | None = None
        self._last: dict | None = None            # last progress / result, for reconnects
        self._outputs: list[str] = []

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def prefs(self) -> dict:
        saved = self.cfg.get("files", {})
        return {k: saved.get(k, v) for k, v in DEFAULT_PREFS.items()}

    def state(self) -> dict:
        return {"type": "file_state", "info": self.info, "detected": self.detected, "track": self.track,
                "out_dir": self.out_dir, "prefs": self.prefs(), "running": self.running,
                "last": self._last,
                "languages": [{"code": c, "name": n} for c, (n, _) in languages.VOICE_LANGS.items()],
                "translator_ready": self._translator_ready(refresh=False)}

    def _translator_ready(self, refresh: bool = True) -> bool:
        # On connect the setup screen's state was just built (which checked every
        # model on disk), so the Files tab reuses that instead of checking again.
        if refresh:
            self.onboarding.models.refresh(self.onboarding.token_ok, self.onboarding.license_ok)
        return self.onboarding.models.get("translator").state in ("present", "done")

    # ── messages ──────────────────────────────────────────────

    def handle(self, msg: dict) -> bool:
        t = msg.get("type", "")
        try:
            if t == "file_state":
                self.emit(self.state())
            elif t == "file_pick":
                path = dialogs.pick_file()
                if path:
                    self.open(path)
            elif t == "file_open":
                self.open(str(msg.get("path", "")))
            elif t == "file_detect":
                self.track = int(msg.get("track", 0))
                self.detect(self.track)
            elif t == "file_pick_dir":
                path = dialogs.pick_folder()
                if path:
                    self.out_dir = path
                    self.emit({"type": "file_out_dir", "out_dir": path})
            elif t == "file_start":
                self.start(msg)
            elif t == "file_cancel":
                if self._job:
                    self._job.cancel()
                    self.log("Cancelling…")
            elif t == "file_reveal":
                self.reveal(str(msg.get("path", "")))
            else:
                return False
        except Exception as exc:
            self.emit({"type": "file_error", "msg": str(exc)})
        return True

    # ── choosing a file ───────────────────────────────────────

    def open(self, path: str):
        p = Path(path)
        if not p.is_file():
            raise RuntimeError("That file doesn't exist.")
        if self.running:
            raise RuntimeError("A file is being translated. Cancel it first.")
        try:
            info = media.probe(p)
        except Exception:
            raise RuntimeError(f"Can't read {p.name} - is it an audio or video file?")
        if not info["tracks"]:
            raise RuntimeError(f"{p.name} has no audio.")
        for tr in info["tracks"]:
            tr["lang_code"] = languages.from_tag(tr["language"])
            tr["lang_name"] = languages.name(tr["lang_code"]) if tr["lang_code"] else None
        self.info, self.detected, self._last = info, {}, None
        self.track = info["default_track"]
        uploaded = self.uploads in p.parents
        self.out_dir = str((self.cfg["_root"] / "output") if uploaded else p.parent / "Ominvox")
        self.emit(self.state())
        # Videos often have a music / commentary track first: if the default
        # track has no speech, try the others and switch to the first that does.
        if not self.detect(info["default_track"])["speech"]:
            for tr in info["tracks"]:
                if tr["index"] != info["default_track"] and self.detect(tr["index"])["speech"]:
                    self.track = tr["index"]
                    self.emit({"type": "file_track", "track": tr["index"],
                               "reason": "The default track has no speech, so this one was picked."})
                    break

    def detect(self, track: int) -> dict:
        if not self.info:
            return {"speech": False}
        if self.onboarding.models.get("stt").state not in ("present", "done"):
            self.emit(self.onboarding.state())
            self.emit({"type": "need_setup"})
            raise RuntimeError("Download the models in Setup first.")
        if self.is_live():
            raise RuntimeError("Stop listening first - live translation is using the models.")
        if self.running:
            raise RuntimeError("A file is being translated. Cancel it first.")
        self.emit({"type": "file_lang", "track": track, "busy": True})
        res = Dubber(self.engine, self.cfg).detect(self.info["path"], track)
        res["name"] = languages.name(res["lang"]) if res["lang"] else None
        for c in res["candidates"]:
            c["name"] = languages.name(c["lang"])
        self.detected[track] = res
        self.emit({"type": "file_lang", "track": track, **res})
        return res

    # ── translating ───────────────────────────────────────────

    def start(self, msg: dict):
        if self.running:
            raise RuntimeError("Already translating a file.")
        if not self.info:
            raise RuntimeError("Choose a file first.")
        if self.is_live():
            raise RuntimeError("Stop listening first - live translation is using the models.")
        if not self.onboarding.license_ok:
            self.emit({"type": "need_setup"})
            raise RuntimeError("Agree to the voice licence in Setup to make translated audio.")
        if not self.onboarding.ready():
            self.emit({"type": "need_setup"})
            raise RuntimeError("Finish downloading the models in Setup first.")
        targets = [t for t in msg.get("targets", []) if t in languages.VOICE_LANGS]
        source = msg.get("source_lang") or None
        targets = [t for t in targets if t != source]
        if not targets:
            raise RuntimeError("Pick at least one language to translate into.")
        if any(t != "en" for t in targets) and not self._translator_ready():
            self.emit(self.onboarding.state())
            self.emit({"type": "need_setup"})
            raise RuntimeError("Languages other than English need the translator - "
                               "tick it in Setup → Download models.")
        self.track = int(msg.get("track", 0))
        job = DubJob(path=self.info["path"], targets=targets,
                     output=msg.get("output", "add") if msg.get("output") in ("separate", "add", "replace") else "add",
                     audio_format=msg.get("audio_format") if msg.get("audio_format") in ("mp3", "m4a", "wav") else "mp3",
                     track=int(msg.get("track", 0)), source_lang=source,
                     keep_background=bool(msg.get("keep_background")),
                     subtitles=bool(msg.get("subtitles", True)),
                     voice_mode="single" if msg.get("voice_mode") == "single" else "match",
                     out_dir=self.out_dir)
        prefs = {k: msg[k] for k in PREF_KEYS if k in msg}
        self.cfg.setdefault("files", {}).update(prefs)
        if self.persist:
            try:
                config_mod.save_user_settings({"files": prefs})
            except Exception as exc:
                self.log(f"Could not save settings: {exc}")
        self._job = Dubber(self.engine, self.cfg, on_progress=self._progress, log=self.log,
                           nllb_ok=self._translator_ready())
        self._thread = threading.Thread(target=self._run, args=(self._job, job), daemon=True,
                                        name="file-dub")
        self._thread.start()
        self.emit({"type": "file_started", "targets": targets})

    def _progress(self, p: dict):
        self._last = {"type": "file_progress", **p}
        self.emit(self._last)

    def _run(self, dubber: Dubber, job: DubJob):
        self.log(f"Translating {Path(job.path).name} into "
                 f"{', '.join(languages.name(t) for t in job.targets)}…")
        try:
            outputs = dubber.run(job)
            self._outputs = [o["path"] for o in outputs]
            self._last = {"type": "file_done", "outputs": outputs, "out_dir": job.out_dir,
                          "langs": {k: v for k, v in (self._last or {}).get("langs", {}).items()}}
            self.log(f"Done - {len(outputs)} file(s) saved in {job.out_dir}")
        except Cancelled:
            self._last = {"type": "file_cancelled"}
            self.log("File translation cancelled.")
        except Exception as exc:
            self._last = {"type": "file_error", "msg": str(exc)}
            self.log(f"File translation failed: {exc}")
        finally:
            self._job = None
            self.emit(self._last)

    def reveal(self, path: str):
        """Show a result in Explorer (only paths this tab produced or its folder)."""
        allowed = set(self._outputs) | ({self.out_dir} if self.out_dir else set())
        if path not in allowed or not Path(path).exists():
            return
        if Path(path).is_dir():
            os.startfile(path)                                       # noqa: S606
        else:
            subprocess.Popen(["explorer", "/select,", str(Path(path))])

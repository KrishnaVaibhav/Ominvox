"""Server side of the first-run screen: system checks, the voice licence, the
Hugging Face token and model downloads. The UI talks to it with fr_* messages."""
from __future__ import annotations
import threading
import webbrowser
from typing import Callable

from .. import config as config_mod
from ..firstrun import checks, hf_token
from ..firstrun.models import ModelManager

# Only these sites can be opened from the UI's "Open page" buttons.
SAFE_URLS = ("https://huggingface.co/", "https://www.nvidia.com/", "https://coqui.ai/",
             "https://vb-audio.com/")
LICENSE_URL = "https://coqui.ai/cpml"


class Onboarding:
    def __init__(self, cfg: dict, emit: Callable[[dict], None], log: Callable[[str], None],
                 persist: bool, on_token: Callable[[], None], on_license: Callable[[], None]):
        self.cfg = cfg
        self.emit, self.log, self.persist = emit, log, persist
        self.on_token, self.on_license = on_token, on_license
        self.models = ModelManager(cfg, on_update=self._on_models)
        self.token = {"valid": False, "checked": False}
        self._checks: list[dict] | None = None
        if hf_token.current_token():
            threading.Thread(target=self._verify, args=(hf_token.current_token(), False),
                             daemon=True).start()

    # ── state ─────────────────────────────────────────────────

    @property
    def license_ok(self) -> bool:
        return bool(self.cfg["tts"].get("license_accepted"))

    @property
    def token_ok(self) -> bool:
        return bool(self.token.get("valid")) and all(m["ok"] for m in self.token.get("models", []))

    def _needs_translator(self) -> bool:
        return self.cfg["translate"]["target_lang"] != "en" and self.cfg["mt"].get("backend") != "whisper"

    def state(self, recheck: bool = False) -> dict:
        models = self.models.refresh(self.token_ok, self.license_ok)
        if recheck or self._checks is None:
            self._checks = checks.run_all(self.cfg["_root"],
                                          self.models.missing_bytes(self._needs_translator()))
        done = bool(self.cfg.get("firstrun", {}).get("done"))
        return {
            "type": "onboarding",
            "done": done,
            "show": not done or not self.ready(),
            "license": {"accepted": self.license_ok, "url": LICENSE_URL},
            "token": {**self.token, "ok": self.token_ok, "page": hf_token.TOKEN_PAGE},
            "models": models,
            "busy": self.models.busy,
            "needs_translator": self._needs_translator(),
            "checks": self._checks,
            "ready": self.ready(),
        }

    def ready(self) -> bool:
        """Can Start Listening run without a silent multi-GB download?"""
        self.models.refresh(self.token_ok, self.license_ok)
        if not self.models.required_ready():
            return False
        if self._needs_translator() and self.models.get("translator").state not in ("present", "done"):
            return False
        return True

    def _on_models(self, msg: dict):
        self.emit(msg)
        if not msg.get("busy"):
            self.emit(self.state())

    # ── actions ───────────────────────────────────────────────

    def handle(self, msg: dict) -> bool:
        """Handle an fr_* / open_url message. Returns True if it was one."""
        t = msg.get("type", "")
        if t == "fr_state":
            self.emit(self.state(recheck=bool(msg.get("recheck"))))
        elif t == "fr_license":
            self._set_license(bool(msg.get("accept")))
        elif t == "fr_token":
            threading.Thread(target=self._verify, args=(msg.get("token", ""), True),
                             daemon=True).start()
        elif t == "fr_download":
            ids = [i for i in msg.get("ids", []) if isinstance(i, str)]
            if not self.models.download(ids):
                self.log("A download is already running.")
            self.emit(self.state())
        elif t == "fr_done":
            self.cfg.setdefault("firstrun", {})["done"] = True
            self._save({"firstrun": {"done": True}})
            self.emit(self.state())
        elif t == "open_url":
            url = str(msg.get("url", ""))
            if url.startswith(SAFE_URLS):
                webbrowser.open(url)
        else:
            return False
        return True

    def _set_license(self, accept: bool):
        self.cfg["tts"]["license_accepted"] = accept
        self._save({"tts": {"license_accepted": accept}})
        if accept:
            import os
            os.environ["COQUI_TOS_AGREED"] = "1"
        self.on_license()
        self.emit(self.state())

    def _verify(self, token: str, save: bool):
        self.emit({"type": "fr_token_checking"})
        result = hf_token.verify(token)
        self.token = {**result, "checked": True}
        if save and result["valid"]:
            hf_token.save(self.cfg["_root"], token)
            self.log(f"Hugging Face token saved (account: {result['user']}).")
        if result["valid"]:
            self.on_token()
        self.emit(self.state())

    def _save(self, changes: dict):
        if self.persist:
            try:
                config_mod.save_user_settings(changes)
            except Exception as exc:
                self.log(f"Could not save settings: {exc}")

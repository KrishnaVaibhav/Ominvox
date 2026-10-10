"""First-run screen backend: token handling, model registry, licence gating,
Start gating and URL filtering. No GPU, no sound, no network.

Run:  .venv312\\Scripts\\python.exe tests\\test_firstrun.py
"""
from __future__ import annotations
import _common  # noqa: F401  (path + cache setup)
from _common import Results
import copy
import os
import tempfile
from pathlib import Path

from ominvox import config
from ominvox.firstrun import hf_token
from ominvox.firstrun.models import ModelManager
from ominvox.ui.onboarding import Onboarding

R = Results()

R.section("Hugging Face token")
R.check("rejects text that isn't a token", hf_token.verify("hello")["error"] is not None)
root = Path(tempfile.mkdtemp())
(root / ".env").write_text("OTHER=1\nHF_TOKEN=hf_old\n", encoding="utf-8")
old_env = os.environ.get("HF_TOKEN")
hf_token.save(root, "hf_new123")
text = (root / ".env").read_text(encoding="utf-8")
R.check("save() replaces HF_TOKEN and keeps other lines",
        "HF_TOKEN=hf_new123" in text and "OTHER=1" in text and "hf_old" not in text, text.strip().replace("\n", " | "))
R.check("save() applies the token immediately", os.environ.get("HF_TOKEN") == "hf_new123")
if old_env is None:
    os.environ.pop("HF_TOKEN", None)
else:
    os.environ["HF_TOKEN"] = old_env
os.environ["HF_TOKEN"] = "hf_paste_your_token_here"
R.check("placeholder token from .env.example counts as missing", hf_token.current_token() is None)
if old_env is None:
    os.environ.pop("HF_TOKEN", None)
else:
    os.environ["HF_TOKEN"] = old_env

R.section("Model registry on an empty cache")
empty = Path(tempfile.mkdtemp())
saved_env = {k: os.environ.get(k) for k in ("HUGGINGFACE_HUB_CACHE", "TORCH_HOME", "TTS_HOME")}
os.environ.update(HUGGINGFACE_HUB_CACHE=str(empty / "hub"), TORCH_HOME=str(empty / "torch"),
                  TTS_HOME=str(empty / "tts"))
cfg = copy.deepcopy(config.load())
cfg["_cache_dir"] = empty
cfg["stt"]["model"] = "tiny"
mm = ModelManager(cfg)
states = {m["id"]: m["state"] for m in mm.refresh(token_ok=False, license_ok=False)}
R.check("nothing is present", all(s in ("missing", "blocked") for s in states.values()), str(states))
R.check("speaker models wait for the token", states["speakers"] == "blocked")
R.check("voice model waits for the licence", states["voice"] == "blocked")
R.check("required models not ready", not mm.required_ready())
states = {m["id"]: m["state"] for m in mm.refresh(token_ok=True, license_ok=True)}
R.check("token + licence unblock them", states["speakers"] == "missing" and states["voice"] == "missing")
R.check("download size excludes the optional translator",
        mm.missing_bytes(False) < mm.missing_bytes(True), f"{mm.missing_bytes(False) / 2**30:.1f} GB")

R.section("Onboarding state, licence and Start gating")
events: list[dict] = []
cfg["_root"] = Path(tempfile.mkdtemp())
cfg["tts"]["license_accepted"] = False
ob = Onboarding(cfg, emit=events.append, log=lambda m: None, persist=False,
                on_token=lambda: None, on_license=lambda: events.append({"type": "_license_cb"}))
st = ob.state()
R.check("state has every section",
        all(k in st for k in ("license", "token", "models", "checks", "ready", "show")))
R.check("setup screen shows when nothing is downloaded", st["show"] and not st["ready"])
R.check("Start is blocked (ready() is False)", not ob.ready())
ob.handle({"type": "fr_license", "accept": True})
R.check("agreeing to the licence is applied and announced",
        cfg["tts"]["license_accepted"] and os.environ.get("COQUI_TOS_AGREED") == "1"
        and any(e.get("type") == "_license_cb" for e in events))
opened = []
import webbrowser
webbrowser.open = lambda url: opened.append(url)
ob.handle({"type": "open_url", "url": "https://huggingface.co/settings/tokens"})
ob.handle({"type": "open_url", "url": "https://evil.example.com/"})
ob.handle({"type": "open_url", "url": "file:///C:/Windows"})
R.check("only whitelisted sites can be opened", opened == ["https://huggingface.co/settings/tokens"], str(opened))
R.check("unknown messages are ignored", ob.handle({"type": "start"}) is False)

for k, v in saved_env.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v
R.finish()

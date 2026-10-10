"""Shared helpers for the test scripts.

Importing this module makes `import ominvox` work when a test is run directly
(python tests/test_x.py), sets the cache folders like run.bat does, and gives
a tiny pass/fail reporter.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_cache = ROOT / ".cache"
for key, sub in (("HF_HOME", "huggingface"), ("HUGGINGFACE_HUB_CACHE", "huggingface/hub"),
                 ("TORCH_HOME", "torch"), ("TTS_HOME", "tts"), ("XDG_CACHE_HOME", "")):
    os.environ.setdefault(key, str(_cache / sub))
os.environ.setdefault("COQUI_TOS_AGREED", "1")     # tests use the voice model
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
# The env var only affects child processes; make this process's own output safe
# too, or printing e.g. "->" arrows fails on a cp1252 console inside a check.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class Results:
    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[str] = []

    def ok(self, name: str, detail: str = ""):
        print(f"  PASS  {name}" + (f"  [{detail}]" if detail else ""), flush=True)
        self.passed.append(name)

    def fail(self, name: str, reason: str = ""):
        print(f"  FAIL  {name}" + (f"  -- {reason}" if reason else ""), flush=True)
        self.failed.append(name)

    def check(self, name: str, cond: bool, detail: str = ""):
        (self.ok if cond else self.fail)(name, detail)

    @staticmethod
    def section(title: str):
        print(f"\n=== {title} ===", flush=True)

    def finish(self) -> None:
        print(f"\n{'=' * 60}\nResults: {len(self.passed)} passed, {len(self.failed)} failed")
        for f in self.failed:
            print(f"  - {f}")
        sys.exit(0 if not self.failed else 1)


def device_by_name(kind: str, env: str):
    """Index of the device whose name contains $env (None = system default).
    Lets the sound tests use e.g. a monitor's speakers instead of headphones."""
    want = os.environ.get(env, "").lower()
    if not want:
        return None
    from ominvox.audio.devices import enumerate_devices
    devs = enumerate_devices()
    pool = [d for d in devs["inputs"] if d["kind"] == "system"] if kind == "input" else devs["outputs"]
    return next((d["index"] for d in pool if want in d["name"].lower()), None)

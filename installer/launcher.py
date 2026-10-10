"""Ominvox.exe - the double-click launcher.

Built with PyInstaller by scripts\\build_exe.bat. Standard library only, so the
exe stays small: the AI models and their Python environment live in the
install folder (.venv312, .cache) and are NOT bundled. The exe must sit there.

What it does:
  1. If Ominvox isn't installed yet (.venv312 missing): offer to run the
     one-time setup (setup.ps1) in a console window, then continue.
  2. Start the app in its own window (python -m ominvox.app --window) with
     every cache pinned inside the folder, logging to logs\\ominvox.log.
     The app's own first-run screen handles the licence, token and models.
  3. If the app dies during startup, show the end of that log.
"""
from __future__ import annotations
import ctypes
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

TITLE = "Ominvox"
MB_OK, MB_YESNO, MB_ICONINFO, MB_ICONWARN, MB_ICONERR, IDYES = 0x0, 0x4, 0x40, 0x30, 0x10, 6
PORT = 8765


def msgbox(text: str, flags: int = MB_OK | MB_ICONINFO) -> int:
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags)


def project_root() -> Path:
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    for cand in (here, here.parent):                    # exe in the install folder, or this script in installer/
        if (cand / "ominvox" / "app.py").is_file():
            return cand
    return here


def env_for(root: Path) -> dict:
    cache = root / ".cache"
    env = dict(os.environ)
    env.update({
        "HF_HOME": str(cache / "huggingface"),
        "HUGGINGFACE_HUB_CACHE": str(cache / "huggingface" / "hub"),
        "TORCH_HOME": str(cache / "torch"),
        "TTS_HOME": str(cache / "tts"),
        "XDG_CACHE_HOME": str(cache),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def already_running() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1) as r:
            return b'"ominvox"' in r.read()
    except Exception:
        return False


def run_setup(root: Path) -> bool:
    if msgbox("Ominvox isn't installed on this PC yet.\n\n"
              "The one-time setup downloads Python, the AI libraries and GPU support "
              "into this folder (about 15 GB, 10-30 minutes).\n\nStart the setup now?",
              MB_YESNO | MB_ICONINFO) != IDYES:
        return False
    script = root / "setup.ps1"
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
           f"& '{script}'; if ($LASTEXITCODE -ne 0 -or -not $?) "
           "{ Write-Host ''; Write-Host 'Setup FAILED - see the messages above.' -ForegroundColor Red }"
           " else { Write-Host ''; Write-Host 'Setup finished. Ominvox will now start.' -ForegroundColor Green };"
           " Write-Host 'Press Enter to close this window.'; [void](Read-Host)"]
    subprocess.call(cmd, cwd=root, creationflags=subprocess.CREATE_NEW_CONSOLE)
    return (root / ".venv312" / "Scripts" / "python.exe").is_file()


def main() -> int:
    root = project_root()
    if not (root / "ominvox" / "app.py").is_file():
        msgbox("Ominvox.exe must be inside the Ominvox project folder "
               "(next to config.yaml and the 'ominvox' folder).", MB_OK | MB_ICONERR)
        return 1

    if already_running():
        webbrowser.open(f"http://127.0.0.1:{PORT}")     # never load the models twice
        return 0

    py = root / ".venv312" / "Scripts" / "pythonw.exe"
    if not py.is_file():
        if not run_setup(root):
            return 1

    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / "ominvox.log"
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([str(py), "-m", "ominvox.app", "--window"], cwd=root,
                            env=env_for(root), stdout=log, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW)

    # Watch the first seconds: if the app exits right away, show why.
    deadline = time.time() + 60
    while time.time() < deadline:
        code = proc.poll()
        if code is not None:
            log.close()
            if code != 0:
                tail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-15:]
                msgbox("Ominvox stopped while starting.\n\n" + "\n".join(tail) +
                       f"\n\nFull log: {log_path}", MB_OK | MB_ICONERR)
            return code
        if already_running():
            return 0
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Native "Open file" / "Choose folder" dialogs for the Files tab.

In the app window (pywebview) the window's own dialog is used. In browser mode
(--ui) a small tkinter dialog runs in a child process (tkinter must own the
main thread of its process, and the server's threads aren't that).
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

from ..files.media import AUDIO_EXTS, VIDEO_EXTS

_MEDIA = ";".join(f"*{e}" for e in sorted(VIDEO_EXTS | AUDIO_EXTS))
_TK = r"""
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
if sys.argv[1] == "file":
    p = filedialog.askopenfilename(title="Choose an audio or video file",
        filetypes=[("Audio and video", sys.argv[2]), ("All files", "*.*")])
else:
    p = filedialog.askdirectory(title="Choose where to save the results")
sys.stdout.write(p or "")
"""

window = None          # set by ui.window when running in the app window


def _python() -> str:
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")        # pythonw has no stdout to read
    return str(console if exe.name.lower() == "pythonw.exe" and console.exists() else exe)


def _tk(kind: str) -> str | None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([_python(), "-c", _TK, kind, _MEDIA], capture_output=True, text=True,
                       encoding="utf-8", creationflags=flags)
    return r.stdout.strip() or None


def pick_file() -> str | None:
    if window is not None:
        import webview
        res = window.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=(f"Audio and video ({_MEDIA})", "All files (*.*)"))
        return res[0] if res else None
    return _tk("file")


def pick_folder() -> str | None:
    if window is not None:
        import webview
        res = window.create_file_dialog(webview.FileDialog.FOLDER)
        return res[0] if res else None
    return _tk("folder")

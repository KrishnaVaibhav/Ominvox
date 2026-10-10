"""OminvoxSetup.exe - the one file a user downloads.

Built by scripts\\build_exe.bat. Standard library only (tkinter UI). The app's
files (and Ominvox.exe) are embedded as payload.zip, so installing needs no
GitHub access - only the Python libraries are downloaded, by setup.ps1.

Flow:  choose folder -> checks -> copy files -> run setup.ps1 (progress parsed
from its "=== [n/6] ... ===" lines) -> shortcuts -> launch Ominvox, which
then shows its own first-run screen (licence, token, model downloads).
Re-running it on an existing install updates the app files and keeps settings,
models, speakers and the Python environment.
"""
from __future__ import annotations
import ctypes
import os
import queue
import re
import shutil
import string
import subprocess
import sys
import threading
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, ttk

APP = "Ominvox"
NEED_GB = 20
BG, SURFACE, TEXT, MUTED, ACCENT, GOOD, BAD = ("#0d0f1a", "#141621", "#e8eaf0", "#9aa1b8",
                                               "#7c5cfc", "#0ca30c", "#ec835a")
STEP_RE = re.compile(r"=== \[(\d+)/(\d+)\] (.+?) ===")


def resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def default_folder() -> Path:
    """The fixed drive with the most free space (keeps big models off a full C:)."""
    best, best_free = Path.home() / APP, 0
    drives = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not drives & (1 << i):
            continue
        root = f"{letter}:\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) != 3:     # 3 = fixed disk
            continue
        try:
            free = shutil.disk_usage(root).free
        except OSError:
            continue
        if free > best_free:
            best, best_free = Path(root) / APP, free
    return best


def nvidia_gpu() -> str | None:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True, text=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW).stdout
        return next((l.strip() for l in out.splitlines() if "nvidia" in l.lower()), None)
    except Exception:
        return None


def make_shortcut(lnk: Path, target: Path, workdir: Path):
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          f"$s.TargetPath='{target}';$s.WorkingDirectory='{workdir}';"
          f"$s.IconLocation='{target},0';$s.Description='Ominvox - live movie translation';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)


def install_to(target: Path, report) -> bool:
    """Copy the app, run setup.ps1, add shortcuts. report(kind, ...) receives
    ("status", text, percent) / ("log", line) / ("done",) / ("failed", message)."""
    try:
        report("status", "Copying files…", 2)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(resource("payload.zip")) as z:
            z.extractall(target)
        report("log", f"Files copied to {target}")
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
               "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
               f"& '{target / 'setup.ps1'}' -NoShortcut; exit $LASTEXITCODE"]
        log_path = target / "logs" / "setup.log"
        log_path.parent.mkdir(exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as lf:
            p = subprocess.Popen(cmd, cwd=target, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            for raw in p.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                lf.write(line + "\n")
                lf.flush()
                m = STEP_RE.search(line)
                if m:
                    n, total, title = int(m.group(1)), int(m.group(2)), m.group(3)
                    report("status", f"Step {n} of {total}: {title}", 5 + 90 * (n - 1) / total)
                elif line.strip():
                    report("log", line)
            code = p.wait()
        if code != 0 or not (target / ".venv312" / "Scripts" / "python.exe").exists():
            report("failed", f"Setup stopped (code {code}). Details: {log_path}")
            return False
        report("status", "Creating shortcuts…", 97)
        exe = target / "Ominvox.exe"
        desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
        start = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        for folder in (desktop, start):
            try:
                make_shortcut(folder / f"{APP}.lnk", exe, target)
            except Exception as exc:
                report("log", f"(shortcut in {folder} failed: {exc})")
        report("done")
        return True
    except Exception as exc:
        report("failed", f"{type(exc).__name__}: {exc}")
        return False


def silent(argv: list[str]) -> int:
    """OminvoxSetup.exe --silent [--dir PATH] [--no-shortcuts]: no window; progress
    goes to <dir>/logs/install.log. For scripted installs and testing."""
    target = Path(argv[argv.index("--dir") + 1]) if "--dir" in argv else default_folder()
    target.mkdir(parents=True, exist_ok=True)
    (target / "logs").mkdir(exist_ok=True)
    if "--no-shortcuts" in argv:
        globals()["make_shortcut"] = lambda *a, **k: None
    with open(target / "logs" / "install.log", "w", encoding="utf-8") as log:
        def report(kind, *args):
            log.write(f"{kind}: {' '.join(str(a) for a in args)}\n")
            log.flush()
        return 0 if install_to(target, report) else 1


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP} Setup")
        self.geometry("640x460")
        self.resizable(False, False)
        self.configure(bg=BG)
        try:
            self.iconbitmap(resource("ominvox.ico"))
        except Exception:
            pass
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor=SURFACE, background=ACCENT, bordercolor=SURFACE,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        self.q: queue.Queue = queue.Queue()
        self.folder = tk.StringVar(value=str(default_folder()))
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=28, pady=22)
        self.show_welcome()
        self.after(100, self.pump)

    # ── helpers ───────────────────────────────────────────────
    def clear(self):
        for w in self.page.winfo_children():
            w.destroy()

    def label(self, text, size=10, color=TEXT, bold=False, **pack):
        lbl = tk.Label(self.page, text=text, bg=BG, fg=color, justify="left", anchor="w",
                       wraplength=580, font=("Segoe UI", size, "bold" if bold else "normal"))
        lbl.pack(fill="x", **({"pady": (0, 6)} | pack))
        return lbl

    def button(self, parent, text, cmd, primary=False):
        return tk.Button(parent, text=text, command=cmd, relief="flat", cursor="hand2",
                         bg=ACCENT if primary else SURFACE, fg="#fff" if primary else TEXT,
                         activebackground=ACCENT, activeforeground="#fff",
                         font=("Segoe UI", 10, "bold" if primary else "normal"), padx=16, pady=6)

    # ── page 1: welcome + folder + checks ─────────────────────
    def show_welcome(self):
        self.clear()
        self.label(f"Install {APP}", 18, bold=True)
        self.label("Live, private movie translation that keeps each speaker's voice. "
                   "Everything runs on your own PC.", 10, MUTED, pady=(0, 16))
        self.label("Install folder", 10, bold=True)
        row = tk.Frame(self.page, bg=BG)
        row.pack(fill="x", pady=(0, 4))
        tk.Entry(row, textvariable=self.folder, bg=SURFACE, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, ipady=5)
        self.button(row, "Browse…", self.browse).pack(side="left", padx=(8, 0))
        self.label(f"Needs about {NEED_GB} GB (Python, AI libraries and models). "
                   "Nothing is installed elsewhere on your PC.", 9, MUTED, pady=(0, 14))
        self.checks = tk.Frame(self.page, bg=BG)
        self.checks.pack(fill="x")
        self.folder.trace_add("write", lambda *_: self.run_checks())
        foot = tk.Frame(self.page, bg=BG)
        foot.pack(side="bottom", fill="x")
        self.install_btn = self.button(foot, "Install", self.start_install, primary=True)
        self.install_btn.pack(side="right")
        self.button(foot, "Cancel", self.destroy).pack(side="right", padx=8)
        self.gpu = None
        threading.Thread(target=lambda: self.q.put(("gpu", nvidia_gpu())), daemon=True).start()
        self.run_checks()

    def browse(self):
        d = filedialog.askdirectory(title="Choose where to install Ominvox")
        if d:
            p = Path(d)
            self.folder.set(str(p if p.name.lower() == APP.lower() else p / APP))

    def run_checks(self):
        for w in self.checks.winfo_children():
            w.destroy()
        ok = True
        target = Path(self.folder.get() or ".")
        anchor = Path(target.anchor or ".")
        try:
            free = shutil.disk_usage(anchor).free / 2**30
            good = free >= NEED_GB
            ok &= good
            self.check_row(good, f"{free:.0f} GB free on {anchor}" + ("" if good else f" - needs {NEED_GB} GB"))
        except OSError:
            ok = False
            self.check_row(False, "That drive doesn't exist")
        if self.gpu is None:
            self.check_row(None, "Looking for an NVIDIA graphics card…")
        elif self.gpu:
            self.check_row(True, self.gpu)
        else:
            self.check_row(False, "No NVIDIA graphics card found - Ominvox needs one to run in real time. "
                                  "You can still install it.")
        if (target / ".venv312").exists():
            self.check_row(True, "Existing install found - it will be updated (settings and models kept)")
        self.install_btn.config(state="normal" if ok else "disabled")

    def check_row(self, good, text):
        icon, color = {True: ("✓", GOOD), False: ("!", BAD), None: ("…", MUTED)}[good]
        row = tk.Frame(self.checks, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=icon, bg=BG, fg=color, font=("Segoe UI", 11, "bold"), width=2).pack(side="left")
        tk.Label(row, text=text, bg=BG, fg=TEXT, font=("Segoe UI", 10), anchor="w", justify="left",
                 wraplength=540).pack(side="left", fill="x")

    # ── page 2: install with progress ─────────────────────────
    def start_install(self):
        self.target = Path(self.folder.get())
        self.clear()
        self.label(f"Installing {APP}", 18, bold=True)
        self.status = self.label("Preparing…", 10, MUTED, pady=(0, 10))
        self.bar = ttk.Progressbar(self.page, maximum=100, mode="determinate")
        self.bar.pack(fill="x", pady=(0, 12), ipady=2)
        self.label("This takes 10-30 minutes depending on your internet. You can keep using your PC.",
                   9, MUTED)
        box = tk.Frame(self.page, bg=SURFACE)
        box.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(box, bg=SURFACE, fg=MUTED, relief="flat", font=("Consolas", 8),
                           wrap="none", height=12, state="disabled")
        self.log.pack(fill="both", expand=True, padx=8, pady=6)
        threading.Thread(target=self.install, daemon=True).start()

    def install(self):
        def report(kind, *args):
            self.q.put((kind, *args))
        install_to(self.target, report)

    # ── page 3: finished / failed ─────────────────────────────
    def show_done(self):
        self.clear()
        self.label(f"{APP} is installed", 18, bold=True)
        self.label("Shortcuts were added to your Desktop and Start menu.\n\n"
                   "When Ominvox opens for the first time it checks your PC, asks you to agree to "
                   "the voice licence, and downloads the AI models (about 3.5 GB) with a progress bar.",
                   10, MUTED, pady=(0, 16))
        foot = tk.Frame(self.page, bg=BG)
        foot.pack(side="bottom", fill="x")
        self.button(foot, f"Open {APP}", self.launch, primary=True).pack(side="right")
        self.button(foot, "Close", self.destroy).pack(side="right", padx=8)

    def show_failed(self, msg: str):
        self.status.config(text="Installation did not finish", fg=BAD)
        self.label(msg, 9, BAD)
        foot = tk.Frame(self.page, bg=BG)
        foot.pack(side="bottom", fill="x", pady=(8, 0))
        self.button(foot, "Try again", self.start_install, primary=True).pack(side="right")
        self.button(foot, "Close", self.destroy).pack(side="right", padx=8)

    def launch(self):
        subprocess.Popen([str(self.target / "Ominvox.exe")], cwd=self.target)
        self.destroy()

    # ── UI-thread message pump ────────────────────────────────
    def pump(self):
        try:
            while True:
                kind, *rest = self.q.get_nowait()
                if kind == "gpu":
                    self.gpu = rest[0] or ""
                    if hasattr(self, "checks") and self.checks.winfo_exists():
                        self.run_checks()
                elif kind == "status":
                    self.status.config(text=rest[0])
                    self.bar["value"] = rest[1]
                elif kind == "log":
                    self.log.config(state="normal")
                    self.log.insert("end", rest[0][:200] + "\n")
                    self.log.see("end")
                    self.log.config(state="disabled")
                elif kind == "done":
                    self.bar["value"] = 100
                    self.show_done()
                elif kind == "failed":
                    self.show_failed(rest[0])
        except queue.Empty:
            pass
        self.after(100, self.pump)


if __name__ == "__main__":
    if "--silent" in sys.argv:
        sys.exit(silent(sys.argv))
    Installer().mainloop()

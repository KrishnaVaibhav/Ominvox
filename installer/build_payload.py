"""Packs the app files OminvoxSetup.exe installs into .cache/build/payload.zip.

Takes the files git tracks (so commit first: the installer ships exactly what
is committed, never stray local files), leaves out what users don't need
(tests, docs, installer sources), and adds the freshly built Ominvox.exe.
"""
from __future__ import annotations
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".cache" / "build" / "payload.zip"
SKIP_DIRS = ("tests/", "docs/", "installer/", ".github/")


def main() -> int:
    files = subprocess.run(["git", "ls-files", "--cached"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.splitlines()
    files = [f for f in files if not f.startswith(SKIP_DIRS) and (ROOT / f).is_file()]
    exe = ROOT / "Ominvox.exe"
    if not exe.is_file():
        print("Ominvox.exe missing - build the launcher first.", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in files:
            z.write(ROOT / f, f)
        z.write(exe, "Ominvox.exe")
    print(f"payload: {len(files) + 1} files, {OUT.stat().st_size / 2**20:.1f} MB -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Run the test suites and print one summary.

  python tests/run_all.py            # fast + gpu (no sound)
  python tests/run_all.py fast       # no GPU models, no sound (~1 min)
  python tests/run_all.py all        # everything, including tests that PLAY SOUND

Sound tests play on the default device unless OMINVOX_TEST_DEVICE /
OMINVOX_TEST_OUTPUT name another one (see README "Tests").
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GROUPS = {
    "fast":  ["test_metrics.py", "test_firstrun.py", "test_speaker_id.py"],
    "gpu":   ["test_pipeline.py", "test_comprehensive.py", "test_e2e.py", "test_real_voices.py"],
    "sound": ["test_audio_devices.py", "test_live_ui.py"],
}


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # any console code page
    which = argv[0] if argv else "default"
    names = {"default": GROUPS["fast"] + GROUPS["gpu"],
             "all": GROUPS["fast"] + GROUPS["gpu"] + GROUPS["sound"]}.get(which, GROUPS.get(which))
    if not names:
        print(__doc__)
        return 2
    rows, failed = [], 0
    for name in names:
        t0 = time.time()
        p = subprocess.run([sys.executable, str(HERE / name)], cwd=HERE.parent,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = p.stdout + p.stderr
        m = re.search(r"Results: (\d+) passed, (\d+) failed", out)
        passed, fails = (int(m.group(1)), int(m.group(2))) if m else (0, 1)
        failed += fails or (p.returncode != 0)
        rows.append((name, passed, fails, time.time() - t0))
        status = "ok  " if not fails and p.returncode == 0 else "FAIL"
        print(f"{status} {name:26s} {passed:4d} passed {fails:3d} failed  {time.time() - t0:6.1f}s", flush=True)
        if fails or p.returncode:
            for line in out.splitlines():
                if "FAIL" in line:
                    print("      " + line[:160])
    total = sum(r[1] for r in rows)
    print(f"\n{total} checks passed, {failed} failed across {len(rows)} suites")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""System checks for the first-run screen. Each check returns a plain dict:
{"id", "label", "status": "ok" | "warn" | "fail", "detail", "fix_url"?}."""
from __future__ import annotations
import shutil
from pathlib import Path

NVIDIA_DRIVERS = "https://www.nvidia.com/Download/index.aspx"


def _check(id_, label, status, detail, fix_url=None) -> dict:
    out = {"id": id_, "label": label, "status": status, "detail": detail}
    if fix_url:
        out["fix_url"] = fix_url
    return out


def gpu() -> list[dict]:
    """GPU + driver. The pipeline needs an NVIDIA GPU with a CUDA 12 driver."""
    try:
        import torch
    except Exception:
        return [_check("gpu", "Graphics card", "fail", "PyTorch is not installed - run the setup again.")]

    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / 2**30
        status = "ok" if vram >= 7.5 else "warn"
        detail = f"{name}, {vram:.0f} GB" + ("" if status == "ok" else
                                               " - below 8 GB: use a smaller speech model (stt.model: small)")
        checks = [_check("gpu", "Graphics card", status, detail)]
        drv = driver_version()
        if drv:
            checks.append(_check("driver", "NVIDIA driver", "ok", f"version {drv}"))
        return checks

    # No CUDA: either no NVIDIA card, or a driver too old for CUDA 12.
    drv = driver_version()
    if drv:
        return [_check("gpu", "Graphics card", "fail",
                       f"NVIDIA driver {drv} is too old for this app. Install the latest driver, then restart.",
                       NVIDIA_DRIVERS)]
    return [_check("gpu", "Graphics card", "fail",
                   "No NVIDIA graphics card found. Ominvox needs one with at least 8 GB of memory.",
                   NVIDIA_DRIVERS)]


def driver_version() -> str | None:
    try:
        import pynvml
        pynvml.nvmlInit()
        v = pynvml.nvmlSystemGetDriverVersion()
        return v.decode() if isinstance(v, bytes) else v
    except Exception:
        return None


def disk(root: Path, needed_bytes: int) -> dict:
    free = shutil.disk_usage(root).free
    need = needed_bytes + 1 * 2**30                    # + 1 GB headroom
    detail = f"{free / 2**30:.0f} GB free on {root.drive or root.anchor}"
    if needed_bytes:
        detail += f", downloads need {needed_bytes / 2**30:.1f} GB"
    return _check("disk", "Disk space", "ok" if free >= need else "fail",
                  detail + ("" if free >= need else " - free up space, then try again."))


def audio() -> dict:
    try:
        from ..audio.devices import enumerate_devices
        d = enumerate_devices()
    except Exception as exc:
        return _check("audio", "Audio devices", "fail", f"Could not list audio devices: {exc}")
    n_out, n_sys = len(d["outputs"]), sum(1 for i in d["inputs"] if i["kind"] == "system")
    if not n_out or not n_sys:
        return _check("audio", "Audio devices", "fail",
                      "No speakers or headphones found. Plug one in, then click Check again.")
    return _check("audio", "Audio devices", "ok", f"{n_out} output device{'s' * (n_out != 1)}")


def run_all(root: Path, needed_bytes: int) -> list[dict]:
    return [*gpu(), disk(root, needed_bytes), audio()]

"""Live processing metrics: per-line timing, rolling stats and system load.

Times are time.monotonic() seconds. For each translated line we know:
  seg_start   when the original speech started (from capture timestamps)
  speech_end  when the original speech ended
  flush_t     when the line was handed to the GPU worker queue
  work_t      when the worker picked it up
  stage times diarize / stt / mt / tts (seconds)
  ready_t     when the translated audio (or text) was ready
  play_t      when the translated audio actually started playing

Derived:
  lag         play_t - seg_start   how far the translated line trails the video
  ready_lag   ready_t - seg_start  the minimum possible lag for this line
  rtf         processing / audio duration (< 1 keeps up in real time)
"""
from __future__ import annotations
import math
import threading
import time
from collections import deque

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

try:
    import pynvml
except Exception:  # pragma: no cover
    pynvml = None

# The parts of a line's lag, in order. They add up to lag = play_t - seg_start:
#   speech    the person is still talking (whole sentences are translated)
#   endpoint  silence needed to decide the sentence has ended
#   queue     waiting for the GPU worker (previous line still processing)
#   diarize/stt/mt/tts  processing
#   wait      translated audio waiting for the previous line to finish playing
#             (or, in fixed-lag mode, for its scheduled time)
STAGES = ("speech", "endpoint", "queue", "diarize", "stt", "mt", "tts", "wait")


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


class Metrics:
    WINDOW = 30          # lines used for rolling stats

    def __init__(self):
        self._lock = threading.Lock()
        self._lines: deque[dict] = deque(maxlen=200)
        self._nvml = None
        self._proc = psutil.Process() if psutil else None
        if pynvml is not None:
            try:
                pynvml.nvmlInit()
                self._nvml = pynvml.nvmlDeviceGetHandleByIndex(0)
            except Exception:
                self._nvml = None
        self.reset()

    def reset(self):
        with self._lock:
            self._lines.clear()
            self.lines_total = 0          # lines translated
            self.lines_spoken = 0         # lines that produced audio
            self.lines_late = 0           # fixed-lag mode: missed their slot
            self.lines_empty = 0          # speech segments with no words
            self.segments_dropped = 0     # worker queue full -> dropped
            self.errors = 0
            self.started_t = time.monotonic()

    # ── recording ─────────────────────────────────────────────

    def record(self, line: dict) -> dict:
        """Store a finished line (played or text-only) and return its summary."""
        seg = line["seg_start"]
        line = dict(line)
        end = line.get("speech_end", seg)
        line["speech"] = max(0.0, end - seg)
        line["endpoint"] = max(0.0, line.get("flush_t", end) - end)
        line["wait"] = max(0.0, line["play_t"] - line["ready_t"]) if "play_t" in line else 0.0
        summary = {
            "id": line.get("id"),
            "speaker": line.get("speaker"),
            "audio_s": round(line.get("audio_s", 0.0), 2),
            "stages": {k: round(line.get(k, 0.0) * 1000) for k in STAGES},
            "processing_ms": round((line["ready_t"] - line["work_t"]) * 1000),
            "ready_lag_s": round(line["ready_t"] - seg, 2),
            "response_s": round(line["ready_t"] - line.get("speech_end", line["ready_t"]), 2),
            "spoken": "play_t" in line,
        }
        if "play_t" in line:
            summary["lag_s"] = round(line["play_t"] - seg, 2)
            summary["late_s"] = round(line.get("late_s", 0.0), 2)
            summary["out_s"] = round(line.get("out_s", 0.0), 2)
        else:
            summary["lag_s"] = summary["ready_lag_s"]
        audio_s = line.get("audio_s") or 0.0
        summary["rtf"] = round((line["ready_t"] - line["work_t"]) / audio_s, 2) if audio_s else 0.0
        with self._lock:
            self._lines.append(summary)
            self.lines_total += 1
            if summary["spoken"]:
                self.lines_spoken += 1
            if summary.get("late_s", 0) > 0.05:
                self.lines_late += 1
        return summary

    def count(self, field: str, n: int = 1):
        with self._lock:
            setattr(self, field, getattr(self, field) + n)

    # ── reporting ─────────────────────────────────────────────

    def rolling(self) -> dict:
        with self._lock:
            recent = list(self._lines)[-self.WINDOW:]
            totals = dict(lines_total=self.lines_total, lines_spoken=self.lines_spoken,
                          lines_late=self.lines_late, lines_empty=self.lines_empty,
                          segments_dropped=self.segments_dropped, errors=self.errors,
                          uptime_s=round(time.monotonic() - self.started_t))
        lags = [l["lag_s"] for l in recent]
        ready = [l["ready_lag_s"] for l in recent]
        out = {
            **totals,
            "n": len(recent),
            "lag": {"last": lags[-1] if lags else None,
                    "avg": round(sum(lags) / len(lags), 2) if lags else None,
                    "p50": round(_pct(lags, .5), 2) if lags else None,
                    "p95": round(_pct(lags, .95), 2) if lags else None,
                    "min": min(lags) if lags else None,
                    "max": max(lags) if lags else None},
            "ready_p95": round(_pct(ready, .95), 2) if ready else None,
            "stages_avg": {k: round(sum(l["stages"][k] for l in recent) / len(recent))
                           for k in STAGES} if recent else {k: 0 for k in STAGES},
            "rtf_avg": round(sum(l["rtf"] for l in recent) / len(recent), 2) if recent else None,
            "history": [{"id": l["id"], "lag": l["lag_s"], "ready": l["ready_lag_s"]}
                        for l in recent],
            "suggested_lag_ms": self.suggest_fixed_lag_ms(ready),
        }
        return out

    @staticmethod
    def suggest_fixed_lag_ms(ready_lags: list[float]) -> int | None:
        """A fixed lag that ~95% of lines can make: p95 of ready-lag plus a margin
        for the player, rounded up to 250 ms. None until there's enough data."""
        if len(ready_lags) < 3:
            return None
        target = _pct(ready_lags, .95) + 0.4
        return int(max(1.0, math.ceil(target * 4) / 4) * 1000)

    def system(self) -> dict:
        s: dict = {}
        try:
            import torch
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                s["gpu_name"] = torch.cuda.get_device_name(0)
                s["vram_used_gb"] = round((total - free) / 2**30, 2)
                s["vram_total_gb"] = round(total / 2**30, 2)
        except Exception:
            pass
        if self._nvml is not None:
            try:
                s["gpu_util"] = pynvml.nvmlDeviceGetUtilizationRates(self._nvml).gpu
                s["gpu_temp_c"] = pynvml.nvmlDeviceGetTemperature(self._nvml, 0)
            except Exception:
                pass
        if psutil is not None:
            try:
                s["cpu_pct"] = psutil.cpu_percent(interval=None)
                s["ram_used_gb"] = round(self._proc.memory_info().rss / 2**30, 2)
            except Exception:
                pass
        return s

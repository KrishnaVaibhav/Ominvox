"""Playback of translated audio, with two timing modes (config playback.sync_mode):

  asap  - play each line as soon as it's ready (+ optional playback.delay_ms).
          Lowest latency, but the lag behind the video varies line to line.
  fixed - play each line exactly playback.fixed_lag_ms after the ORIGINAL line
          started. The lag is constant, so you can set your video player's audio
          delay to -fixed_lag_ms and the translated voice lines up with the picture.
          Lines that aren't ready in time play immediately and are counted as late.
"""
from __future__ import annotations
import queue
import threading
import time
from typing import Callable
import numpy as np

try:
    import pyaudiowpatch as pyaudio
except Exception:  # pragma: no cover
    pyaudio = None

from .devices import pa_new, pa_term, wasapi_default_output  # shared PortAudio lock

try:
    from scipy.signal import resample_poly
except Exception:  # pragma: no cover
    resample_poly = None


def _resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or not len(x):
        return x
    if resample_poly is not None:
        from math import gcd
        g = gcd(src, dst)
        return resample_poly(x, dst // g, src // g).astype(np.float32)
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x).astype(np.float32)


class Player:
    def __init__(self, cfg: dict, on_play: Callable[[dict], None] | None = None):
        self._pcfg = cfg["playback"]
        self.sr = self._pcfg.get("sample_rate", 24000)
        # IMPORTANT: if this is None, TTS plays to the DEFAULT output device — the
        # same device LoopbackCapture records — so the translated speech is fed
        # back in and re-translated (echo loop). Set playback.output_device_index
        # to a different device (headphones / a virtual cable) to break the loop.
        self.out_index = self._pcfg.get("output_device_index", None)
        self.on_play = on_play or (lambda _meta: None)
        self._q: "queue.Queue[tuple[float, np.ndarray, dict]]" = queue.Queue()
        self._stop = threading.Event()
        self._opened = threading.Event()
        self.error: str | None = None
        self.device_name: str | None = None
        self._t: threading.Thread | None = None
        self._queued_s = 0.0           # seconds of audio waiting in the queue
        self._busy_until = 0.0         # monotonic time the current clip finishes
        self._lock = threading.Lock()

    # ── settings (read live so the UI can change them) ─────────

    @property
    def delay(self) -> float:
        return float(self._pcfg.get("delay_ms", 0)) / 1000.0

    @delay.setter
    def delay(self, seconds: float):
        self._pcfg["delay_ms"] = int(seconds * 1000)

    @property
    def sync_mode(self) -> str:
        return self._pcfg.get("sync_mode", "asap")

    @property
    def fixed_lag(self) -> float:
        return float(self._pcfg.get("fixed_lag_ms", 4000)) / 1000.0

    def backlog_seconds(self) -> float:
        """Audio still to be played: queued clips + the rest of the current one."""
        with self._lock:
            return self._queued_s + max(0.0, self._busy_until - time.monotonic())

    # ── lifecycle ─────────────────────────────────────────────

    def start(self):
        self._stop.clear()                 # reset so a restart actually runs
        try:                               # discard stale queued audio
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            self._queued_s = 0.0
            self._busy_until = 0.0
        self.error = None
        self._opened.clear()
        self._t = threading.Thread(target=self._run, daemon=True, name="player")
        self._t.start()
        self._opened.wait(timeout=10)
        if self.error:
            raise RuntimeError(f"Audio output failed: {self.error}")

    def stop(self):
        self._stop.set()
        if self._t:
            self._t.join(timeout=2)

    # ── queueing ──────────────────────────────────────────────

    def submit(self, audio: np.ndarray, anchor: float | None = None, meta: dict | None = None):
        """Queue a clip. `anchor` = monotonic time the original line started
        (needed for fixed-lag mode). `meta` is passed back through on_play."""
        now = time.monotonic()
        meta = dict(meta or {})
        if self.sync_mode == "fixed" and anchor is not None:
            play_at = anchor + self.fixed_lag
        else:
            play_at = now + self.delay
        meta["target_t"] = play_at
        with self._lock:
            self._queued_s += len(audio) / self.sr
        self._q.put((play_at, audio, meta))

    def play_test_tone(self, seconds: float = 0.6, freq: float = 660.0):
        t = np.arange(int(self.sr * seconds)) / self.sr
        env = np.minimum(1.0, np.minimum(t, seconds - t) * 20)      # no clicks
        tone = (0.15 * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        with self._lock:
            self._queued_s += seconds
        self._q.put((time.monotonic(), tone, {"test": True}))

    # ── playback thread ───────────────────────────────────────

    def _run(self):
        if pyaudio is None:
            self._opened.set()
            return
        pa = pa_new()
        stream = None
        try:
            if self.out_index is not None:
                dev = pa.get_device_info_by_index(int(self.out_index))
            else:
                dev = wasapi_default_output(pa) or pa.get_default_output_device_info()
            self.device_name = dev["name"]
            # WASAPI (shared mode) only accepts the device's own rate and channel
            # layout, so open it natively and convert the 24 kHz mono TTS audio.
            dev_sr = int(dev["defaultSampleRate"])
            dev_ch = max(1, min(2, int(dev.get("maxOutputChannels", 2)) or 2))
            stream = None
            for rate, ch in ((dev_sr, dev_ch), (dev_sr, 1), (self.sr, 1)):
                try:
                    stream = pa.open(format=pyaudio.paFloat32, channels=ch, rate=rate,
                                     output=True, output_device_index=int(dev["index"]))
                    dev_sr, dev_ch = rate, ch
                    break
                except Exception as e:
                    last_err = e
            if stream is None:
                raise last_err
            self._opened.set()
            while not self._stop.is_set():
                try:
                    play_at, audio, meta = self._q.get(timeout=0.5)
                except queue.Empty:
                    continue
                dur = len(audio) / self.sr
                wait = play_at - time.monotonic()
                if wait > 0 and self._stop.wait(wait):
                    break
                start = time.monotonic()
                with self._lock:
                    self._queued_s = max(0.0, self._queued_s - dur)
                    self._busy_until = start + dur
                if not meta.get("test"):
                    meta.update(play_t=start, late_s=max(0.0, start - meta["target_t"]),
                                out_s=dur)
                    try:
                        self.on_play(meta)
                    except Exception:
                        pass
                pcm = _resample(np.asarray(audio, dtype=np.float32), self.sr, dev_sr)
                if dev_ch > 1:
                    pcm = np.repeat(pcm[:, None], dev_ch, axis=1)
                stream.write(np.ascontiguousarray(pcm, dtype=np.float32).tobytes())
        except Exception as e:
            self.error = str(e)
            print(f"[player] ERROR: {e}", flush=True)
        finally:
            self._opened.set()
            if stream is not None:
                try:
                    stream.stop_stream(); stream.close()
                except Exception:
                    pass
            pa_term(pa)

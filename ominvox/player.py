"""Delay-buffered playback of translated audio (subtitle-style offset to absorb
pipeline jitter). Plays to the default output device."""
from __future__ import annotations
import queue
import threading
import time
import numpy as np

try:
    import pyaudiowpatch as pyaudio
except Exception:  # pragma: no cover
    pyaudio = None

from .capture import pa_new, pa_term  # shared PortAudio init/terminate lock


class Player:
    def __init__(self, cfg: dict):
        self.sr = cfg["playback"].get("sample_rate", 24000)
        self.delay = cfg["playback"]["delay_ms"] / 1000.0
        # IMPORTANT: if this is None, TTS plays to the DEFAULT output device — the
        # same device LoopbackCapture records — so the translated speech is fed
        # back in and re-translated (echo loop). Set playback.output_device_index
        # to a different device (headphones / a virtual cable) to break the loop.
        self.out_index = cfg["playback"].get("output_device_index", None)
        self._q: "queue.Queue[tuple[float, np.ndarray]]" = queue.Queue()
        self._stop = threading.Event()
        self._opened = threading.Event()
        self.error: str | None = None
        self._t: threading.Thread | None = None

    def start(self):
        self._stop.clear()                 # reset so a restart actually runs
        try:                               # discard stale queued audio
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self.error = None
        self._opened.clear()
        self._t = threading.Thread(target=self._run, daemon=True, name="player")
        self._t.start()
        self._opened.wait(timeout=10)
        if self.error:
            raise RuntimeError(f"Audio output failed: {self.error}")

    def submit(self, audio: np.ndarray):
        self._q.put((time.time() + self.delay, audio))

    def _run(self):
        if pyaudio is None:
            self._opened.set()
            return
        pa = pa_new()
        stream = None
        try:
            open_kwargs = dict(format=pyaudio.paFloat32, channels=1, rate=self.sr, output=True)
            if self.out_index is not None:
                open_kwargs["output_device_index"] = int(self.out_index)
            stream = pa.open(**open_kwargs)
            self._opened.set()
            while not self._stop.is_set():
                try:
                    play_at, audio = self._q.get(timeout=0.5)
                except queue.Empty:
                    continue
                wait = play_at - time.time()
                if wait > 0 and self._stop.wait(wait):
                    break
                stream.write(np.ascontiguousarray(audio, dtype=np.float32).tobytes())
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

    def stop(self):
        self._stop.set()
        if self._t:
            self._t.join(timeout=2)

"""System-audio capture via WASAPI loopback (Windows). Yields mono float32 chunks
resampled to the pipeline sample rate. This is the source of the movie audio."""
from __future__ import annotations
import queue
import threading
import time
import numpy as np

from .devices import pa_new, pa_term, pyaudio


class LoopbackCapture:
    def __init__(self, target_sr: int = 16000, block_ms: int = 1000,
                 device_index: int | None = None):
        self.target_sr = target_sr
        self.block_ms = block_ms
        # If set, capture this exact device instead of auto-detecting the default
        # speaker's loopback. Use `run.bat --list-devices` to find loopback indices.
        self.device_index = device_index
        self.device_name: str | None = None   # set once the stream opens
        self.error: str | None = None          # set if the capture thread fails
        self._level = 0.0                      # last chunk RMS (see .level)
        self._level_ts = 0.0
        # (monotonic time the chunk ENDED, audio). Timestamps let the pipeline
        # measure how far the translation lags behind the original speech.
        self._q: "queue.Queue[tuple[float, np.ndarray]]" = queue.Queue(maxsize=64)
        self.dropped_chunks = 0
        self._stop = threading.Event()
        self._opened = threading.Event()       # set once the stream opened (or failed)
        self._thread: threading.Thread | None = None

    @property
    def level(self) -> float:
        """Live input RMS for the UI meter. Decays with time, so it falls to zero
        when the source goes quiet (WASAPI loopback delivers NO data at all while
        nothing is playing, so we can't rely on silent chunks arriving)."""
        age = max(0.0, time.monotonic() - self._level_ts)
        return self._level * (0.5 ** (age / 0.3))      # halves every 0.3 s

    @classmethod
    def from_cfg(cls, cfg: dict) -> "LoopbackCapture":
        a = cfg["audio"]
        return cls(a["sample_rate"], a["block_ms"], a.get("input_device_index"))

    def _default_loopback(self, pa) -> dict:
        """Find the WASAPI loopback device for the current default speaker.

        Robust against PortAudio's 31-char device-name truncation (which breaks a
        naive `spk_name in dev_name` substring match) and against odd default
        configs, by trying, in order: the PyAudioWPatch helper, an exact/prefix
        name match, then simply the first available loopback device.
        """
        # 1. Canonical helper from PyAudioWPatch (handles the default-speaker case).
        try:
            info = pa.get_default_wasapi_loopback()
            if info:
                return info
        except Exception:
            pass

        # 2. Heuristic match against the default output device.
        candidates = []
        try:
            candidates = list(pa.get_loopback_device_info_generator())
        except Exception:
            candidates = []

        spk_name = ""
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            spk = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            spk_name = spk["name"]
        except Exception:
            pass

        if spk_name:
            for dev in candidates:
                # PortAudio truncates names to 31 chars, so compare on a shared prefix.
                if spk_name in dev["name"] or dev["name"][:24].startswith(spk_name[:24]):
                    return dev

        # 3. Last resort: any loopback device (better than crashing the capture thread).
        if candidates:
            return candidates[0]

        raise RuntimeError(
            "No WASAPI loopback device found. Make sure an audio output device is "
            "active (something playing), then restart. Run `run.bat --list-devices`."
        )

    def _run(self):
        pa = pa_new()
        stream = None
        try:
            if self.device_index is not None:
                dev = pa.get_device_info_by_index(int(self.device_index))
            else:
                dev = self._default_loopback(pa)
            src_sr = int(dev["defaultSampleRate"])
            self.device_name = dev["name"]
            frames = int(src_sr * self.block_ms / 1000)
            reported = int(dev.get("maxInputChannels", 2)) or 2

            # Some loopback devices (e.g. game headsets) reject their reported
            # channel count with -9998; try the reported value, then 2, then 1.
            # Blocking mode, NOT callback mode: callback-mode loopback fails with
            # -9999 "Unanticipated host error" when this process is also playing
            # to that device (measured). But a blocking read() would wait forever
            # on a loopback while nothing plays, so we only ever read frames that
            # are already available (see the loop below).
            tried, ch = [], None
            for c in dict.fromkeys([reported, 2, 1]):
                try:
                    stream = pa.open(
                        format=pyaudio.paFloat32, channels=c, rate=src_sr,
                        frames_per_buffer=frames, input=True,
                        input_device_index=dev["index"],
                    )
                    ch = c
                    break
                except Exception as e:
                    tried.append(f"{c}ch({e})")
                    stream = None
            if stream is None:
                raise RuntimeError(
                    f"could not open '{dev['name']}' at {src_sr} Hz "
                    f"[tried {', '.join(tried)}]")
            print(f"[capture] device [{dev['index']}] {dev['name']} "
                  f"({src_sr} Hz, {ch} ch)", flush=True)
            self._opened.set()
            while not self._stop.is_set():
                if stream.get_read_available() < frames:
                    self._stop.wait(0.01)          # nothing to read yet: never block
                    continue
                raw = stream.read(frames, exception_on_overflow=False)
                a = np.frombuffer(raw, dtype=np.float32).reshape(-1, ch).mean(axis=1)
                a = self._resample(a, src_sr, self.target_sr)
                now = time.monotonic()
                if len(a):
                    rms = float(np.sqrt(np.mean(a * a)))
                    # decaying peak, decayed by elapsed time (not per chunk), so the
                    # meter falls just as fast whether silence arrives as quiet
                    # chunks or as no chunks at all
                    self._level = max(rms, self.level)
                    self._level_ts = now
                try:
                    self._q.put_nowait((now, a))
                except queue.Full:
                    self.dropped_chunks += 1  # drop on backpressure to stay live
        except Exception as e:
            self.error = str(e)
            print(f"[capture] ERROR: {e}", flush=True)
        finally:
            self._opened.set()
            if stream is not None:
                try:
                    stream.stop_stream(); stream.close()
                except Exception:
                    pass
            pa_term(pa)

    @staticmethod
    def _resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
        if src == dst:
            return x
        n = int(round(len(x) * dst / src))
        return np.interp(np.linspace(0, len(x), n, endpoint=False),
                         np.arange(len(x)), x).astype(np.float32)

    def start(self):
        if pyaudio is None:
            raise RuntimeError("PyAudioWPatch not available (Windows only). pip install PyAudioWPatch")
        self._stop.clear()                 # reset so a restart actually runs
        self._opened.clear()
        self.error = None
        self._level = 0.0
        self._drain()                      # discard stale audio from a prior session
        self._thread = threading.Thread(target=self._run, daemon=True, name="capture")
        self._thread.start()
        # Surface "device won't open" to the caller instead of failing silently.
        self._opened.wait(timeout=10)
        if self.error:
            raise RuntimeError(f"Audio input failed: {self.error}")

    def _drain(self):
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def chunks(self, with_time: bool = False):
        """Yield audio chunks. Yields None when no audio arrived for one block
        (source paused/silent), so consumers can treat it as silence.
        with_time=True yields (end_time_monotonic, chunk) pairs instead
        ((now, None) for the silence marker)."""
        wait = max(self.block_ms / 1000.0, 0.05)
        while not self._stop.is_set():
            try:
                t, a = self._q.get(timeout=wait)
            except queue.Empty:
                t, a = time.monotonic(), None
            yield (t, a) if with_time else a

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

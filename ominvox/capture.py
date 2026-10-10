"""System-audio capture via WASAPI loopback (Windows). Yields mono float32 chunks
resampled to the pipeline sample rate. This is the source of the movie audio."""
from __future__ import annotations
import queue
import threading
import time
import numpy as np

try:
    import pyaudiowpatch as pyaudio  # WASAPI loopback fork
except Exception:  # pragma: no cover - non-Windows / not installed
    pyaudio = None

# PortAudio's Pa_Initialize/Pa_Terminate (called by PyAudio()/terminate()) are NOT
# thread-safe — they mutate global refcounted state and, on WASAPI, init/uninit COM.
# Concurrent construct/terminate from different threads (e.g. a WS connect enumerating
# devices while the capture thread starts) corrupts that state and segfaults the
# process. Serialize ONLY construction and teardown; stream I/O stays lock-free so
# capture and playback still run at the same time.
_PA_LOCK = threading.Lock()


def pa_new():
    """Construct a PyAudio instance under the global PortAudio lock."""
    with _PA_LOCK:
        return pyaudio.PyAudio()


def pa_term(pa) -> None:
    """Terminate a PyAudio instance under the global PortAudio lock."""
    if pa is None:
        return
    with _PA_LOCK:
        try:
            pa.terminate()
        except Exception:
            pass


def enumerate_devices() -> dict:
    """Return EVERY selectable audio device for the UI:
      inputs  = system-audio loopbacks (kind='system') AND microphones/line-in (kind='mic')
      outputs = real playback devices
    Shape: {'inputs':[{index,name,kind,default}], 'outputs':[{index,name,default}],
            'default_input', 'default_output'}.
    """
    out = {"inputs": [], "outputs": [], "default_input": None, "default_output": None}
    if pyaudio is None:
        return out
    pa = pa_new()
    try:
        default_loop = None
        try:
            default_loop = int(pa.get_default_wasapi_loopback()["index"])
        except Exception:
            pass
        default_mic = None
        try:
            default_mic = int(pa.get_default_input_device_info()["index"])
        except Exception:
            pass
        try:
            out["default_output"] = int(pa.get_default_output_device_info()["index"])
        except Exception:
            pass
        out["default_input"] = default_loop if default_loop is not None else default_mic

        loopback_idx = set()
        # 1) System-audio loopbacks (what the movie plays through)
        try:
            for d in pa.get_loopback_device_info_generator():
                idx = int(d["index"])
                loopback_idx.add(idx)
                out["inputs"].append({
                    "index": idx,
                    "name": d["name"].replace(" [Loopback]", ""),
                    "kind": "system",
                    "default": idx == default_loop,
                })
        except Exception:
            pass
        # 2) Real input devices: microphones, line-in, capture cards, virtual cables
        seen_names = set()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            idx = int(info["index"])
            if idx in loopback_idx:
                continue
            if int(info.get("maxInputChannels", 0)) <= 0:
                continue
            if "loopback" in info["name"].lower():
                continue
            if info["name"] in seen_names:
                continue
            seen_names.add(info["name"])
            out["inputs"].append({
                "index": idx,
                "name": info["name"],
                "kind": "mic",
                "default": idx == default_mic,
            })
        # 3) Outputs (for playback / avoiding the echo loop)
        seen_out = set()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if int(info.get("maxOutputChannels", 0)) <= 0:
                continue
            if "loopback" in info["name"].lower():
                continue
            if info["name"] in seen_out:
                continue
            seen_out.add(info["name"])
            out["outputs"].append({
                "index": int(info["index"]),
                "name": info["name"],
                "default": int(info["index"]) == out["default_output"],
            })
    finally:
        pa_term(pa)
    return out


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
        self._q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._opened = threading.Event()       # set once the stream opened (or failed)
        self._thread: threading.Thread | None = None

    @property
    def level(self) -> float:
        """Live input RMS for the UI meter. Decays with time, so it falls to zero
        when the source goes quiet (WASAPI loopback delivers NO data at all while
        nothing is playing, so we can't rely on silent chunks arriving)."""
        age = time.monotonic() - self._level_ts
        return self._level * (0.5 ** (age / 0.3)) if age > 0.3 else self._level

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
            ch_box = [reported]

            # Callback mode, not blocking read(): a loopback stream gets no data
            # while nothing plays, so read() would block forever and stop() could
            # never close the stream.
            def _callback(in_data, frame_count, time_info, status):
                a = np.frombuffer(in_data, dtype=np.float32).reshape(-1, ch_box[0]).mean(axis=1)
                a = self._resample(a, src_sr, self.target_sr)
                if len(a):
                    rms = float(np.sqrt(np.mean(a * a)))
                    self._level = max(rms, self.level * 0.85)
                    self._level_ts = time.monotonic()
                try:
                    self._q.put_nowait(a)
                except queue.Full:
                    pass  # drop on backpressure to stay live
                return (None, pyaudio.paContinue)

            # Some loopback devices (e.g. game headsets) reject their reported
            # channel count with -9998; try the reported value, then 2, then 1.
            tried = []
            for c in dict.fromkeys([reported, 2, 1]):
                ch_box[0] = c
                try:
                    stream = pa.open(
                        format=pyaudio.paFloat32, channels=c, rate=src_sr,
                        frames_per_buffer=frames, input=True,
                        input_device_index=dev["index"],
                        stream_callback=_callback,
                    )
                    break
                except Exception as e:
                    tried.append(f"{c}ch({e})")
                    stream = None
            if stream is None:
                raise RuntimeError(
                    f"could not open '{dev['name']}' at {src_sr} Hz "
                    f"[tried {', '.join(tried)}]")
            stream.start_stream()
            print(f"[capture] device [{dev['index']}] {dev['name']} "
                  f"({src_sr} Hz, {ch_box[0]} ch)", flush=True)
            self._opened.set()
            self._stop.wait()
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

    def chunks(self):
        """Yield audio chunks. Yields None when no audio arrived for one block
        (source paused/silent), so consumers can treat it as silence."""
        wait = max(self.block_ms / 1000.0, 0.05)
        while not self._stop.is_set():
            try:
                yield self._q.get(timeout=wait)
            except queue.Empty:
                yield None

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

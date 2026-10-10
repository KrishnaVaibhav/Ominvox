"""Audio device helpers shared by capture and playback (Windows / WASAPI).

- pa_new / pa_term: create and destroy PyAudio instances under one lock
- enumerate_devices: the inputs/outputs shown in the UI
- wasapi_default_output: the default speakers as a WASAPI device
"""
from __future__ import annotations
import threading

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


def wasapi_default_output(pa) -> dict | None:
    """The default speakers as a WASAPI device (the API loopback capture uses)."""
    try:
        api = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        return pa.get_device_info_by_index(api["defaultOutputDevice"])
    except Exception:
        return None


def enumerate_devices() -> dict:
    """Return every selectable audio device for the UI, WASAPI only.

    Windows lists each device once per audio API (MME, DirectSound, WASAPI...),
    and MME cuts names to 31 characters, so showing all of them gives several
    near-identical entries per device. Loopback capture needs WASAPI anyway.
      inputs  = system-audio loopbacks (kind='system') + microphones/line-in (kind='mic')
      outputs = playback devices
    Shape: {'inputs':[{index,name,kind,default}], 'outputs':[{index,name,default}],
            'default_input', 'default_output'}.
    """
    out = {"inputs": [], "outputs": [], "default_input": None, "default_output": None}
    if pyaudio is None:
        return out
    pa = pa_new()
    try:
        try:
            api = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except Exception:
            return out
        wasapi = api["index"]
        default_out = api.get("defaultOutputDevice", -1)
        default_mic = api.get("defaultInputDevice", -1)
        default_loop = None
        try:
            default_loop = int(pa.get_default_wasapi_loopback()["index"])
        except Exception:
            pass

        loopbacks, mics, outputs = [], [], []
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d.get("hostApi") != wasapi:
                continue
            idx = int(d["index"])
            if d.get("isLoopbackDevice") or "[Loopback]" in d["name"]:
                loopbacks.append({"index": idx, "name": d["name"].replace(" [Loopback]", ""),
                                  "kind": "system", "default": idx == default_loop})
            elif int(d.get("maxInputChannels", 0)) > 0:
                mics.append({"index": idx, "name": d["name"], "kind": "mic",
                             "default": idx == default_mic})
            elif int(d.get("maxOutputChannels", 0)) > 0:
                outputs.append({"index": idx, "name": d["name"], "default": idx == default_out})
        out["inputs"] = loopbacks + mics
        out["outputs"] = outputs
        out["default_input"] = default_loop if default_loop is not None else (
            default_mic if default_mic >= 0 else None)
        out["default_output"] = default_out if default_out >= 0 else None
    finally:
        pa_term(pa)
    return out

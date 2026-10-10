"""Entry point.  Run:  python -m ominvox.app  [--target es] [--check]
--check runs a dependency/self-test without needing models or audio."""
from __future__ import annotations
import argparse
import os
import sys

from . import config


def selftest(cfg: dict) -> int:
    print(f"Ominvox v{__import__('ominvox').__version__}")
    print(f"Project root : {cfg['_root']}")
    print(f"Cache dir    : {cfg['_cache_dir']}  (all downloads pinned here)")
    print(f"Target lang  : {cfg['translate']['target_lang']}")
    print(f"Voice mode   : {cfg['tts']['voice_mode']}")
    print("\nDependency check:")
    # (import_name, label) — coqui-tts installs under the "TTS" import namespace.
    mods = {
        "pyaudiowpatch": "WASAPI loopback capture (Windows)",
        "torch": "VAD / diarization / TTS backend",
        "faster_whisper": "speech-to-text",
        "pyannote.audio": "speaker diarization",
        "transformers": "NLLB translation",
        "TTS": "coqui-tts (XTTS voice cloning)",
    }
    missing = []
    for m, what in mods.items():
        try:
            __import__(m)
            print(f"  ok   {m:16} - {what}")
        except Exception:
            print(f"  MISS {m:16} - {what}")
            missing.append(m)

    # --- CUDA must be active: a CPU-only torch build silently kills GPU perf ---
    print("\nCUDA check:")
    cuda_ok = False
    try:
        import torch
        cuda_ok = bool(torch.cuda.is_available())
        print(f"  torch version          : {torch.__version__}")
        print(f"  torch.cuda.is_available: {cuda_ok}")
        if cuda_ok:
            name = torch.cuda.get_device_name(0)
            cap = torch.cuda.get_device_capability(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            print(f"  ok   device 0          : {name} (sm_{cap[0]}{cap[1]}, {vram_gb:.1f} GB)")
        else:
            print("  FAIL torch.cuda.is_available() is False.")
            print("       This is almost certainly a CPU-only torch build. Reinstall the CUDA wheel:")
            print("       pip install --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu124")
    except Exception as e:
        print(f"  FAIL could not import torch / query CUDA: {e}")

    if missing:
        print("\nMissing packages -> run setup_conda.bat. Capture is Windows-only.")
        return 1
    if not cuda_ok:
        print("\nFAIL: CUDA not active. GPU pipeline will not run on the 8 GB budget. Self-test failing loudly.")
        return 2
    print("\nAll core deps present and CUDA active.")
    return 0


def spike(cfg: dict, window_s: float = 5.0, translate: bool = False,
          max_seconds: float = 0.0) -> int:
    """Phase 0 spike: WASAPI loopback capture -> faster-whisper, print real-time factor.
    RTF = STT processing time / audio duration. RTF < 1.0 means STT keeps up live.
    max_seconds > 0 auto-stops after that long (headless); 0 runs until Ctrl+C."""
    import time
    import numpy as np
    from .audio.capture import LoopbackCapture
    from .pipeline.stt import STT

    sr = cfg["audio"]["sample_rate"]
    s = cfg["stt"]
    print(f"Phase 0 spike: WASAPI loopback -> faster-whisper "
          f"(model={s['model']} {s['compute_type']} on {s['device']})")
    print(f"STT window   : {window_s:.1f} s   task: {'translate->en' if translate else 'transcribe'}")
    print("Loading STT model (first run downloads weights into .cache\\whisper)...")
    stt = STT(cfg)
    if stt.model is None:
        print("FAIL: faster-whisper not available. Run setup.ps1.")
        return 1

    cap = LoopbackCapture.from_cfg(cfg)
    try:
        cap.start()
    except RuntimeError as e:
        print(f"FAIL capture: {e}")
        return 1
    stop_note = f"auto-stops after {max_seconds:.0f}s" if max_seconds > 0 else "Ctrl+C to stop"
    print(f"\nCapturing system audio. >>> PLAY YOUR MOVIE NOW <<<  ({stop_note})\n")

    buf, buf_n, need = [], 0, int(window_s * sr)
    rtfs: list[float] = []
    t_start = time.perf_counter()
    try:
        for chunk in cap.chunks():
            if chunk is None:               # source silent / paused
                if max_seconds and (time.perf_counter() - t_start) >= max_seconds:
                    break
                continue
            buf.append(chunk); buf_n += len(chunk)
            if buf_n < need:
                if max_seconds and (time.perf_counter() - t_start) >= max_seconds:
                    break
                continue
            audio = np.concatenate(buf); buf, buf_n = [], 0
            dur = len(audio) / sr
            t0 = time.perf_counter()
            text, lang = stt.transcribe(audio, translate_to_en=translate)
            dt = time.perf_counter() - t0
            rtf = dt / dur if dur else 0.0
            rtfs.append(rtf)
            avg = sum(rtfs) / len(rtfs)
            flag = "ok" if rtf < 1.0 else "SLOW"
            print(f"[{lang}] rtf={rtf:.2f} (proc {dt:.2f}s / audio {dur:.1f}s) avg={avg:.2f} {flag}")
            if text:
                print(f"    {text}")
            if max_seconds and (time.perf_counter() - t_start) >= max_seconds:
                break
    except KeyboardInterrupt:
        print("\nStopping spike...")
    finally:
        cap.stop()

    if rtfs:
        print(f"\nReal-time factor over {len(rtfs)} windows: "
              f"avg={sum(rtfs)/len(rtfs):.2f}  min={min(rtfs):.2f}  max={max(rtfs):.2f}")
        print("RTF < 1.0 => STT keeps up with realtime on this GPU; budget remains for MT+TTS.")
    else:
        print("\nNo speech windows processed. Was audio actually playing on the default output?")
    return 0


def list_devices() -> int:
    """List ALL input sources (system-audio loopbacks + mics) and outputs, with
    indices for audio.input_device_index / playback.output_device_index."""
    from .audio.devices import enumerate_devices
    d = enumerate_devices()
    if not d["inputs"] and not d["outputs"]:
        print("No devices found (PyAudioWPatch unavailable or no audio devices).")
        return 1
    print("== INPUT sources (set audio.input_device_index) ==")
    for it in d["inputs"]:
        tag = "  <- default" if it.get("default") else ""
        kind = "system audio" if it.get("kind") == "system" else "mic"
        print(f"  [{it['index']:>2}] {it['name']}  ({kind}){tag}")
    print("\n== OUTPUTS (set playback.output_device_index to avoid the echo loop) ==")
    for it in d["outputs"]:
        tag = "  <- default" if it.get("default") else ""
        print(f"  [{it['index']:>2}] {it['name']}{tag}")
    print("\nTip: input = where your MOVIE plays (a 'system' device), or a 'mic'; "
          "output = a different device so the translation isn't re-captured.")
    return 0


def audio_test(cfg: dict, seconds: float = 10.0) -> int:
    """Capture system audio and print the live signal level. Proves whether the
    selected device is actually receiving the movie's audio (RMS > 0)."""
    import time
    import numpy as np
    from .audio.capture import LoopbackCapture

    cap = LoopbackCapture.from_cfg(cfg)
    try:
        cap.start()
    except RuntimeError as e:
        print(f"FAIL: {e}")
        return 1
    print(f"Listening for {seconds:.0f}s  >>> PLAY YOUR MOVIE / SOME AUDIO NOW <<<\n")
    peak = 0.0
    n = 0
    t0 = time.time()
    for chunk in cap.chunks():
        if cap.error:
            print(f"FAIL: capture error -> {cap.error}")
            break
        if chunk is None:
            print("  level 0.0000 |   (no audio arriving - is something playing?)")
        elif len(chunk):
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            peak = max(peak, rms)
            n += 1
            bar = "#" * min(50, int(rms * 500))
            print(f"  level {rms:6.4f} |{bar}")
        if time.time() - t0 >= seconds:
            break
    cap.stop()
    print(f"\nDevice : {cap.device_name}")
    print(f"Peak level over {n} chunks: {peak:.4f}")
    if peak > 1e-3:
        print("RESULT: AUDIO DETECTED - capture is working.")
        return 0
    print("RESULT: SILENCE - no system audio captured.")
    print("  Fix: run `run.bat --list-devices`, find the loopback whose name matches")
    print("  the device your movie plays on, and set audio.input_device_index in config.yaml.")
    return 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="ominvox")
    p.add_argument("--config", default=None)
    p.add_argument("--target", help="override target language ISO code")
    p.add_argument("--check", action="store_true", help="dependency self-test only")
    p.add_argument("--list-devices", action="store_true",
                   help="list loopback + output devices with indices")
    p.add_argument("--audio-test", action="store_true",
                   help="capture system audio and show the live signal level")
    p.add_argument("--audio-seconds", type=float, default=10.0,
                   help="how long --audio-test listens (default 10s)")
    p.add_argument("--spike", action="store_true",
                   help="Phase 0 spike: capture + STT, print real-time factor")
    p.add_argument("--spike-window", type=float, default=5.0,
                   help="seconds of audio per STT window in --spike (default 5)")
    p.add_argument("--spike-seconds", type=float, default=0.0,
                   help="auto-stop --spike after N seconds (0 = run until Ctrl+C)")
    p.add_argument("--translate", action="store_true",
                   help="STT translate-to-English (whisper) instead of transcribe")
    p.add_argument("--ui", action="store_true",
                   help="start the web UI at http://127.0.0.1:8765")
    p.add_argument("--host", default="127.0.0.1", help="UI server host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765, help="UI server port (default 8765)")
    p.add_argument("--no-browser", action="store_true", help="don't open browser on UI start")
    p.add_argument("--window", action="store_true",
                   help="start the UI in its own app window (what Ominvox.exe runs)")
    args = p.parse_args(argv)

    # The UI remembers choices made in it (user_settings.json); CLI modes don't.
    cfg = config.load(args.config, user_settings=args.ui or args.window)
    if args.target:
        cfg["translate"]["target_lang"] = args.target

    if args.list_devices:
        return list_devices()
    if args.audio_test:
        return audio_test(cfg, seconds=args.audio_seconds)
    if args.check:
        return selftest(cfg)
    if args.spike:
        return spike(cfg, window_s=args.spike_window, translate=args.translate,
                     max_seconds=args.spike_seconds)
    if args.window:
        from .ui.server import UIServer
        from .ui.window import run_window
        run_window(UIServer(cfg, persist=True), host=args.host, port=args.port)
        # Window closed: exit hard so audio/CUDA worker threads can't keep the
        # process (and its VRAM) alive in the background.
        sys.stdout.flush()
        os._exit(0)
    if args.ui:
        from .ui.server import UIServer
        UIServer(cfg, persist=True).serve(host=args.host, port=args.port,
                                          open_browser=not args.no_browser)
        return 0

    from .pipeline.orchestrator import Pipeline
    Pipeline(cfg).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

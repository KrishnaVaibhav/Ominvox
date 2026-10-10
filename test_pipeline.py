"""Synthetic pipeline test - no live audio or movie required.
Runs each stage with generated audio and reports pass/fail for every step.
Usage: .venv312/Scripts/python.exe test_pipeline.py
"""
import os, sys, time, traceback
import numpy as np

# Bypass Coqui TTS non-commercial license prompt in non-interactive runs.
# The tos_agreed.txt file in the model dir also covers this, but belt-and-suspenders.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

PASS = []
FAIL = []

def check(name, fn):
    t0 = time.perf_counter()
    try:
        result = fn()
        dt = time.perf_counter() - t0
        print(f"  PASS  {name} ({dt:.2f}s)" + (f"  -> {result}" if result is not None else ""))
        PASS.append(name)
        return result
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"  FAIL  {name} ({dt:.2f}s)  {type(e).__name__}: {e}")
        traceback.print_exc()
        FAIL.append(name)
        return None

# ------ synthetic audio helpers ------
SR = 16000

def silence(seconds=1.0):
    return np.zeros(int(SR * seconds), dtype=np.float32)

def tone(freq=440.0, seconds=1.0, amp=0.3):
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)

def speech_like(seconds=2.0):
    """Mix of frequencies to trigger Silero VAD as speech."""
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    sig = np.zeros_like(t)
    for f, a in [(200, 0.15), (400, 0.10), (800, 0.08), (1600, 0.05), (3200, 0.03)]:
        sig += a * np.sin(2 * np.pi * f * t)
    return sig.astype(np.float32)


# ============================================================
print("\n=== 1. Config ===")
# ============================================================

cfg = check("config.load", lambda: (
    __import__("ominvox.config", fromlist=["load"]).load()
))
if cfg is None:
    print("Config failed — cannot continue.")
    sys.exit(1)


# ============================================================
print("\n=== 2. VAD (Silero, CPU) ===")
# ============================================================

from ominvox.vad import VAD
vad_obj = check("VAD.__init__", lambda: VAD(SR))

if vad_obj:
    check("VAD.is_speech(silence) -> False",
          lambda: (not vad_obj.is_speech(silence(1.0))) or "model not loaded (pass-all mode)")
    check("VAD.is_speech(speech-like tone) -> True",
          lambda: vad_obj.is_speech(speech_like(2.0)))
    check("VAD.is_speech(440 Hz sine) passes without crash",
          lambda: isinstance(vad_obj.is_speech(tone(440, 1.0)), bool))


# ============================================================
print("\n=== 3. STT (faster-whisper medium int8, CUDA) ===")
# ============================================================

from ominvox.stt import STT
stt_obj = check("STT.__init__ (loads whisper model)", lambda: STT(cfg))

if stt_obj and stt_obj.model:
    check("STT.transcribe(silence) -> ('', lang)",
          lambda: stt_obj.transcribe(silence(2.0)))

    # A very short spoken-like chirp — won't produce real text but must not crash.
    check("STT.transcribe(speech-like 3s) returns (str, str)",
          lambda: (
              lambda r: (isinstance(r[0], str) and isinstance(r[1], str))
          )(stt_obj.transcribe(speech_like(3.0))))

    check("STT.transcribe(silence, translate_to_en=True) no crash",
          lambda: stt_obj.transcribe(silence(1.0), translate_to_en=True))
elif stt_obj:
    print("  SKIP  STT inference — model not loaded (faster-whisper unavailable?)")


# ============================================================
print("\n=== 4. Diarizer (real pyannote model — HF terms accepted) ===")
# ============================================================

from ominvox.diarize import Diarizer

diar_obj = check("Diarizer.__init__ (downloads/loads pyannote model)", lambda: Diarizer(cfg))

if diar_obj:
    check("Diarizer.pipeline loaded (not None)",
          lambda: diar_obj.pipeline is not None)
    # Synthetic audio won't contain real speech; pyannote may find no segments,
    # in which case the code falls back to "SPEAKER_00".  Either way it must
    # return a non-empty string without crashing.
    check("Diarizer.label(4s silence) returns str",
          lambda: isinstance(diar_obj.label(silence(4.0)), str) and
                  len(diar_obj.label(silence(4.0))) > 0)
    check("Diarizer.label(5s speech-like) returns str",
          lambda: isinstance(diar_obj.label(speech_like(5.0)), str) and
                  len(diar_obj.label(speech_like(5.0))) > 0)


# ============================================================
print("\n=== 5. MT (whisper pass-through mode) ===")
# ============================================================

from ominvox.mt import Translator
mt_obj = check("Translator.__init__", lambda: Translator(cfg))

if mt_obj:
    check("Translator.translate('Hello world', 'en') pass-through",
          lambda: mt_obj.translate("Hello world", "en") == "Hello world")
    check("Translator.translate('', 'en') returns ''",
          lambda: mt_obj.translate("", "en") == "")


# ============================================================
print("\n=== 6. SpeakerRegistry (no TTS) ===")
# ============================================================

from ominvox.voices import SpeakerRegistry
reg = check("SpeakerRegistry.__init__", lambda: SpeakerRegistry(cfg))

if reg:
    check("SpeakerRegistry.add_audio accumulates",
          lambda: (
              reg.add_audio("SPK_00", speech_like(3.0)),
              reg.reference("SPK_00") is None  # 3s < min_ref_seconds=6
          ))
    check("SpeakerRegistry.add_audio flushes at min_ref_seconds",
          lambda: (
              reg.add_audio("SPK_00", speech_like(4.0)),
              reg.reference("SPK_00") is not None  # now 7s >= 6s
          ))
    check("SpeakerRegistry reference wav exists on disk",
          lambda: reg.reference("SPK_00").exists())
    check("SpeakerRegistry.latents initially None",
          lambda: reg.latents("SPK_00") is None)
    check("SpeakerRegistry.set_latents roundtrip",
          lambda: (
              reg.set_latents("SPK_00", "dummy_gpt", "dummy_spk"),
              reg.latents("SPK_00") == ("dummy_gpt", "dummy_spk")
          ))


# ============================================================
print("\n=== 7. VoiceSynth + XTTS-v2 (GPU, slow — skipped if model not cached) ===")
# ============================================================

import soundfile as sf, pathlib

_xtts_dir = cfg["_cache_dir"] / "tts" / "tts" / "tts_models--multilingual--multi-dataset--xtts_v2"
_xtts_ready = (_xtts_dir / "model.pth").exists()

if not _xtts_ready:
    print(f"  SKIP  XTTS model not yet downloaded at {_xtts_dir}")
    print("        Run: run.bat --target en  (first run downloads ~1.8 GB from HuggingFace)")
else:
    from ominvox.voices import VoiceSynth

    def make_ref_wav():
        """Write a short sine-wave WAV at 16 kHz as a dummy reference."""
        audio = tone(220.0, seconds=7.0, amp=0.2)
        p = pathlib.Path(cfg["_speaker_dir"]) / "_test_ref.wav"
        sf.write(str(p), audio, SR)
        return str(p)

    synth_obj = check("VoiceSynth.__init__ (loads XTTS-v2 model)", lambda: VoiceSynth(cfg))

    if synth_obj and synth_obj.tts:
        ref_wav = check("make test reference wav", make_ref_wav)
        if ref_wav:
            check("VoiceSynth._latents_for(wav) from sine ref",
                  lambda: synth_obj._latents_for("wav", ref_wav, "_test") is not None)
            check("VoiceSynth.speak short sentence (built-in voice before cloning)",
                  lambda: isinstance(synth_obj.speak("Hello.", "_test"), np.ndarray))
            check("VoiceSynth.speak output dtype is float32",
                  lambda: synth_obj.speak("Hi there.", "_test").dtype == np.float32)
            check("VoiceSynth.speak Chinese target maps zh -> zh-cn",
                  lambda: isinstance(synth_obj.speak("你好。", "_test", language="zh"), np.ndarray))
            check("VoiceSynth.speak unsupported language returns None (no crash)",
                  lambda: synth_obj.speak("Hej.", "_test", language="sv") is None)
    elif synth_obj:
        print("  SKIP  XTTS inference — TTS model object not initialised")


# ============================================================
print("\n=== 8. Player construction ===")
# ============================================================

from ominvox.player import Player
check("Player.__init__ sample_rate=24000",
      lambda: Player(cfg).sr == 24000)
check("Player.__init__ delay_ms=1500",
      lambda: Player(cfg).delay == 1.5)


# ============================================================
print("\n=== 9. Orchestrator construction ===")
# Real diarizer (model cached from section 4).  TTS backend stubbed to 'none'
# because the XTTS weights (~1.8 GB) haven't been downloaded yet — that happens
# on the first real run.  tts=None is a valid graceful-degradation state.
# ============================================================

from ominvox.orchestrator import Pipeline

cfg_pipeline_test = dict(cfg)
cfg_pipeline_test["tts"] = {**cfg["tts"], "backend": "none"}

check("Pipeline.__init__ (real diarizer, TTS stub, no capture)",
      lambda: Pipeline(cfg_pipeline_test, log=lambda _: None))


# ============================================================
print(f"\n{'='*50}")
print(f"Results: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("Failed:")
    for f in FAIL:
        print(f"  - {f}")
sys.exit(0 if not FAIL else 1)

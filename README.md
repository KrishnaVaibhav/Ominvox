# Ominvox

Live, **local** audio translation with **per-speaker voice matching**. Captures whatever is playing on your Windows PC (e.g. a movie), translates the dialogue live, and speaks it back — giving each on-screen voice its own cloned voice in the target language.

Everything (venv, model downloads, caches) stays inside this folder. Nothing is written to `C:`.

## Layout

```
D:\GitHub\Ominvox\
  ominvox\            pipeline package
    capture.py        WASAPI loopback (system audio)
    vad.py            Silero VAD gate
    diarize.py        pyannote speaker labels
    stt.py            faster-whisper speech-to-text
    mt.py             translation (whisper / NLLB)
    voices.py         per-speaker registry + XTTS cloning
    player.py         delay-buffered playback
    orchestrator.py   wires the stages together
    app.py            entry point
  config.yaml         all settings
  requirements.txt
  setup.bat           creates .venv + installs, caches pinned to .\.cache
  set_env.bat         pins caches for a shell
  run.bat             activate + run
```

## Setup (Windows, consumer GPU)

```bat
cd /d D:\GitHub\Ominvox
setup.bat
```

Edit the CUDA index-url in `setup.bat` to match your GPU driver. Put your Hugging Face token in `config.yaml` (`diarize.hf_token`) — the pyannote model is gated.

## Run

```bat
run.bat --check            REM dependency self-test, no models needed
run.bat --target es        REM translate to Spanish, clone each movie voice
```

Start playback, then play your movie. Translated, voice-matched audio comes out the default speaker after the configured delay buffer.

## Status

Phase 1–2 skeleton (cascaded pipeline, per-speaker cloning). Every stage degrades gracefully if its model/dep is absent, so `--check` and partial runs work before all heavy models are installed. See `Ominvox_Project_Plan.md` for the full roadmap, latency strategy, and risks.

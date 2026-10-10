# Ominvox — Project Plan

Live, local audio translation with per-speaker voice matching. Capture any audio playing on the device (e.g. a movie on a Windows PC), translate it live to a target language, and speak it back with a distinct cloned voice for each speaker in the source.

Target: **Windows first**, future scope **Android + Linux**. Hardware: **consumer GPU** (RTX-class, 8–24 GB VRAM). Voice: **match per speaker** (detect each voice, clone its timbre live).

---

## 1. What it has to do

The pipeline is real-time speech-to-speech translation with speaker preservation:

```
System audio (movie)
  → capture (WASAPI loopback)
  → VAD + speaker diarization (who is talking)
  → STT (source language → text)
  → MT (translate to target language)
  → TTS with per-speaker cloned voice
  → playback (mixed back, low latency)
```

Two viable architectural tracks:

**A. Cascaded (recommended for v1).** Separate STT → MT → TTS stages. More control, swappable models, easier to add languages and per-speaker voice cloning. Higher cumulative latency.

**B. End-to-end streaming S2ST.** Meta SeamlessStreaming does speech→speech directly and preserves vocal style/prosody. Lower latency, fewer moving parts, but harder to inject *arbitrary cloned* per-speaker voices and Windows/local packaging is rougher (official local support is Linux/Apple-silicon).

Plan: build **cascaded** for full control over per-speaker voice cloning; keep Seamless as a benchmark/fallback path.

---

## 2. Component choices (researched)

| Stage | Pick | Notes |
|---|---|---|
| Audio capture (Win) | **PyAudioWPatch** (WASAPI loopback) | Captures the system mix; loopback devices appear as virtual input devices. Microsoft's native loopback API underneath. |
| VAD | **Silero VAD** | Tiny, fast, gates the pipeline so it only runs on speech. |
| Diarization | **pyannote** (speaker-diarization-3.1, streaming) | ~6–8 GB VRAM, pure PyTorch; streaming mode gives timestamped speaker labels live (sub-150 ms in their API). Assigns each utterance to a speaker ID. |
| STT | **faster-whisper** (CTranslate2) + whisper-streaming policy | large-v3 runs many× real-time on a modern GPU; streaming wrapper gives ~2–3 s latency on long-form. Use small/medium for lower-end GPUs. Whisper also does source-language detection. |
| Translation | **Whisper translate** (quick path) or **NLLB / SeamlessM4T-v2 T2TT** (quality, many languages) | Whisper can translate-to-English cheaply; NLLB/Seamless for arbitrary target languages. |
| TTS + voice clone | **XTTS-v2** (primary) / **OpenVoice v2** (low-latency) / **F5-TTS** | XTTS clones from ~6 s reference, streaming first-chunk ~200 ms, multilingual. OpenVoice is lighter for weaker GPUs. |
| End-to-end alt | **SeamlessStreaming / SeamlessExpressive** | Benchmark + fallback; preserves prosody in streaming. |

Per-speaker voice: diarization gives a stable speaker ID → collect a few seconds of that speaker's clean source audio → build an XTTS speaker embedding → reuse it for every later line from that speaker. New speaker = new embedding on the fly.

---

## 3. Latency budget (the hard part)

Real-time means staying under ~2–3 s end-to-end or it feels broken against the picture. Strategy:

- Chunk audio ~1 s; run VAD-gated so silence costs nothing.
- Parallelize stages (capture → diarize/STT → MT → TTS) as a streaming queue, not blocking steps.
- Cache speaker embeddings (clone once per speaker, not per line).
- Add a small fixed delay buffer (like subtitle offset) to absorb jitter and keep lipsync-ish alignment.
- Use streaming variants everywhere (whisper-streaming, XTTS streaming endpoint).
- Quantized models (CTranslate2 int8, smaller XTTS) to fit consumer VRAM and go faster.

Accept that perfect lipsync is out of scope; goal is intelligible, voice-distinct, near-live dubbing.

---

## 4. Architecture

- **Capture service** — WASAPI loopback → ring buffer of PCM frames.
- **Orchestrator** — async pipeline (Python, asyncio). Frames → VAD → diarizer → per-speaker segment objects.
- **Speaker registry** — maps speaker ID → reference clip → cached TTS embedding.
- **STT worker(s)** — GPU, faster-whisper, returns text + source lang.
- **MT worker** — text → target language.
- **TTS worker(s)** — XTTS with the speaker's embedding → translated audio.
- **Mixer/player** — schedules clips on a delay-compensated timeline, optionally ducks original audio.
- **Model server** — keep models hot in VRAM (one process, queues) to avoid reload latency.
- **UI** — tray app: source/target language, voice mode (match / preset / single), delay slider, on/off.

Language: Python core (best model ecosystem). Wrap GPU models in a persistent worker process. UI via a lightweight desktop shell (PySide/Qt or Tauri/Electron front + Python backend over local socket).

---

## 5. Phased roadmap

**Phase 0 — Spike (1–2 wks).** Prove WASAPI loopback capture + faster-whisper transcription of live movie audio on the target GPU. Measure real-time factor.

**Phase 1 — Cascaded MVP, single voice (3–4 wks).** Capture → STT → MT → one XTTS voice → playback. No diarization yet. Validate end-to-end latency and quality on real movies.

**Phase 2 — Diarization + per-speaker voices (3–4 wks).** Add pyannote streaming, speaker registry, on-the-fly XTTS cloning per speaker. This is the headline feature.

**Phase 3 — Latency + quality hardening (3–4 wks).** Streaming STT/TTS, parallel workers, quantization, delay-buffer tuning, overlap-speech handling, original-audio ducking, language coverage (NLLB/Seamless).

**Phase 4 — Product shell (2–3 wks).** Tray UI, settings, model download/manager, presets, packaging/installer for Windows.

**Phase 5 — Portability (future).** Linux build (Seamless runs natively here). Android: on-device is hard on consumer phones — plan a lighter model set (OpenVoice/whisper-small) or optional local-network offload to a PC.

---

## 6. Hardware tiers

- **Min (8 GB VRAM):** whisper small/medium + OpenVoice, diarization may share GPU → expect higher latency, fewer simultaneous speakers.
- **Recommended (12–16 GB):** whisper large-v3 (int8) + XTTS-v2 + pyannote comfortably hot.
- **High (24 GB):** parallel STT/TTS workers, multiple concurrent cloned voices, larger MT.

---

## 7. Key risks

- **Music/SFX/overlapping dialogue** confuse VAD/diarization/STT. Movies are noisy — mitigate with source separation (e.g. a vocal-isolation stage) before STT.
- **Cumulative latency** of the cascade. Mitigate with streaming + buffer; consider Seamless end-to-end if cascade can't hit target.
- **Voice-clone quality from short, noisy refs.** Accumulate cleaner reference over time per speaker; fall back to preset voices when a clone is poor.
- **Cloning real actors' voices** raises consent/IP/deepfake concerns — keep it personal/local-use, add disclosure, no distribution of cloned outputs.
- **Android feasibility** for fully local — likely needs offload or heavily reduced models.

---

## 8. Immediate next steps

1. Confirm dev GPU (exact model + VRAM) to lock model sizes.
2. Build the Phase 0 spike: WASAPI loopback → faster-whisper, log real-time factor on a movie clip.
3. Prototype XTTS clone-and-speak from a 6 s sample to validate voice quality.
4. Decide source-separation (vocal isolation) need based on spike results.

---

## Environment / setup

All project files, virtual env, and model caches live under `D:\GitHub\Ominvox` — nothing on `C:`.

```
# from D:\GitHub\Ominvox
python -m venv D:\GitHub\Ominvox\.venv
D:\GitHub\Ominvox\.venv\Scripts\activate

# keep HF / torch model downloads off C:
set HF_HOME=D:\GitHub\Ominvox\.cache\huggingface
set TORCH_HOME=D:\GitHub\Ominvox\.cache\torch
set PIP_CACHE_DIR=D:\GitHub\Ominvox\.cache\pip
```

`.gitignore` excludes `.venv/`, `.cache/`, and downloaded model weights.

---

## Sources

- [faster-whisper real-time transcription (GoTranscript)](https://gotranscript.com/public/real-time-transcription-with-faster-whisper-3-live-demos)
- [Faster Whisper real-time (Cerebrium)](https://cerebrium.ai/blog/faster-whisper-transcription-how-to-maximize-performance-for-real-time-audio-to-text)
- [whisper_streaming (GitHub)](https://github.com/wonyx/whisper_streaming)
- [Self-host XTTS-2 / F5-TTS / OpenVoice V2 (Spheron)](https://www.spheron.network/blog/self-host-voice-cloning-gpu-cloud-xtts-f5-tts-openvoice-v2/)
- [Streaming real-time TTS with XTTS v2 (Baseten)](https://www.baseten.co/blog/streaming-real-time-text-to-speech-with-xtts-v2/)
- [Best open-source voice cloning 2026 (Resemble AI)](https://www.resemble.ai/resources/best-open-source-ai-voice-cloning-tools)
- [pyannote speaker-diarization-3.1 (Hugging Face)](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [pyannote-audio (GitHub)](https://github.com/pyannote/pyannote-audio)
- [PyAudioWPatch — WASAPI loopback (GitHub)](https://github.com/s0d3s/PyAudioWPatch)
- [WASAPI Loopback Recording (Microsoft Learn)](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)
- [Seamless streaming speech translation (Meta AI)](https://ai.meta.com/research/publications/seamless-multilingual-expressive-and-streaming-speech-translation/)
- [SeamlessM4T-v2-large (Hugging Face)](https://huggingface.co/facebook/seamless-m4t-v2-large)

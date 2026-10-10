# Ominvox

Live, **local** audio translation with **per-speaker voice matching**. Ominvox listens to whatever is playing on your Windows PC (a movie, a YouTube video, a call), translates the dialogue live, and speaks it back. Each speaker on screen gets their own cloned voice in the new language.

Everything runs on your own computer: no cloud service, no subscription. The program, its Python environment, and all downloaded AI models stay inside the project folder.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Download Ominvox](#2-download-ominvox)
3. [The uv installer tool (automatic)](#3-the-uv-installer-tool-automatic)
4. [Get a free Hugging Face token](#4-get-a-free-hugging-face-token)
5. [Create your .env file](#5-create-your-env-file)
6. [Run the setup](#6-run-the-setup)
7. [Start Ominvox](#7-start-ominvox)
8. [Avoid the echo problem (important)](#8-avoid-the-echo-problem-important)
   - [Sync the translation with your video](#sync-the-translation-with-your-video)
9. [Settings (config.yaml)](#9-settings-configyaml)
10. [Troubleshooting](#10-troubleshooting)
11. [For developers](#11-for-developers)

---

## 1. What you need

| Requirement | Details |
|---|---|
| **Windows 10 or 11** | Audio capture uses a Windows-only feature (WASAPI loopback). Mac and Linux are not supported. |
| **NVIDIA graphics card** | At least **8 GB of video memory** (for example an RTX 3070, 4060 Ti, 4070 or better). AMD and Intel graphics cards won't work. |
| **Up-to-date NVIDIA driver** | 2024 or newer. Download it from <https://www.nvidia.com/Download/index.aspx> or update through the NVIDIA app. |
| **About 20 GB free disk space** | For the Python environment and AI models. Use any drive; the D: drive works well. |
| **16 GB RAM** or more | 32 GB is recommended. |
| **Internet connection** | Only for the first setup and the first run, when models download. After that it works offline. |
| **Headphones** | Strongly recommended. See [section 8](#8-avoid-the-echo-problem-important). |

You do **not** need to install Python yourself. The setup downloads its own copy into the project folder.

**How to check your graphics card:** press `Ctrl + Shift + Esc` to open Task Manager, go to **Performance** and click **GPU**. The name (for example "NVIDIA GeForce RTX 4070") and **Dedicated GPU memory** are shown in the top right.

---

## 2. Download Ominvox

**Option A: no git, easiest**

1. Open <https://github.com/KrishnaVaibhav/Ominvox>.
2. Click the green **Code** button, then **Download ZIP**.
3. Right-click the downloaded ZIP and choose **Extract All...**.
4. Extract it to a short path **without spaces**, for example `D:\Ominvox`.

**Option B: with git**

```bat
cd /d D:\
git clone https://github.com/KrishnaVaibhav/Ominvox.git
```

From now on, "the project folder" means the folder that contains `README.md`, `config.yaml` and `run.bat`.

---

## 3. The uv installer tool (automatic)

Ominvox uses a small tool called **uv** to build its Python environment. **You don't need to do anything:** the setup in step 6 downloads it into the `.tools` folder by itself.

Only if your network blocks that download, add it by hand:

1. Open <https://github.com/astral-sh/uv/releases/latest>.
2. Under **Assets**, download **`uv-x86_64-pc-windows-msvc.zip`** and extract it.
3. In the project folder, create a folder named **`.tools`** (if Windows refuses a name starting with a dot, type `.tools.` and it saves as `.tools`).
4. Copy **`uv.exe`** into it, so you have `D:\Ominvox\.tools\uv.exe`.

---

## 4. Get a free Hugging Face token

Ominvox uses an AI model from Hugging Face to tell different speakers apart. The model is free, but you must accept its terms and use a personal access key (a "token").

1. **Create an account** at <https://huggingface.co/join> (free), and confirm your email.
2. **Accept the model terms.** While logged in, open each of these pages, fill in the short form and click **Agree and access repository**:
   - <https://huggingface.co/pyannote/speaker-diarization-3.1>
   - <https://huggingface.co/pyannote/segmentation-3.0>
3. **Create a token.**
   - Go to <https://huggingface.co/settings/tokens>.
   - Click **Create new token**.
   - Under **Token type** choose **Read**.
   - Give it any name (for example `ominvox`) and click **Create token**.
   - **Copy** the token. It starts with `hf_`. Keep it private, like a password.

---

## 5. Create your .env file

The `.env` file holds your private token on your computer only. It is never uploaded to GitHub.

1. In the project folder, find the file **`.env.example`**.
2. Make a copy of it (`Ctrl + C`, then `Ctrl + V`).
3. Rename the copy to exactly **`.env`**. Windows may warn about changing the extension; click **Yes**.
   - If Windows won't accept the name, type `.env.` (with a dot at the end) and it will save as `.env`.
   - If you can't see file extensions: in File Explorer click **View**, then **Show**, then turn on **File name extensions**.
4. Open `.env` with **Notepad** (right-click, then **Open with**, then **Notepad**).
5. Replace `hf_paste_your_token_here` with your real token so the line looks like:

   ```
   HF_TOKEN=hf_AbCdEf1234567890...
   ```

6. Save and close.

That's the only file you need to create. You **don't** need to put the token anywhere else.

---

## 6. Run the setup

This step downloads Python, the AI libraries, and GPU support. It takes **10–30 minutes** depending on your internet speed, and you only do it once.

1. Open the project folder in File Explorer.
2. Click the address bar at the top, type `powershell` and press **Enter**. A blue or black window opens, already in the right folder.
3. Copy this line, paste it into the window (right-click pastes) and press **Enter**:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup_uv.ps1
   ```

4. Wait. Lots of text will scroll by; this is normal. When it finishes you should see:

   ```
   ===== SETUP COMPLETE (self-test exit code: 0) =====
   ```

   The self-test should show `ok` next to every package and `torch.cuda.is_available: True`.

   At the end, setup also builds **`Ominvox.exe`** in the project folder and puts an **Ominvox shortcut on your desktop**.

If it ends with a red error instead, see [Troubleshooting](#10-troubleshooting).

**Alternative:** if you already use Anaconda or Miniconda, you can run `setup_conda.bat` instead of steps 3 and 4 above. It builds the same environment.

---

## 7. Start Ominvox

### Open the app

Double-click the **Ominvox** shortcut on your desktop (or `Ominvox.exe` in the project folder). Ominvox opens in its own window.

- If setup hasn't been run yet, `Ominvox.exe` offers to run it for you.
- If your Hugging Face token is missing, it offers to open the token page and your `.env` file.
- Prefer a browser tab? Double-click `start_ui.bat` instead (it opens <http://127.0.0.1:8765>).
- If something goes wrong at start-up, the error and the log file location (`logs\ominvox.log`) are shown.

The window has three columns.

### Left: Audio, language and sync

| Control | What it does |
|---|---|
| **Input** | Where the sound to translate comes from. Under *Computer sound* pick the speakers or headphones **your movie plays on**; under *Microphones* pick a mic to translate a live speaker. *Automatic* uses your default speakers. |
| **Check input** | Listens to the chosen input for 10 seconds **without loading the AI models**. Play something: the level bar turns green if sound is arriving. |
| **Output** | Where you hear the translation. |
| **Test sound** | Plays a short beep on the chosen output. |
| **↻ Refresh** | Re-scans devices after you plug something in. |
| Yellow warning | Appears when input and output are the same device. See [section 8](#8-avoid-the-echo-problem-important). |
| **Movie language / Translate into / Voice** | Change any time, even while listening. |
| **Video sync** | *Fastest* or *Fixed lag*. See [Sync the translation with your video](#sync-the-translation-with-your-video). |

Every choice is saved and restored the next time you open Ominvox. Devices are remembered by name, so plugging hardware in or out doesn't mix them up.

### Middle: the transcript

Press **Start Listening**, then play your movie.

- **First start:** the AI models load and warm up. This takes 15–60 seconds, plus a one-time download of about 5 GB the very first time.
- Each line shows **who spoke** on the left and the **translation** on the right.
- Every translation is tagged with its delay, for example `voice +5.6 s`. Hover over the tag to see where the time went.

### Right: Performance and Speakers

**Performance** shows the live numbers:

| Item | Meaning |
|---|---|
| **Translation lag** | How long after the original line **starts** the translated voice starts. Green under 3 s, yellow under 5 s, orange under 8 s, red above. The header shows the same number. |
| **Average / 95% of lines / Range** | Over the last 30 lines. |
| **Lag chart** | Blue = when each line was actually spoken. Orange = when it was ready, the fastest possible. Dashed = your fixed lag, in Fixed mode. |
| **Where the lag comes from** | The last line's lag, split into its parts. These always add up to the lag: the person speaking (whole sentences are translated), the end-of-sentence pause (about 1 s of silence), waiting for the GPU, speaker ID, speech-to-text, translation, voice, and playback wait. |
| **Speed (real-time factor)** | Processing time ÷ length of speech. **Below 1.0 the app keeps up**; above 1.0 it falls behind. |
| **Response time** | From the end of a sentence to its translation being ready. |
| **Playback backlog / queue** | Translated audio still waiting to play, and lines waiting for the GPU. Growing numbers mean it can't keep up. |
| **Lines** | Translated, spoken, late (Fixed mode), dropped and errors. |
| **System** | GPU load, GPU memory, GPU temperature, CPU and memory, and the devices in use. |

**Speakers** lists the detected voices:
- **Rename** a speaker (for example "Unknown 2" to "Captain"). Names are remembered, so the same voice gets the same name next time.
- If one person shows up twice, rename the second entry to the **same name** as the first to merge them.
- **Forget all** (click twice to confirm) clears every saved speaker. Use it when you switch to a different movie.

To stop, click **Stop**. To quit, close the window.

**Voice modes:**
- **Match each speaker (clone):** each speaker gets a voice that imitates them. Cloning starts after about 6 seconds of their speech; until then their lines use a built-in voice, chosen per speaker so people still sound different.
- **Preset voice:** one voice cloned from a `.wav` file you choose (`tts: preset_voice` in `config.yaml`).
- **One voice for everyone:** one built-in voice.

> **Languages:** you can switch the target language at any time, even while listening.
> - **English** uses Whisper's built-in translation (fastest).
> - **Any other language** uses the NLLB translator. The first time you pick one, about 2.5 GB downloads. After that it loads in a few seconds.
> - The voice can speak English, Spanish, French, German, Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Arabic, Chinese, Hungarian, Korean, Japanese and Hindi. Other languages (such as Swedish) show the translated **text only**.

### Helper scripts (double-click)

| File | What it does |
|---|---|
| `Ominvox.exe` | Opens the app in its own window (the normal way to use Ominvox). |
| `start_ui.bat` | Opens the same interface in your web browser instead. |
| `build_exe.bat` | Rebuilds `Ominvox.exe` (setup already does this). |
| `audiotest.bat` | Play something, then run this. It records 15 seconds and shows whether sound is being captured. Results are saved to `audiotest_output.txt`. |
| `devices.bat` | Lists all your audio devices with their numbers, saved to `devices_output.txt`. Useful for `config.yaml`. |
| `check.bat` | Runs the self-test, saved to `check_output.txt`. |
| `verify.bat` | Checks that the program files load correctly, saved to `verify_output.txt`. |

### Command line (optional)

Open a terminal in the project folder and run:

```bat
run.bat --window             REM app window (what Ominvox.exe runs)
run.bat --ui                 REM web interface in the browser (same as start_ui.bat)
run.bat --check              REM self-test
run.bat --list-devices       REM show audio devices
run.bat --audio-test         REM check that sound is being captured
run.bat --target es          REM run without the UI, translating to Spanish
run.bat --ui --port 9000     REM use a different port for the web page
```

---

## 8. Avoid the echo problem (important)

Ominvox records **whatever your output device plays**. If the translated voice plays on the **same** speakers it is recording, it hears itself and translates its own voice again, in a loop.

Pick one of these fixes:

**Fix 1: two different devices (simplest).** Play the movie through one device and send the translation to another. For example, the movie plays on your monitor or laptop speakers, and the **Output Source** in Settings is your headphones.

**Fix 2: a virtual audio cable (best for one pair of headphones).**
1. Download and install **VB-CABLE** (free) from <https://vb-audio.com/Cable/>, then restart your PC.
2. In your movie player, or in Windows **Settings > System > Sound > Volume mixer**, set the movie app's output to **CABLE Input**.
3. In Ominvox, set the **Input Source** to the **CABLE** loopback and the **Output Source** to your headphones.

You'll then hear only the translation in your headphones, with no echo.

### Sync the translation with your video

Translation can't start until a sentence is finished, so the translated voice always comes a few seconds after the original. You can't remove that delay, but you can **make it constant and shift the video to match**:

1. Start listening and play the movie for about a minute. In the **Video sync** box, choose **Fixed lag**.
2. Click **Use X.X s**. This is a lag that about 95% of lines can make, based on live measurements. Every line is now spoken exactly that long after the original. Lines that miss it are marked *late* and counted in **Lines**.
3. The box shows the value to enter in your video player, for example **−7.000 s (−7000 ms)**. Set your player's **audio delay** to that value:
   - **VLC:** Tools → Track Synchronization → *Audio track synchronization*. You can also press **J** / **K** to move it in 50 ms steps.
   - **MPC-HC / MPC-BE:** Options → Internal Filters → Audio Switcher → enable *Time shift* and enter the milliseconds.

The player now sends the movie's sound early, Ominvox translates it, and the translated voice arrives in step with the picture. This works best with Fix 2 above (a virtual cable), so you hear only the translation.

**Keeping the lag low:**
- Lag is mostly **sentence length** plus about 1 s of pause detection. "Where the lag comes from" shows this.
- A smaller `stt: model` (for example `small`) speeds up speech-to-text.
- English output is fastest, because it skips the separate translator.
- Lower `vad: silence_chunks` in `config.yaml` (default 4 × 0.25 s) to detect sentence ends sooner, at the cost of splitting sentences more often.

---

## 9. Settings (config.yaml)

Most things can be changed in the web interface. For anything else, open **`config.yaml`** in Notepad, edit it, save, and restart Ominvox. Lines starting with `#` are comments.

| Setting | What it does | Typical values |
|---|---|---|
| `translate: target_lang` | Language to translate into | `en`, `es`, `fr`, `de`, `hi`, `ja`, ... |
| `translate: source_lang` | Language of the movie | `auto` (detect), or a code like `ja` |
| `stt: model` | Speech-recognition size. Bigger is more accurate but slower and uses more video memory. | `small`, `medium` (default), `large-v3` |
| `stt: device` | Use the graphics card or the processor | `cuda` (GPU, default), `cpu` (very slow) |
| `diarize: enabled` | Tell different speakers apart | `true` / `false` |
| `mt: backend` | Translation engine. `auto` uses Whisper for English and NLLB for everything else. `whisper` gives English only; `nllb` always uses NLLB. | `auto` (default), `whisper`, `nllb` |
| `tts: voice_mode` | Voice style | `match`, `preset`, `single` |
| `tts: preset_voice` | Path to a `.wav` voice sample (10–30 s of clear speech) for preset mode | `D:\voices\me.wav` |
| `tts: fallback_voice` | Built-in voice for single mode | `Claribel Dervla`, `Damien Black`, `Ana Florence`, `Andrew Chipper` |
| `speaker_id: threshold` | How similar two lines must sound to count as the same person. Raise it if different people get merged; lower it if one person gets split. | `0.62` (default), `0.55`–`0.75` |
| `speaker_id: min_seconds` | Lines with less speech than this (like "No.") are given to the closest known speaker instead of creating a new one | `1.6` |
| `playback: sync_mode` | `asap` speaks each line as soon as it's ready; `fixed` keeps a constant lag for syncing with the video | `asap` (default), `fixed` |
| `playback: fixed_lag_ms` | The constant lag in `fixed` mode | `4000`–`10000` |
| `playback: delay_ms` | Extra wait in `asap` mode | `0` (default) |
| `audio: input_device_index` | Fixed capture device number (from `devices.bat`). `null` means automatic. | `null`, `26` |
| `playback: output_device_index` | Fixed playback device number. `null` means default. | `null`, `19` |

Choices made in the app are saved to **`user_settings.json`** and override `config.yaml`. Delete that file to go back to the `config.yaml` values.

**Leave `diarize: hf_token` empty.** The token belongs in `.env` (see [section 5](#5-create-your-env-file)).

**Low on video memory (6 GB card)?** Set `stt: model: "small"`, or set `diarize: enabled: false`.

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| "Could not get uv.exe" during setup | Your network blocked the download. Add it by hand as described in [step 3](#3-the-uv-installer-tool-automatic). |
| "Ominvox is not installed yet" | Run the setup in [step 6](#6-run-the-setup) first. |
| "running scripts is disabled on this system" | Use the full command from step 6, including `-ExecutionPolicy Bypass`. |
| `torch.cuda.is_available: False` | Update your NVIDIA driver, restart, and run the setup again. If you use a laptop, plug it in and check that the NVIDIA GPU isn't disabled. |
| Error mentioning `401`, `gated`, `pyannote` or "access" | Check that `.env` exists, is named exactly `.env` (not `.env.txt`), and contains `HF_TOKEN=hf_...`. Also check that you accepted **both** model pages in [step 4](#4-get-a-free-hugging-face-token). |
| Level bar stays grey or `audiotest` says SILENCE | Pick a different **Input Source**: the one matching the device your movie actually plays on. Make sure the movie isn't muted. |
| `Invalid number of channels` | Choose a different input device in the dropdown, or set `input_device_index` in `config.yaml` using a number from `devices.bat`. |
| Translation repeats itself in a loop | That's the echo problem; see [section 8](#8-avoid-the-echo-problem-important). |
| Output is English even though another language was chosen | Make sure `mt: backend` in `config.yaml` is `auto` (not `whisper`). |
| Message "Speaker separation is OFF" | Your Hugging Face token is missing or the model terms weren't accepted. Everything else still works, but everyone shares one voice. Redo [steps 4–5](#4-get-a-free-hugging-face-token). |
| One person appears as several "Unknown" speakers | Rename the extra entries to the same name to merge them, or lower `speaker_id: threshold` slightly. |
| "Audio input failed" / "Audio output failed" | The chosen device is unplugged or in use. Pick another one, or choose Automatic. Click **↻ Refresh** after plugging devices in. |
| The lag is high | Open **Where the lag comes from**. If *Person speaking* is the biggest part, that's sentence length and can't be avoided (use Fixed lag to sync instead). If *Speech-to-text* or *Voice* is large, or Speed is above 1.0, use a smaller `stt: model` or close other GPU programs. |
| Many lines marked *late* in Fixed lag mode | Click **Use X.X s** again, or raise the lag by 0.5–1 s. |
| Nothing happens when opening `Ominvox.exe` | Look at `logs\ominvox.log` in the project folder. `Ominvox.exe` must stay in the project folder. |
| "Port 8765 in use" | Ominvox automatically tries ports 8765–8784. Read the black window to see which port it chose, or close the other Ominvox window. |
| Out of memory / CUDA OOM | Use a smaller `stt: model` (`small`), or close games and other GPU-heavy apps. |
| Web page shows old behaviour after an update | Close the black window and start `start_ui.bat` again. |

**Starting over cleanly:** delete the `.venv312` folder and run step 6 again. To force models to download again, also delete `.cache`. Don't delete `.cache\speakers` if you want to keep your saved speaker voices (use **Forget all** in the app to clear them instead).

---

## 11. For developers

### Pipeline

```
capture (WASAPI loopback / mic) -> Silero VAD -> pyannote diarization + speaker-id
  -> faster-whisper STT -> MT (auto: whisper->en | NLLB) -> XTTS-v2 per-speaker clone
  -> delay-buffered playback
```

### Layout

```
ominvox\              pipeline package
  capture.py          WASAPI loopback / mic capture, device enumeration
  vad.py              Silero VAD gate
  diarize.py          pyannote speaker labels + embeddings
  speaker_id.py       persistent voice profiles (cosine matching)
  stt.py              faster-whisper speech-to-text
  mt.py               translation (whisper / NLLB)
  voices.py           per-speaker registry + XTTS cloning
  player.py           delay-buffered playback
  orchestrator.py     wires the stages together
  ui.py               FastAPI web UI (embedded HTML/JS)
  config.py           loads config.yaml + user_settings.json + .env, pins caches
  metrics.py          per-line latency breakdown, rolling stats, GPU/CPU stats
  web/index.html      the interface (served by ui.py; no build step)
  app.py              CLI entry point (--ui, --window, --check, ...)
launcher/             Ominvox.exe source (stdlib only) + icon generator
build_exe.bat         builds Ominvox.exe with PyInstaller (requirements-build.txt)
config.yaml           all settings
.env.example          template for .env (HF_TOKEN)
requirements.txt      Python deps (torch installed separately, CUDA build)
setup_uv.ps1          recommended setup -> .venv312 (Python 3.12 via portable uv)
setup_conda.bat       alternative setup via conda -> .venv312
setup.bat             legacy (system Python -> .venv); run.bat does not use it
run.bat               runs .venv312 with caches pinned
test_*.py             tests (see below)
```

### Notes

- **Python 3.12 is required.** coqui-tts doesn't support 3.13.
- torch/torchaudio are installed **last** from the CUDA 12.4 index (`cu124`) so that coqui-tts can't replace them with a CPU build. Edit the index URL in `setup_uv.ps1` if your driver needs a different CUDA build.
- `transformers` is pinned `<5` because coqui-tts 0.27.x imports a symbol removed in 5.x.
- All HF, torch and TTS caches are pinned to `.cache\` by `config.py` and the `.bat` launchers. Nothing is written to `C:`.
- `config.py` reads `.env` into `os.environ` without overriding variables that are already set. `diarize.py` uses `diarize.hf_token` if set, otherwise `HF_TOKEN`. Without a working token the diarizer is disabled and the app keeps running with one speaker.
- **Speaker identity comes from the voice embedding, not the pyannote label.** Each utterance is diarized on its own, so its dominant label is nearly always `SPEAKER_00`; `VoiceProfileStore.resolve()` matches the WeSpeaker embedding against profile centroids instead. Clips with less than `speaker_id.min_seconds` of voiced audio (`orchestrator.voiced_seconds`) are matched but never enrolled (their embeddings are unreliable).
- Capture uses PortAudio **callback** mode: a WASAPI loopback delivers no data while nothing plays, so a blocking `read()` would hang. `chunks()` yields `None` when no audio arrives, which the segmenter treats as silence.
- Target/source language and voice mode are read live from the shared config dict, so UI changes apply without rebuilding the pipeline.
- **Latency:** capture chunks carry monotonic timestamps; each line records speech start/end, queue, per-stage and playback times (`metrics.py`). `lag = play_t - seg_start`, and the eight parts in `metrics.STAGES` sum to it exactly. In `fixed` sync mode the player schedules each clip at `seg_start + fixed_lag`.
- Device lists are **WASAPI only**: one entry per device with full names, and the same API loopback uses. WASAPI shared mode only accepts the device's native rate and channels, so the player resamples the 24 kHz TTS audio (`scipy.signal.resample_poly`).
- Models are warmed up once after loading (`Pipeline._warmup`), so the first line isn't slower than the rest.
- `Ominvox.exe` is a stdlib-only launcher (about 9 MB). It runs `.venv312\Scripts\pythonw.exe -m ominvox.app --window`, which shows the UI in an Edge WebView2 window via pywebview. A second launch reuses a running instance (`/api/health`) so the models are never loaded twice.
- Every stage degrades gracefully if its model or dependency is missing, so `--check` and partial runs work before all models are installed.
- See `Ominvox_Project_Plan.md` for the roadmap, latency strategy and risks.

### Tests

```bat
REM unit / synthetic (no sound)
.venv312\Scripts\python.exe test_metrics.py
.venv312\Scripts\python.exe test_pipeline.py
.venv312\Scripts\python.exe test_speaker_id.py
.venv312\Scripts\python.exe test_e2e.py
.venv312\Scripts\python.exe test_comprehensive.py
REM real speech generated with XTTS, full chain without audio devices
.venv312\Scripts\python.exe test_real_voices.py
REM these PLAY SOUND on your default speaker
.venv312\Scripts\python.exe test_audio_devices.py
.venv312\Scripts\python.exe test_live_ui.py
REM ...or on chosen devices (part of the name), e.g. to keep it out of headphones:
set OMINVOX_TEST_DEVICE=LG ULTRAGEAR
set OMINVOX_TEST_OUTPUT=Realtek
```

### Licenses

The XTTS-v2 voice model is released under the **Coqui Public Model License** (non-commercial use). `run.bat` sets `COQUI_TOS_AGREED=1`, which means you accept that license. The pyannote models are subject to their own terms on Hugging Face.

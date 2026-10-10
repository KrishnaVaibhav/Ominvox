# Ominvox

Live, **local** audio translation with **per-speaker voice matching**. Ominvox listens to whatever is playing on your Windows PC (a movie, a YouTube video, a call), translates the dialogue live, and speaks it back. Each speaker on screen gets their own cloned voice in the new language.

Everything runs on your own computer: no cloud service, no subscription. The program, its Python environment and all AI models stay inside the folder you install it to.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Install](#2-install)
3. [First start: the setup screen](#3-first-start-the-setup-screen)
4. [Using Ominvox](#4-using-ominvox)
5. [Avoid the echo problem (important)](#5-avoid-the-echo-problem-important)
   - [Sync the translation with your video](#sync-the-translation-with-your-video)
6. [Settings (config.yaml)](#6-settings-configyaml)
7. [Troubleshooting](#7-troubleshooting)
8. [Updating and uninstalling](#8-updating-and-uninstalling)
9. [For developers](#9-for-developers)

---

## 1. What you need

| Requirement | Details |
|---|---|
| **Windows 10 or 11** | Audio capture uses a Windows-only feature (WASAPI loopback). Mac and Linux are not supported. |
| **NVIDIA graphics card** | At least **8 GB of video memory** (for example an RTX 3070, 4060 Ti, 4070 or better). AMD and Intel graphics cards won't work. |
| **Up-to-date NVIDIA driver** | The setup screen checks this and links to the download if needed. |
| **About 20 GB free disk space** | For Python, the AI libraries and the models. The installer picks the drive with the most free space. |
| **16 GB RAM** or more | 32 GB is recommended. |
| **Internet connection** | Only while installing and downloading the models. After that it works offline. |
| **Headphones** | Strongly recommended. See [section 5](#5-avoid-the-echo-problem-important). |

You do **not** need to install Python or anything else yourself.

---

## 2. Install

1. Download **`OminvoxSetup.exe`** (from the project's **Releases** page, or build it yourself with `scripts\build_exe.bat`; see [section 9](#9-for-developers)).
2. Double-click it. If Windows SmartScreen says "Windows protected your PC", click **More info → Run anyway**. The app isn't code-signed.
3. Check the install folder (the drive with the most free space is pre-selected) and click **Install**.
4. Wait 10–30 minutes while it downloads Python and the AI libraries. A progress bar shows each step, and you can keep using your PC.
5. Click **Open Ominvox**. Shortcuts are also added to your **Desktop** and **Start menu**.

Nothing is installed outside that folder, apart from the two shortcuts.

<details>
<summary><b>Manual install (without the installer)</b></summary>

1. On <https://github.com/KrishnaVaibhav/Ominvox>, click **Code → Download ZIP**, then extract it to a folder **without spaces** (for example `D:\Ominvox`).
2. In that folder, click the address bar, type `powershell` and press **Enter**.
3. Run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

   This downloads the same things as the installer, then builds `Ominvox.exe` and adds a desktop shortcut.
4. If your network blocks the download of the `uv` tool, get `uv-x86_64-pc-windows-msvc.zip` from <https://github.com/astral-sh/uv/releases/latest> and put `uv.exe` in a folder named `.tools` inside the Ominvox folder.

Already use Anaconda? `scripts\setup_conda.bat` builds the same environment with conda.
</details>

---

## 3. First start: the setup screen

The first time Ominvox opens, it walks you through four short steps. You can reopen it any time with the **Setup** button at the top.

1. **Check your PC.** Confirms the NVIDIA graphics card and driver, disk space and audio devices. If something's wrong, it says what to do, with a **Get driver** button where relevant.
2. **Voice licence.** The voice model (XTTS-v2) is free for **non-commercial use only** (Coqui Public Model License). Click **I agree** to turn voices on. If you choose **Not now**, translations are shown as text only.
3. **Speaker separation (optional).** Lets Ominvox tell voices apart so every character keeps their own voice. It needs a free Hugging Face account:
   1. Create an account at **huggingface.co/join**.
   2. While logged in, open the two model pages shown and click **Agree and access repository** on each.
   3. Create a token of type **Read** at **huggingface.co/settings/tokens**, paste it into the box and click **Check & save**.

   The screen confirms your account and both model pages with green ticks. The token is stored only on your PC (in the `.env` file). Skip this step and everyone shares one voice; you can add it later.
4. **Download models.** Shows each model with its size and a progress bar, plus speed and time left. The total is about 3.5 GB. Tick *Also get the translator* if you want output in languages other than English (+2.5 GB).

Click **Finish**. You're ready.

---

## 4. Using Ominvox

Open Ominvox from the desktop or Start menu shortcut. It opens in its own window. If you prefer a browser tab, double-click `start_ui.bat` instead (it opens <http://127.0.0.1:8765>).

The window has three columns.

### Left: Audio, language and sync

| Control | What it does |
|---|---|
| **Input** | Where the sound to translate comes from. Under *Computer sound* pick the speakers or headphones **your movie plays on**; under *Microphones* pick a mic to translate a live speaker. *Automatic* uses your default speakers. |
| **Check input** | Listens to the chosen input for 10 seconds **without loading the AI models**. Play something: the level bar turns green if sound is arriving. |
| **Output** | Where you hear the translation. |
| **Test sound** | Plays a short beep on the chosen output. |
| **↻ Refresh** | Re-scans devices after you plug something in. |
| Yellow warning | Appears when input and output are the same device. See [section 5](#5-avoid-the-echo-problem-important). |
| **Movie language / Translate into / Voice** | Change any time, even while listening. |
| **Video sync** | *Fastest* or *Fixed lag*. See [Sync the translation with your video](#sync-the-translation-with-your-video). |

Every choice is saved and restored the next time you open Ominvox. Devices are remembered by name, so plugging hardware in or out doesn't mix them up.

### Middle: the transcript

Press **Start Listening**, then play your movie.

- The models load and warm up in about 15–30 seconds; after that, Stop and Start are instant.
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
> - **Any other language** uses the NLLB translator (download it in **Setup**). It loads within a few seconds of switching.
> - The voice can speak English, Spanish, French, German, Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Arabic, Chinese, Hungarian, Korean, Japanese and Hindi. Other languages (such as Swedish) show the translated **text only**.

### Files in the Ominvox folder

| File | What it does |
|---|---|
| `Ominvox.exe` | Opens the app in its own window (the normal way to use Ominvox). |
| `start_ui.bat` | Opens the same interface in your web browser instead. |
| `scripts\audiotest.bat` | Play something, then run this: it listens for 15 seconds and shows whether sound is being captured. |
| `scripts\devices.bat` | Lists all your audio devices with their numbers (for `config.yaml`). |
| `scripts\check.bat` | Self-test: are the libraries installed and is the GPU usable? |
| `config.yaml` | All settings (see [section 6](#6-settings-configyaml)). |
| `logs\` | `ominvox.log` (app) and `setup.log` (installer). Useful when something goes wrong. |

### Command line (optional)

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

## 5. Avoid the echo problem (important)

Ominvox records **whatever your output device plays**. If the translated voice plays on the **same** speakers it is recording, it hears itself and translates its own voice again, in a loop.

Pick one of these fixes:

**Fix 1: two different devices (simplest).** Play the movie through one device and send the translation to another. For example, the movie plays on your monitor or laptop speakers, and **Output** is your headphones.

**Fix 2: a virtual audio cable (best for one pair of headphones).**
1. Download and install **VB-CABLE** (free) from <https://vb-audio.com/Cable/>, then restart your PC.
2. In your movie player, or in Windows **Settings > System > Sound > Volume mixer**, set the movie app's output to **CABLE Input**.
3. In Ominvox, set **Input** to **CABLE Input** (under *Computer sound*) and **Output** to your headphones.

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

## 6. Settings (config.yaml)

Most things can be changed in the app. For anything else, open **`config.yaml`** in Notepad, edit it, save, and restart Ominvox. Lines starting with `#` are comments.

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
| `audio: input_device_index` | Fixed capture device number (from `scripts\devices.bat`). `null` means automatic. | `null`, `26` |
| `playback: output_device_index` | Fixed playback device number. `null` means default. | `null`, `19` |

Choices made in the app (devices, languages, sync, licence, setup) are saved to **`user_settings.json`** and override `config.yaml`. Delete that file to go back to the `config.yaml` values, including showing the setup screen again.

The Hugging Face token lives in **`.env`** (`HF_TOKEN=hf_...`). The setup screen writes it for you; you can also edit it by hand, using `.env.example` as a template.

**Low on video memory (6 GB card)?** Set `stt: model: "small"`, or set `diarize: enabled: false`.

---

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| Installer stops with an error | Click **Try again**. The full output is in `logs\setup.log` inside the install folder. Most failures are a dropped internet connection. |
| "Could not get uv.exe" | Your network blocked a download. See *Manual install*, step 4, in [section 2](#2-install). |
| Setup screen: graphics card ✕ | Install the latest NVIDIA driver (**Get driver**), restart, then click **Check again**. On a laptop, plug it in and make sure the NVIDIA GPU isn't disabled. |
| Token: "pages marked ✕ haven't been accepted" | Open each ✕ page while logged in, click **Agree and access repository**, then **Check & save** again. |
| A model download fails | Check your internet connection and click **Download** again; it resumes where it stopped. |
| **Start** opens the setup screen | Something it needs isn't downloaded yet. Finish the **Download models** step. |
| Level bar stays grey or `audiotest` says SILENCE | Pick a different **Input**: the one matching the device your movie actually plays on. Make sure the movie isn't muted. |
| `Invalid number of channels` | Choose a different input device, or set `input_device_index` in `config.yaml` using a number from `scripts\devices.bat`. |
| Translation repeats itself in a loop | That's the echo problem; see [section 5](#5-avoid-the-echo-problem-important). |
| Output is English even though another language was chosen | Make sure `mt: backend` in `config.yaml` is `auto` (not `whisper`), and that the translator is downloaded (**Setup → Download models**). |
| Message "Speaker separation is OFF" | Add the Hugging Face token in **Setup** (step 3). Everything else works meanwhile; everyone just shares one voice. |
| Message "Voice is OFF" | Agree to the voice licence in **Setup** (step 2). |
| One person appears as several "Unknown" speakers | Rename the extra entries to the same name to merge them, or lower `speaker_id: threshold` slightly. |
| "Audio input failed" / "Audio output failed" | The chosen device is unplugged or in use. Pick another one, or choose Automatic. Click **↻ Refresh** after plugging devices in. |
| The lag is high | Open **Where the lag comes from**. If *Person speaking* is the biggest part, that's sentence length and can't be avoided (use Fixed lag to sync instead). If *Speech-to-text* or *Voice* is large, or Speed is above 1.0, use a smaller `stt: model` or close other GPU programs. |
| Many lines marked *late* in Fixed lag mode | Click **Use X.X s** again, or raise the lag by 0.5–1 s. |
| Nothing happens when opening `Ominvox.exe` | Look at `logs\ominvox.log` in the Ominvox folder. `Ominvox.exe` must stay in that folder. |
| Out of memory / CUDA OOM | Use a smaller `stt: model` (`small`), or close games and other GPU-heavy apps. |

---

## 8. Updating and uninstalling

**Update:** run a newer `OminvoxSetup.exe` and choose the same folder. It replaces the program files and keeps your settings, token, speakers, models and Python environment.

**Uninstall:** delete the Ominvox folder, plus the **Ominvox** shortcuts on your Desktop and in the Start menu. Nothing else was installed.

---

## 9. For developers

### Pipeline

```
capture (WASAPI loopback / mic) -> Silero VAD -> utterance
  GPU worker:  text stage   speaker embedding (WeSpeaker) -> speaker ID
                            -> faster-whisper STT -> translation (auto: Whisper->en | NLLB)
               voice stage  XTTS-v2 (per-speaker clone or built-in voice)
  player:      asap or fixed-lag schedule, resampled to the output device
```

### Layout

```
ominvox\
  app.py                 CLI entry point (--window, --ui, --check, --list-devices, ...)
  config.py              config.yaml + user_settings.json + .env; pins every cache to .cache\
  audio\
    devices.py           WASAPI device lists, PortAudio init/teardown lock
    capture.py           loopback / mic capture (timestamped chunks)
    player.py            playback, asap / fixed-lag scheduling, resampling
  pipeline\
    orchestrator.py      segmenting, GPU worker (text stage + voice stage), warm-up, stats
    vad.py  diarize.py  speaker_id.py  stt.py  mt.py  voices.py
    metrics.py           per-line lag breakdown, rolling stats, GPU/CPU stats
  firstrun\
    checks.py            GPU / driver / disk / audio checks
    hf_token.py          verify + save the Hugging Face token
    models.py            model registry, presence checks, downloads with progress
  ui\
    server.py            FastAPI + WebSocket server (pipeline lifecycle, devices, settings)
    onboarding.py        first-run screen backend (fr_* messages)
    window.py            native window (pywebview / Edge WebView2)
    web\                 index.html, app.css, app.js, setup.js (no build step)
installer\
  launcher.py            Ominvox.exe (stdlib only)
  installer.py           OminvoxSetup.exe (tkinter; embeds the app as payload.zip)
  build_payload.py       packs the app files for the installer
  make_icon.py           draws assets\ominvox.ico
scripts\                 build_exe.bat, audiotest/devices/check.bat, setup_conda.bat
tests\                   test suites + run_all.py
docs\                    project plan, history
setup.ps1                environment setup (used by the installer and manual installs)
run.bat / start_ui.bat   launchers with caches pinned
```

### Building the programs

```bat
scripts\build_exe.bat            REM Ominvox.exe + dist\OminvoxSetup.exe
scripts\build_exe.bat launcher   REM only Ominvox.exe
```

`OminvoxSetup.exe` embeds every **committed** file except `tests\`, `docs\` and `installer\`, plus the freshly built `Ominvox.exe`, so commit before building a release. For scripted installs: `OminvoxSetup.exe --silent --dir D:\Ominvox [--no-shortcuts]` (progress in `logs\install.log`).

### Notes

- **Python 3.12 is required** (coqui-tts doesn't support 3.13).
- `setup.ps1` installs the libraries, then **reinstalls PyTorch 2.6 + CUDA 12.4 last**, so nothing can replace it with a CPU build. pyannote.audio 4 *declares* `torch>=2.8`, but runs correctly on 2.6, and 2.6/cu124 works with older drivers. Every test passes on this combination.
- `transformers` is pinned `<5` (coqui-tts 0.27 imports a symbol removed in 5.x). NLLB loads with `use_safetensors=False`, which avoids a second 2.4 GB auto-converted copy.
- **Models are downloaded by the first-run screen** (`firstrun/models.py`), not by setup. Progress is measured from bytes on disk in each model's cache folder, so it works the same for Hugging Face, Coqui and torch.hub. Hugging Face calls get `cache_dir` explicitly, because huggingface_hub fixes its default cache path at import time.
- **Voice licence:** XTTS loads only after the user agrees (`tts.license_accepted`, which then sets `COQUI_TOS_AGREED`). Without it the app runs text-only.
- **Speaker identity comes from the voice embedding**, not pyannote's label (each utterance is diarized alone, so the label is almost always `SPEAKER_00`). The full diarization pass only runs as a fallback when no embedding is available. Clips with less than `speaker_id.min_seconds` of voiced audio are matched but never enrolled.
- **One GPU worker, models loaded one after another, on purpose.** On an 8 GB card, a second worker (text and voice in parallel) and parallel model loading each cost about 0.6 GB more VRAM (per-thread CUDA workspaces). That pushed the card into shared memory, and voice synthesis went from about 1.0 s to 3.6 s per line. See the note in `orchestrator.py`.
- **Capture** uses blocking-mode streams but only reads frames that are already available. Callback mode fails (-9999) when this process also plays to the device, and a plain blocking `read()` would hang on a silent loopback. `chunks()` yields `None` when nothing arrives, and the segmenter treats that as silence.
- **Latency:** capture chunks carry monotonic timestamps; `lag = play_t - seg_start`, and the eight parts in `metrics.STAGES` sum to it exactly. In `fixed` mode the player schedules each clip at `seg_start + fixed_lag`.
- Device lists are **WASAPI only**: one entry per device, full names. WASAPI shared mode needs the device's native rate and channels, so the player resamples the 24 kHz TTS audio.
- Models are warmed up once after loading, so the first line isn't slower than the rest. A second launch reuses a running instance (`/api/health`), so the models are never loaded twice.
- See `docs\PROJECT_PLAN.md` for the original roadmap.

### Tests

```bat
.venv312\Scripts\python.exe tests\run_all.py          REM fast + GPU suites (no sound)
.venv312\Scripts\python.exe tests\run_all.py fast     REM no GPU models (~30 s)
.venv312\Scripts\python.exe tests\run_all.py all      REM also the suites that PLAY SOUND
```

The sound suites (`test_audio_devices.py`, `test_live_ui.py`) use your default speakers unless you name other devices, for example to keep test sounds out of the headphones you're wearing:

```bat
set OMINVOX_TEST_DEVICE=LG ULTRAGEAR
set OMINVOX_TEST_OUTPUT=Realtek
```

### Licences

The XTTS-v2 voice model is released under the **Coqui Public Model License** (non-commercial use only); the app asks the user to agree before downloading or using it. The pyannote models are subject to their own terms on Hugging Face, which the user accepts there.

# Ominvox

Live, **local** audio translation with **per-speaker voice matching**. Ominvox listens to whatever is playing on your Windows PC (a movie, a YouTube video, a call), translates the dialogue live, and speaks it back. Each speaker on screen gets their own cloned voice in the new language.

Everything runs on your own computer: no cloud service, no subscription. The program, its Python environment, and all downloaded AI models stay inside the project folder.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Download Ominvox](#2-download-ominvox)
3. [Get the uv installer tool](#3-get-the-uv-installer-tool)
4. [Get a free Hugging Face token](#4-get-a-free-hugging-face-token)
5. [Create your .env file](#5-create-your-env-file)
6. [Run the setup](#6-run-the-setup)
7. [Start Ominvox](#7-start-ominvox)
8. [Avoid the echo problem (important)](#8-avoid-the-echo-problem-important)
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

## 3. Get the uv installer tool

Ominvox uses a small tool called **uv** to build its Python environment. It isn't included in the download, so you add it once:

1. Open <https://github.com/astral-sh/uv/releases/latest>.
2. Scroll to **Assets** and download **`uv-x86_64-pc-windows-msvc.zip`**.
3. Extract the ZIP.
4. In the project folder, create a new folder named **`.tools`**. The name starts with a dot.
5. Copy **`uv.exe`** (and, if present, `uvx.exe` and `uvw.exe`) into that `.tools` folder.

You should end up with:

```
D:\Ominvox\.tools\uv.exe
```

> Windows Explorer may refuse a folder name that starts with a dot. If so, type the name as `.tools.` (with a dot at the end too); Windows removes the trailing dot automatically.

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

If it ends with a red error instead, see [Troubleshooting](#10-troubleshooting).

**Alternative:** if you already use Anaconda or Miniconda, you can run `setup_conda.bat` instead of steps 3–4. It builds the same environment.

---

## 7. Start Ominvox

### The easy way: web interface

1. Double-click **`start_ui.bat`** in the project folder.
2. A window opens and your web browser opens <http://127.0.0.1:8765>. If the browser doesn't open, type that address in yourself.
3. **First start only:** the AI models download, about 5 GB. This can take several minutes. Later starts are much faster.
4. In the web page:
   - Choose the **Input Source** at the top: the speakers or headphones your movie plays on.
   - Open **Settings** (⚙) and choose the **Source Language** (or Auto-detect), the **Target Language**, the **Voice Mode** and the **Output Source** (where you hear the translation; see [section 8](#8-avoid-the-echo-problem-important)). Then click **Apply**.
   - Click **Start Listening**.
5. Play your movie. The level bar turns green when sound is detected, the transcript appears, and the translated voice plays after a short delay (1.5 seconds by default).
6. Click the 👥 button to see detected speakers and give them names.
7. To stop, click **Stop**, then close the black window.

**Voice modes:**
- **Match Speaker (clone):** each speaker gets a voice that imitates them. This needs about 6 seconds of their speech before cloning starts.
- **Preset Voice / Single Voice:** one fixed voice for everyone.

> **Language note:** with the default settings, Ominvox translates **into English** best. To translate into other languages, set `mt: backend: "nllb"` in `config.yaml` (see [section 9](#9-settings-configyaml)).

### Helper scripts (double-click)

| File | What it does |
|---|---|
| `start_ui.bat` | Starts the web interface (the normal way to use Ominvox). |
| `audiotest.bat` | Play something, then run this. It records 15 seconds and shows whether sound is being captured. Results are saved to `audiotest_output.txt`. |
| `devices.bat` | Lists all your audio devices with their numbers, saved to `devices_output.txt`. Useful for `config.yaml`. |
| `check.bat` | Runs the self-test, saved to `check_output.txt`. |
| `verify.bat` | Checks that the program files load correctly, saved to `verify_output.txt`. |

### Command line (optional)

Open a terminal in the project folder and run:

```bat
run.bat --ui                 REM web interface (same as start_ui.bat)
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
| `mt: backend` | Translation engine. `whisper` only translates to English; `nllb` handles any target language. | `whisper`, `nllb` |
| `tts: voice_mode` | Voice style | `match`, `preset`, `single` |
| `tts: preset_voice` | Path to a `.wav` voice sample for preset or single mode | `D:\voices\me.wav` |
| `playback: delay_ms` | Delay before translated speech plays | `1500` (1.5 s) |
| `audio: input_device_index` | Fixed capture device number (from `devices.bat`). `null` means automatic. | `null`, `34` |
| `playback: output_device_index` | Fixed playback device number. `null` means default. | `null`, `5` |

**Leave `diarize: hf_token` empty.** The token belongs in `.env` (see [section 5](#5-create-your-env-file)).

**Low on video memory (6 GB card)?** Set `stt: model: "small"`, or set `diarize: enabled: false`.

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `uv.exe` not found during setup | `uv.exe` must be at `<project>\.tools\uv.exe`. Redo [step 3](#3-get-the-uv-installer-tool). |
| "running scripts is disabled on this system" | Use the full command from step 6, including `-ExecutionPolicy Bypass`. |
| `torch.cuda.is_available: False` | Update your NVIDIA driver, restart, and run the setup again. If you use a laptop, plug it in and check that the NVIDIA GPU isn't disabled. |
| Error mentioning `401`, `gated`, `pyannote` or "access" | Check that `.env` exists, is named exactly `.env` (not `.env.txt`), and contains `HF_TOKEN=hf_...`. Also check that you accepted **both** model pages in [step 4](#4-get-a-free-hugging-face-token). |
| Level bar stays grey or `audiotest` says SILENCE | Pick a different **Input Source**: the one matching the device your movie actually plays on. Make sure the movie isn't muted. |
| `Invalid number of channels` | Choose a different input device in the dropdown, or set `input_device_index` in `config.yaml` using a number from `devices.bat`. |
| Translation repeats itself in a loop | That's the echo problem; see [section 8](#8-avoid-the-echo-problem-important). |
| Output is English even though another language was chosen | Set `mt: backend: "nllb"` in `config.yaml`. |
| "Port 8765 in use" | Ominvox automatically tries ports 8765–8784. Read the black window to see which port it chose, or close the other Ominvox window. |
| Out of memory / CUDA OOM | Use a smaller `stt: model` (`small`), or close games and other GPU-heavy apps. |
| Web page shows old behaviour after an update | Close the black window and start `start_ui.bat` again. |

**Starting over cleanly:** delete the `.venv312` folder and run step 6 again. To force models to download again, also delete `.cache`. Don't delete `.cache\speakers` if you want to keep your saved speaker voices.

---

## 11. For developers

### Pipeline

```
capture (WASAPI loopback / mic) -> Silero VAD -> pyannote diarization + speaker-id
  -> faster-whisper STT -> MT (whisper->en | NLLB) -> XTTS-v2 per-speaker clone
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
  config.py           loads config.yaml + .env, pins caches into .cache
  app.py              CLI entry point
config.yaml           all settings
.env.example          template for .env (HF_TOKEN)
requirements.txt      Python deps (torch installed separately, CUDA build)
setup_uv.ps1          recommended setup -> .venv312 (Python 3.12 via portable uv)
setup_conda.bat       alternative setup via conda -> .venv312
setup.bat             legacy (system Python -> .venv); run.bat does not use it
run.bat               runs .venv312 with caches pinned
test_*.py             synthetic tests
```

### Notes

- **Python 3.12 is required.** coqui-tts doesn't support 3.13.
- torch/torchaudio are installed **last** from the CUDA 12.4 index (`cu124`) so that coqui-tts can't replace them with a CPU build. Edit the index URL in `setup_uv.ps1` if your driver needs a different CUDA build.
- `transformers` is pinned `<5` because coqui-tts 0.27.x imports a symbol removed in 5.x.
- All HF, torch and TTS caches are pinned to `.cache\` by `config.py` and the `.bat` launchers. Nothing is written to `C:`.
- `config.py` reads `.env` into `os.environ` without overriding variables that are already set. `diarize.py` uses `diarize.hf_token` if set, otherwise `HF_TOKEN`.
- Every stage degrades gracefully if its model or dependency is missing, so `--check` and partial runs work before all models are installed.
- See `Ominvox_Project_Plan.md` for the roadmap, latency strategy and risks.

### Tests

```bat
.venv312\Scripts\python.exe test_pipeline.py
.venv312\Scripts\python.exe test_speaker_id.py
.venv312\Scripts\python.exe test_e2e.py
.venv312\Scripts\python.exe test_comprehensive.py
```

### Licenses

The XTTS-v2 voice model is released under the **Coqui Public Model License** (non-commercial use). `run.bat` sets `COQUI_TOS_AGREED=1`, which means you accept that license. The pyannote models are subject to their own terms on Hugging Face.

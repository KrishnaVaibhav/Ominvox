# Contributing to Ominvox

Thanks for helping! Ominvox is a Windows app that translates speech live (or
from a file) and speaks it in each speaker's own voice, entirely on the user's
GPU. This guide covers everything you need to send a good pull request.

By contributing you agree that your work is licensed under the project's
[Apache-2.0 licence](LICENSE), and that you follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to help

- **Report a bug** or **suggest a feature** with the
  [issue forms](https://github.com/KrishnaVaibhav/Ominvox/issues/new/choose).
  For bugs, attach `logs\ominvox.log` and your GPU / Windows version.
- **Fix an issue.** Ones labelled `good first issue` are a good start. Comment
  on the issue first so two people don't do the same work.
- **Improve the docs.** The README is written for people who don't code; keep it
  that way (short steps, no jargon).
- **Security problems:** please don't open a public issue - see [SECURITY.md](SECURITY.md).

## Set up a development copy

You need Windows 10/11, an NVIDIA GPU (6 GB+ VRAM, 8 GB recommended) and Git.

```powershell
git clone https://github.com/<you>/Ominvox.git
cd Ominvox
powershell -ExecutionPolicy Bypass -File setup.ps1 -NoShortcut
```

`setup.ps1` installs a portable Python 3.12 and every library into `.venv312\`
and keeps all caches in `.cache\` (nothing is installed system-wide). Then
start the app with `run.bat --window` (or `run.bat --ui` for a browser tab) and
let the setup screen download the models.

## Project layout

See [README → For developers](README.md#9-for-developers) for the full map. In short:

| Folder | What lives there |
|---|---|
| `ominvox/audio/` | capture (WASAPI loopback / mic), playback, device lists |
| `ominvox/pipeline/` | the AI stages (VAD, speakers, Whisper, NLLB, XTTS), the shared `Engine`, live orchestration, metrics |
| `ominvox/files/` | whole-file translation (media I/O with PyAV, the dubber) |
| `ominvox/firstrun/` | system checks, Hugging Face token, model downloads |
| `ominvox/ui/` | FastAPI/WebSocket server, setup screen + Files tab backends, `web/` front end (plain HTML/CSS/JS, no build step) |
| `installer/` | `Ominvox.exe` launcher and `OminvoxSetup.exe` installer sources |
| `tests/` | test scripts + `run_all.py` |

## Making a change

1. Create a branch from `master`: `git checkout -b fix/short-description`.
2. Keep the change focused - one fix or feature per pull request.
3. Match the surrounding code: same naming, same comment style (comments say
   *why*, not *what*), no new dependency unless it's really needed.
4. If you change behaviour users see, update the README in the same PR.
5. Add or update a test (see below).

### Code style

We use [ruff](https://docs.astral.sh/ruff/) (settings in `pyproject.toml`):

```powershell
.tools\uv.exe pip install --python .venv312\Scripts\python.exe ruff
.venv312\Scripts\ruff.exe check .
```

CI runs the same check on every pull request. JavaScript in `ominvox/ui/web/`
has no build step; CI checks it parses with `node --check`.

### Tests

```powershell
.venv312\Scripts\python.exe tests\run_all.py fast   # no GPU, ~1 min  (CI runs these)
.venv312\Scripts\python.exe tests\run_all.py        # + GPU suites, ~15 min, needs the models
.venv312\Scripts\python.exe tests\run_all.py all    # + suites that PLAY SOUND
```

- **Fast suites** (`test_metrics`, `test_firstrun`, `test_speaker_id`,
  `test_files_unit`) need no GPU or models and run in CI on every PR.
- **GPU suites** can't run on GitHub's machines. If your change touches the
  pipeline, the file dubber or the server, run them locally and paste the
  summary line into the PR (the PR template asks for it).
- The sound suites play audio; point them at speakers you're not wearing with
  `OMINVOX_TEST_DEVICE` / `OMINVOX_TEST_OUTPUT` (see README → Tests).

Each test file is a plain script using the small `Results` helper in
`tests/_common.py` - copy an existing test to start a new one.

### Commits and pull requests

- Write commit messages in the imperative: "Fix echo warning for mic inputs".
- Open the PR against `master` and fill in the template.
- These checks must pass before a PR can be merged: **Lint**, **Fast tests (Windows)** and **Build installer** (CodeQL also runs). The build job attaches the installer to the run, so you can test your change as users would get it.
- The maintainer reviews every PR. Expect questions - they're about keeping the
  app simple for non-technical users, not about you.
- Please don't add `Co-authored-by:` or "Generated with ..." trailers to your
  commits. Credit is given by the PR itself.

## Things to keep in mind

- **Users aren't programmers.** Every error message should say what to do next.
  Prefer a sensible default over a new setting.
- **8 GB of VRAM is the budget.** Whisper, pyannote and XTTS (and NLLB for
  non-English targets) all stay loaded. Measure VRAM and per-line latency
  before and after a pipeline change; the performance panel shows both.
- **Nothing outside the project folder.** Models, caches and settings stay in
  the Ominvox folder; never write to `C:\` paths or the user profile unasked.
- **Licences.** XTTS-v2 and NLLB are non-commercial. Don't add a model or
  library with a licence that conflicts with Apache-2.0 for the code, and say
  in the PR if you add a model with its own terms.
- **Windows only, for now.** Audio capture uses WASAPI loopback.

## Releasing (maintainer)

See [docs/MAINTAINING.md](docs/MAINTAINING.md).

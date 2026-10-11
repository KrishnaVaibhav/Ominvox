# Maintaining Ominvox

Notes for the maintainer: reviewing pull requests, merging, and releasing.

## What runs automatically

| Workflow | When | What it does |
|---|---|---|
| **CI** (`ci.yml`) | every push to `master` and every PR | ruff lint, `node --check` on the front end, a scan for committed tokens / `.env`, and the fast test suites on Windows |
| **CodeQL** (`codeql.yml`) | PRs, pushes, weekly | security analysis of the Python and JavaScript |
| **Release** (`release.yml`) | pushing a `v*` tag | builds `Ominvox.exe` + `OminvoxSetup.exe` on a clean Windows machine and drafts a GitHub Release with the installer attached |
| **Dependabot** (`dependabot.yml`) | monthly | PRs for GitHub Actions and Python dependency updates (transformers 5 and PyTorch are excluded on purpose) |

GitHub's machines have no NVIDIA GPU, so the **GPU suites never run in CI**.

## Reviewing a pull request

1. Read the description and the linked issue. Does it fit the app (simple for
   non-technical users, Windows, local-only)?
2. Check CI is green.
3. If it touches `ominvox/pipeline/`, `ominvox/files/`, `ominvox/ui/server.py`
   or audio code, run the GPU suites yourself on the PR branch:
   ```powershell
   gh pr checkout <number>
   .venv312\Scripts\python.exe tests\run_all.py
   ```
   For pipeline changes, also compare VRAM and per-line latency in the app's
   performance panel against `master`.
4. Try the change in the app if users will see it.
5. Check for new dependencies (licence, size, does `setup.ps1` still work) and
   for README updates.

## Merging

All merge methods are enabled. Squash-merging keeps `master` to one commit per
PR, and lets you edit the final message before it lands. That's where to
remove any `Co-authored-by:` or "Generated with …" lines a contributor's
commits carry. GitHub records the PR author as the author of a squashed commit.

`master` is protected: changes from others come in through PRs with CI passing.

## Releasing

1. Make sure `master` is green and the GPU suites pass locally.
2. Bump `__version__` in `ominvox/__init__.py` (e.g. `0.2.0`) and commit.
3. Tag and push:
   ```powershell
   git tag v0.2.0
   git push origin master v0.2.0
   ```
4. The **Release** workflow builds the installer and creates a **draft**
   release with generated notes. Download `OminvoxSetup.exe` from the draft,
   test-install it (`OminvoxSetup.exe --silent --dir D:\OminvoxTest`), then
   edit the notes and click **Publish**.

The installer ships the app code exactly as committed at the tag (it packs
`git ls-files`), so nothing local leaks into a release.

## Labels

`bug`, `enhancement`, `documentation`, `good first issue`, `help wanted` and
`triage` (new issues land with `triage`; remove it once you've looked).

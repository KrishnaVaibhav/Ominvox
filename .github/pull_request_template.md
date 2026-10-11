## What and why

<!-- What does this change, and why? Link the issue: "Fixes #123". -->

## How I tested it

<!-- Fast suites run in CI. If you touched the pipeline, files/, or the server,
     run the GPU suites locally and paste the last line here, e.g.
     "255 checks passed, 0 failed across 9 suites" -->

- [ ] `tests\run_all.py fast` passes
- [ ] GPU suites (`tests\run_all.py`) pass, or this change can't affect them
- [ ] Tried it in the app (for UI or behaviour changes); screenshot below if it changes the UI

## Checklist

- [ ] `ruff check .` is clean
- [ ] README updated if users will see a difference
- [ ] No new dependency, or explained why it's needed (and its licence)
- [ ] No tokens, personal files, models or logs committed

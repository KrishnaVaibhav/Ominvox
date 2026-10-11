# Security policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems.

Report it privately through GitHub:
**[Security → Report a vulnerability](https://github.com/KrishnaVaibhav/Ominvox/security/advisories/new)**.

Include what you found, how to reproduce it, and what an attacker could do.
You'll get a reply within 7 days. Once a fix is released you'll be credited in
the advisory (unless you'd rather not be).

## Supported versions

Only the latest release (and `master`) gets security fixes.

## What's in scope

Ominvox runs entirely on the user's PC, but it does run a local web server and
handle files and a token, so these matter most:

- **The local server** (`127.0.0.1:8765`): the WebSocket and the upload
  endpoint must refuse requests from other websites (Origin check). Anything
  that lets a web page control the app, read files, or start jobs is in scope.
- **Files:** path traversal through uploads or file names, opening or
  revealing files outside what the user chose, overwriting the user's files.
- **The Hugging Face token** (stored in `.env`): leaking it to logs, the UI,
  or anywhere off the machine.
- **The installer and launcher:** running or extracting anything from
  untrusted locations.

Out of scope: problems that need someone who already controls the user's
Windows account, and the third-party models' own behaviour.

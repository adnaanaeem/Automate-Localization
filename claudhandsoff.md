# Claude session handoff — read this first

The user is switching to a **different Claude account** and will resume this
work there. This file is written so a completely fresh Claude session (no
memory, no prior context) can pick up exactly where things left off, just
from reading this one file plus the two it points to. It is **not** a
replacement for [`HANDOFF.md`](HANDOFF.md) — that's the exhaustive technical
design history (32 sections, every bug found, every decision made and why).
This file is the shorter "where are we right now, and how does this user
like to work" briefing. Read this first, then read `HANDOFF.md` sections
25 onward for the deep detail on everything from the last several weeks
(iOS support, Import from Sheet, the Settings-page refactor, CI/CD).

## What this project is, in one paragraph

A Windows/macOS desktop app ("Automate Localization", pywebview + plain
HTML/CSS/JS frontend, Python backend) that keeps Android (`strings.xml`)
and iOS (`.xcstrings`) app translations in sync using AI (Gemini/OpenAI),
with optional Google Sheets QA export and a reverse "Import from Sheet"
flow. Public repo: **https://github.com/adnaanaeem/Automate-Localization**
(branch `main`). The user describes it as "vibe-coded" entirely by Claude —
they direct, Claude implements, tests, and documents.

## Current state as of this handoff

- **Latest release: v1.3.1**, live on GitHub with both installers attached
  and verified downloadable:
  - `AutomateLocalizationSetup.exe` (Windows installer)
  - `AutomateLocalization.dmg` (macOS disk image)
- **Working tree is clean** — everything up through v1.3.1 is committed and
  pushed to `main`. The only untracked file is `scripts/icon_preview.png`
  (a harmless local-only byproduct of `scripts/make_icon.py`, never
  committed, leave it alone).
- **The dev app is NOT currently running** on this machine. To launch it
  for testing: `python app/main.py` from the repo root (after
  `pip install -r requirements.txt` if it's a fresh environment).
- **CI/CD is fully working**: `.github/workflows/release.yml` builds both
  installers (Windows via PyInstaller + Inno Setup, macOS via PyInstaller +
  `hdiutil`) and publishes them to a GitHub Release automatically. To cut a
  new release: bump `app/version.py`'s `APP_VERSION` **and**
  `installer/setup.iss`'s `MyAppVersion` to the same value, commit, then
  `git tag vX.Y.Z && git push origin main && git push origin vX.Y.Z`. CI
  refuses to build if the tag and `app/version.py` disagree. Takes ~3-9
  minutes; verify with `gh run list --workflow=release.yml` /
  `gh run view <id>`, and verify the actual download links resolve (302→200)
  before telling the user it's done, not just that the API says assets exist.
  A `workflow_dispatch` trigger also exists (no tag needed) for testing the
  pipeline itself without publishing a real release.

## How this session has been working — conventions to keep

These are patterns the user has reinforced repeatedly, not one-off asks:

- **"No exe build until testing is done"** was the standing rule for most
  of this project's life — the user explicitly changed this once CI existed
  ("now deploy the both builds"), and now routinely asks to bump-and-ship
  directly after a fix is verified. Default to: verify locally first
  (`py_compile`, `node --check app/web/app.js`, and where practical an
  actual functional test), *then* offer or do the version bump + tag if the
  user's request implies shipping, matching how the last several fixes
  went out (fix → verify → bump version in both files → commit → tag →
  push → watch CI → verify the release page for real → tell the user).
- **Verify, don't assume.** Every fix in this project's recent history was
  confirmed by actually reproducing the bug or running the new code path
  (unit tests with mocked Sheets clients, a real browser-mock UI pass
  serving `app/web/` locally with a fake `window.pywebview.api`, or —
  for the CI pipeline itself — actually triggering `workflow_dispatch` and
  watching it go green before trusting it). Reading the code and reasoning
  about it is the first step, not the last.
- **HANDOFF.md gets a new numbered section for every real feature or bug
  fix**, written in detail: what was reported, root cause (with the actual
  evidence, e.g. an exception traceback or a diff of real data), the fix,
  and exactly what was verified and how. The user has never asked for this
  explicitly in recent sessions — it's just the established style, and
  skipping it would be a regression. Next section number is **33**.
- **Relaunch the dev app after every code change** the user might want to
  test, so what's running always matches the latest edits. Kill the old
  `python app/main.py` process first (`Get-CimInstance Win32_Process` /
  `Stop-Process`), then start a fresh one, then confirm the PID is live.
- The user gives feedback tersely and expects it acted on without
  re-litigating — e.g. when asked "how does X work", give a direct answer
  grounded in the actual code (grep/read it, don't guess), not a hedge.
- Never guess at ambiguous, consequential asks — this session used
  `AskUserQuestion` once for a genuine architecture fork (per-screen
  settings vs. a centralized Settings screen) and it worked well; use it
  again for anything similarly two-way-door.

## Loose thread — not yet resolved

The user shared a screenshot of a pricing card (a "Lifetime / Rs 11,100/pay
once" card with a low-contrast "One-time" badge on a green background) and
asked how to fix the contrast "according to theme UI colors." **This is not
part of the Automate Localization app** — its color palette is dark
navy/blue (`--bg: #0f1115`, `--accent: #4f8cff` in `app/web/style.css`),
not green, and nothing in this codebase resembles a pricing/subscription
card. I asked which project it's from and the user interrupted the question
with "oky now deploy the both builds" before answering — so **this is still
an open question, not abandoned**. If it comes up again: it needs either a
path to the actual project's theme/CSS file, or an explicit "just give
general advice, it's not in a codebase you can access."

## Key files to know

```
app/
  main.py            pywebview Api class -- all JS-facing backend methods
  engine.py           Android scan/translate/write + Sheet upload
  ios_engine.py        iOS translate/write (.xcstrings) + Sheet upload
  sheet_import.py      reverse-direction: read a Sheet tab back, write into
                        a local Android/iOS file; also Sheet URL parsing +
                        sheet-name lookup + the clearer-permission-error fix
  config.py             local settings (config.json) + OS-keychain API keys
  updater.py            self-update: GitHub Releases check, now platform-
                        aware (.dmg on macOS, .exe on Windows)
  version.py             single source of truth for APP_VERSION
  web/                  index.html / app.js / style.css -- 7 screens now:
                        setup, review, progress, results, settings, ios,
                        import (Settings centralizes AI provider keys +
                        Google Sheet config, shared by all platforms)
installer/setup.iss     Inno Setup script, MyAppVersion must match version.py
.github/workflows/release.yml   CI: builds + publishes both installers on tag push
scripts/
  make_icon.py           generates app/icon.ico AND app/icon.icns
  demo.html               one consolidated screenshot-generation harness,
                        ?screen=setup|review|results|settings|ios|import
  crop_screenshots.py     trims generated screenshots to content height
HANDOFF.md              full technical history, 32 sections, read this for depth
README.md               user-facing docs, download links, usage per platform
```

## If the user just says "continue" or similar

There's no specific in-flight task left half-done — the last several
requests (Sheet fixes, iOS batching/retry parity, iOS Import key-collision
reporting, CI setup, the macOS self-update bug) were all completed, verified,
shipped in v1.3.0/v1.3.1, and confirmed live. Ask what they'd like to work
on next, or check the pricing-card thread above if that seems relevant.

# Automate Localization

[![Download for Windows](https://img.shields.io/badge/Download-Windows%20Installer-4f8cff?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/adnaanaeem/Automate-Localization/releases/latest/download/AutomateLocalizationSetup.exe)
[![Latest release](https://img.shields.io/github/v/release/adnaanaeem/Automate-Localization?style=for-the-badge&color=2450b8&label=latest)](https://github.com/adnaanaeem/Automate-Localization/releases/latest)

A desktop app for Android developers that keeps `strings.xml` translations in
sync across every language in your project — automatically, using AI.

Point it at your English `strings.xml`, and it finds every string that's new
or missing in each translated language (`values-de`, `values-ja`, `values-fr`,
...), lets you review and pick exactly which ones to translate, then
machine-translates only those (via Gemini or OpenAI) and writes them back
into the right files — without ever touching a string that's already
translated.

> **Full disclosure:** I built this purely for my own convenience, entirely by vibe-coding with Claude. I did not personally write a single line of it — didn't shoot one arrow myself. Every bug fix, every feature, every questionable variable name: all Claude. I just kept saying "yes, do that" and occasionally "no, not like that."

![Setup screen — path, target languages, provider, and batching](docs/screenshots/setup.png)

<table>
<tr>
<td width="50%"><img src="docs/screenshots/review.png" alt="Review screen — filterable checklist of missing strings" /></td>
<td width="50%"><img src="docs/screenshots/results.png" alt="Results screen — per-language write counts and Sheet sync status" /></td>
</tr>
</table>

## Why

Keeping Android localizations in sync by hand doesn't scale: every time a new
string is added to the English source, someone has to notice it's missing in
a dozen other languages and translate it. This tool automates that gap-fill
step while staying safe:

- **Never overwrites existing translations** — only fills in what's actually missing, per language, independently.
- **Never silently drops a string** — translations are sent in small batches with automatic retries, and anything still missing after retries is reported, not lost.
- **Never corrupts a file it can't parse** — if a language file fails to parse, it's skipped entirely with a warning rather than guessed at.
- **You choose what gets translated** — a review screen shows every missing string before anything is sent to an AI provider, so you can deselect drafts or anything you'd rather write by hand.

## Features

- 🔍 **Auto-detects languages** — scans your `res/` folder for `values-*` directories and tells language folders (`values-de`) apart from device-qualifier variants (`values-land`, `values-sw600dp`, ...), which just get a raw copy of the English text instead of translation.
- ➕ **Add new languages** — pick from a searchable list of ~80 languages (with flags) to create a brand-new `values-<code>/` folder and populate it from scratch, even if it didn't exist before.
- ✅ **Review before you translate** — every missing string is listed with a checkbox and which languages it's missing in, checked by default, deselectable per-row. A filter box narrows the list by key or English text, and "select all"/"select none" respect whatever's currently filtered.
- 📊 **Live per-language progress** — see "German: 8/23 translated" update in real time as each language completes, not one opaque global bar.
- 🔑 **Two AI providers** — Gemini or OpenAI, switchable per run.
- 🔐 **Keys never touch disk** — API keys are entered once in the app and stored in your OS keychain via [`keyring`](https://pypi.org/project/keyring/), never written to a file or committed anywhere.
- 📋 **Optional Google Sheets QA export** — after a run, sync exactly the strings that were newly translated (backfilled with every language's current value for context) to a fresh tab in a Google Sheet for reviewers.
- 🔄 **Checks GitHub for updates on launch** — a banner appears if a newer release is available, with a one-click download-and-install; also available anytime from the **☰ Menu → Check for updates**.

## Prerequisites

- Python 3.9+
- A Gemini API key ([aistudio.google.com](https://aistudio.google.com/)) and/or an OpenAI API key ([platform.openai.com](https://platform.openai.com/))
- *(Optional, for Google Sheets sync)* a Google Cloud service account with the Sheets API enabled, and the target sheet shared with that service account's email as an Editor

## Download (Windows)

No Python required. **[Download the latest installer](https://github.com/adnaanaeem/Automate-Localization/releases/latest/download/AutomateLocalizationSetup.exe)** (`AutomateLocalizationSetup.exe`) and run it — or grab it from the [Releases page](https://github.com/adnaanaeem/Automate-Localization/releases) if you'd rather see the changelog first. It's a proper installer — Start Menu entry, optional desktop shortcut, and an uninstaller listed in "Add or Remove Programs". This is also what **☰ Menu → Check for updates** downloads and runs for you when a new version is out.

> Windows SmartScreen will likely flag it as "unrecognized publisher" the first time, since the build isn't code-signed. Click **More info → Run anyway**. This is expected for an unsigned open-source executable, not a sign of a problem — check the [Releases page](https://github.com/adnaanaeem/Automate-Localization/releases) itself, or build it yourself from source (below), if you'd rather verify first.
>
> Prefer a portable exe with no installer? Build it yourself from source (below) — `dist/AutomateLocalization.exe` isn't published as a separate release download.

## Run from source

```bash
python -m pip install -r requirements.txt
python app/main.py
```

## Usage

1. **Setup tab**
   - Browse to your English `strings.xml` (the one under `.../res/values/`, not the project root).
   - Enter your Gemini or OpenAI API key once — it's saved to your OS keychain, not to a file.
   - Optionally, check any additional languages you want new `values-<code>/` folders created for.
   - Optionally, turn on Google Sheet sync and point at a service account JSON.
2. **Scan** — the app diffs every `values-xx/` folder against English, independently per language, and lists variant/unrecognized folders separately so nothing is silently skipped.
3. **Review** — every missing string is shown with a checkbox (checked by default) and which languages it's missing in. Type in the filter box to narrow the list by key or English text — handy for a large app. Deselect anything you don't want translated this run.
4. **Run** — translates only the selected strings, in batches, with live per-language progress and a log of any retries.
5. **Results** — a summary of what was written per language, anything still missing after retries (safe to rerun — it'll be picked back up on the next scan), and Google Sheet sync status.

The **☰ Menu** (top-right) has two things: **Check for updates** (also runs automatically on launch — a banner appears if a newer release exists) and **About** (the developer's GitHub profile, fetched live).

## How it works, briefly

The engine (`app/engine.py`) reads the English source and every `values-*`
sibling folder, classifies each folder as a language, a device-qualifier
variant, or unrecognized, and diffs each language's existing strings against
English independently — so a language falling behind for reasons unrelated
to any other language still gets caught. Selected strings are sent to the AI
provider in small batches (so a response can never silently get truncated),
retried per-batch if some keys don't come back, then re-escaped deterministically
for Android's string-resource syntax (`\n`, `\t`, `\'`, inline HTML wrapped in
`CDATA`) before being surgically inserted into each file — existing entries
are never touched or reordered.

See [`HANDOFF.md`](HANDOFF.md) for the full design history, and
[`localize_claude.py`](localize_claude.py) for the original reference CLI
script this app's engine was ported from.

## Project structure

```
app/
  main.py       # pywebview entry point / JS-facing API
  engine.py     # scan/translate/write logic
  config.py     # local settings + OS-keychain API key storage
  providers.py  # Gemini/OpenAI client setup
  updater.py    # checks GitHub Releases, downloads + launches the installer
  version.py    # single source of truth for the app version
  icon.ico      # app icon (exe, window/taskbar, installer)
  web/          # frontend (plain HTML/CSS/JS, no framework)
installer/
  setup.iss     # Inno Setup script -- builds the Windows installer
scripts/
  make_icon.py  # regenerates app/icon.ico
localize_claude.py  # original reference CLI script
requirements.txt
requirements-build.txt        # adds pyinstaller, for building the .exe yourself
AutomateLocalization.spec     # PyInstaller build recipe
```

## Building it yourself

The Releases page always has the latest prebuilt installer and portable
executable, but if you'd rather build them yourself from source:

```bash
python -m pip install -r requirements-build.txt
python -m PyInstaller AutomateLocalization.spec --noconfirm
```

This writes `dist/AutomateLocalization/` — the executable plus an
`_internal/` folder it needs sitting next to it (an intentional choice, not
a stray folder to clean up — see `AutomateLocalization.spec`'s comment for
why this isn't a single-file build).

To also build the installer, you'll additionally need [Inno Setup](https://jrsoftware.org/isinfo.php)
(free), then:

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
```

which writes `dist_installer\AutomateLocalizationSetup.exe`.

**Screenshots** in this README (`docs/screenshots/`) are generated, not
hand-captured — `scripts/demo_*.html` fake the `window.pywebview.api` layer
with realistic sample data so the real `app/web/` UI can be rendered
headlessly:

```bash
python -m http.server 8935 --directory .
# then, per screenshot:
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new --disable-gpu --window-size=1100,1500 --screenshot="docs\screenshots\setup.png" "http://localhost:8935/scripts/demo_setup.html"
```

Re-run this (and re-crop as needed) after any visible UI change so the
README doesn't go stale.

## Security

- API keys live only in your OS keychain (`keyring`) — never in a file, never committed.
- `config.json` (recent paths, non-secret settings) and `service_account.json` are git-ignored; they never leave your machine.
- If you're setting up your own fork, replace the placeholder `GOOGLE_SHEET_ID`/paths in `localize_claude.py` with your own before running it standalone — the desktop app itself takes these as user input, not hardcoded values.

## License

No license has been chosen yet — until one is added, all rights are reserved by the author.

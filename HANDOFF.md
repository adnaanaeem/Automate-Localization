# Handoff: Android Localization Desktop App

> **Status as of 2026-08-13: built, working, public, packaged, self-updating, and renamed to "Automate Localization."** Tested against real translation runs (Gemini) including Google Sheet sync. Pushed to a public GitHub repo (secret-audited first), shipped as a proper Windows installer (plus a portable exe) with in-app update checking against GitHub Releases, and has an About screen with a live-fetched developer profile.
> Sections 1-9 below are the *original* spec this was built from — still accurate as ground truth for the engine logic, but written under the project's original working name, **"Smart Localization Automation."** The app and its internal identifiers were renamed to match the GitHub repo (`Automate-Localization`) partway through -- see section 17 for exactly what changed and why the rename needed a config-migration shim. If you're continuing this project, read sections 1-9 for context, then jump to **section 10 onward** for what's actually been built, bugs found beyond the original list, how the open questions in section 8 were resolved, and what's not done yet. **Section 16** covers the public repo and the first `.exe` release; **section 17** covers the installer, self-update, and rename that came after it.

## 1. What this project is

An internal tool that keeps Android `strings.xml` files in sync across languages. Given the English source file, it finds strings that are new or missing in each translated language, machine-translates only what's missing (via Gemini or OpenAI), writes them back into the right `values-xx/strings.xml` files without touching anything already translated, and logs everything to a Google Sheet for QA.

A working reference implementation already exists as a CLI script: **`localize_claude.py`** (attached alongside this doc). It is fully functional and has already been debugged through several rounds — treat its core logic as correct and battle-tested, and **port it, don't rewrite it from scratch**. The only thing wrong with it for this project's purposes is that it's a `input()`-driven terminal script with no UI and no way to review/select strings before running.

## 2. What we're building now

A desktop app with a window, replacing the terminal flow with:

1. **Set project path** — a field where the user points at their English `strings.xml` (e.g. `.../res/values/strings.xml`), not the whole project root.
2. **Scan** — the app reads that file, compares it against every `values-xx/strings.xml` sibling folder, and loads the full list of strings that are new/missing in at least one language.
3. **Review list** — every missing string is shown with a checkbox, checked by default. The user can deselect any they don't want translated in this run (e.g. because it's still a draft, or they want to write that one by hand).
4. **Run** — only the checked strings get sent for translation. Progress is shown **language by language** (e.g. "German: 8/23 translated", then moves to Spanish, etc.), not just a single global progress bar.
5. **Result** — a summary of what was written per language, anything that failed after retries, and confirmation that the Google Sheet was updated.

## 3. Deriving paths from the one field the user sets

The user only sets the path to the English `strings.xml`. Everything else is derived from it:

```
selected path:      .../app/src/main/res/values/strings.xml
BASE_RES_PATH  = dirname(dirname(selected path))   ->  .../app/src/main/res
language folder:     BASE_RES_PATH / f"values-{code}" / "strings.xml"
```

Recommendation: **auto-detect available languages** by scanning `BASE_RES_PATH` for `values-*` folders instead of relying on the hardcoded `LANG_MAP` dict in the reference script. Filter out folders that aren't real languages (`values-land`, `values-sw*dp*`, `values-night`, `values-v21`, `values-w*dp`, etc. — anything matching a known non-language qualifier pattern). Map recognized ISO codes (`de`, `es`, `fr`, `ja`, `zh-rCN`, ...) to display names for the UI using the same mapping as `LANG_MAP` in the reference script, but let it be a lookup table, not a hard requirement — unrecognized-but-present `values-xx` folders should still show up (labeled by their raw code) rather than being silently skipped, since silently skipping languages is exactly the class of bug this project has already had to fix once.

The reference script's `VAR_FOLDERS` list (`values-land`, `values-sw600dp`, etc.) — screen-size/orientation variants that just get a raw copy of the English text, no translation — should be handled the same way: auto-detected, not translated, just diffed and copied.

## 4. Core logic to port (from `localize_claude.py`)

These functions are the tested engine — reuse the logic, just restructure so the UI can drive it and subscribe to progress instead of it running straight through `main()`:

- `get_eng_strings_with_context()` — reads English `strings.xml` into `{key: {text, context}}`. `context` comes from a `description` attribute if present and is only used to give the AI extra context, never written back out.
- `get_existing_strings(path)` — returns `{key: text}` for an existing language file, `{}` if the file doesn't exist yet, or `None` if it exists but fails to parse (callers must treat `None` as "do not touch this file," not as empty — this is what prevents the app from ever corrupting or duplicating a language file with a pre-existing syntax error).
- `chunk_dict(d, size)` — batches strings into groups (`BATCH_SIZE = 25`) before sending to the model. **Do not remove this.** Sending everything in one prompt is what caused strings to silently vanish in the original buggy version of this script — the model's response gets truncated with no way to detect it.
- `translate_batch(...)` / `translate_batch_with_retry(...)` — sends one batch to Gemini or OpenAI, parses `Key: TranslatedText` lines back into a dict, and retries only the keys that didn't come back (`MAX_RETRIES_PER_BATCH = 2`). Returns `(results, still_missing)` — `still_missing` must be surfaced to the user, never silently dropped.
- `_collapse_escapes` / `escape_android_string` / `format_string_value(val)` — normalizes and re-escapes Android string syntax (`\n`, `\t`, `\'`, `\\`) exactly once regardless of what the AI returned. This is the fix for a real bug we hit: the AI sometimes turns `\n` into `\\n` when translating, which broke the build. Real HTML markup (`<b>`, `<i>`) is detected via `TAG_RE` and wrapped in `CDATA` instead of being escaped.
- `append_to_xml_file(folder, data_dict)` — surgically inserts new `<string>` entries before `</resources>`, skipping any key that already exists in that file. **Never overwrites an existing translated string.**

### What needs to change structurally

`main()` in the reference script is a linear script with `input()` and `print()` calls. For the app, refactor this into something like:

```python
class LocalizationEngine:
    def scan(self, base_res_path: str) -> ScanResult:
        """Reads English source + every language folder, returns per-key,
        per-language missing status for the UI to render as a checklist."""

    def run(self, selected_keys: set[str], provider, on_progress) -> RunResult:
        """Translates only selected_keys, batch by batch, per language.
        on_progress(language, done, total) fires after every batch so the
        UI can show live per-language progress. Writes results via
        append_to_xml_file as each language completes (not all at the end),
        so a crash partway through doesn't lose already-finished languages."""
```

`ScanResult` should carry, per key: the English text, and which languages already have it vs. are missing it — the UI needs this to show the checklist meaningfully (e.g. "missing in: German, Japanese" per row), not just a flat list of key names.

## 5. Known bugs already fixed — do not reintroduce these

The reference script went through a debugging pass; these are load-bearing, not optional:

1. **Per-language diffing, not a single reference language.** The very first version of this script only compared English against German to decide what was "new," so any language that fell behind independently of German (e.g. only Japanese missing a string) never got backfilled. Every language must be diffed against English independently.
2. **Batched translation with retry**, as above — no single giant prompt.
3. **XML/Android escaping done once, deterministically, after translation** — never trust the model's own escaping verbatim.
4. **QA sheet backfill.** When a key is only missing in some languages, the Google Sheet export pulls the *existing* value for languages that weren't touched this run (from `get_existing_strings`), so a sheet row shows the true current state across all languages, not blanks that could be misread as "missing in the app."
5. **Sheet tab naming** avoids characters Google Sheets disallows in tab names (`: [ ] * / \ ?`) — current format is e.g. `Gemini Localization - Aug 12, 2026 05_10 PM`.

## 6. Security — must fix before shipping

The very first version of this script had live-looking Gemini and OpenAI API keys hardcoded in plain text in the source, and a Google service-account JSON credential expected to sit in the project folder. For the app:

- API keys must be entered by the user in the app (e.g. a settings screen) and stored in the OS keychain (`keyring` package) or an untracked local config file — **never hardcoded, never committed.**
- If this app is going in a git repo, add `service_account.json`, `.env`, and any local config/credentials file to `.gitignore` from the start.
- If the keys pasted into earlier chat messages during this script's development are real, they've already been exposed and should be rotated in Google AI Studio and the OpenAI dashboard regardless of what this app does.

## 7. Suggested tech stack

Since the entire working engine is Python (`lxml`, `google-generativeai`, `openai`, `gspread`), keep the backend in Python and pick a UI layer rather than rewriting the engine in another language:

- **`pywebview` + a small local HTML/JS frontend** — gives a real native window (not a browser tab), lets the frontend be plain HTML/CSS/JS (checklist table, progress bars), and the Python side stays exactly the engine above, called directly — no HTTP server needed. Good default choice given the "a window" requirement.
- **PySide6/PyQt6** — a fully native GUI if a more traditional desktop-app look/feel is wanted; more boilerplate for a table + checkboxes + progress view than the webview approach.

Either is reasonable; pywebview is the faster path to the UI described in section 2.

## 8. Open questions to resolve while building (or ask the user)

- Should translations be editable in the review screen before running, or purely select/deselect?
- Should a failed key (still missing after retries) be retryable individually from the UI, or only via a full rerun?
- Multiple projects/paths remembered (recent list), or single path re-entered each time?
- Does the Google Sheet sync stay mandatory, or become optional/toggleable per run?
- Batch size and retry count — expose as settings, or keep as fixed constants like the reference script?

## 9. Files provided

- `localize_claude.py` — working reference CLI implementation described above. Use it as ground truth for the translation/escaping/file-writing logic; do not port its `input()`-based `main()` as-is.

---

## 10. What's actually been built

Chosen stack: **pywebview** (section 7's recommended default). Layout:

```
app/
  main.py       -- pywebview Api class: file dialogs, scan, threaded run with
                   live progress via window.evaluate_js(). Entry point.
  engine.py     -- LocalizationEngine (scan()/run()), ported core logic from
                   localize_claude.py, auto-detection of values-* folders,
                   language-picker data (get_all_language_options()).
  config.py     -- local JSON config (recent paths, batch/retry settings,
                   sheet settings) + OS-keychain API key storage via `keyring`.
                   Config file lives at %APPDATA%/SmartLocalizationAutomation/
                   config.json (Windows) -- never contains API keys.
  providers.py  -- Gemini/OpenAI client setup, ported from the reference
                   script's get_available_gemini_model()/setup_openai().
  web/
    index.html  -- 4 screens: setup -> review -> progress -> results
    app.js      -- all frontend logic, no framework
    style.css   -- dark theme
requirements.txt
```

Run it with `python app/main.py` (after `pip install -r requirements.txt`). No build step, no HTTP server -- the JS frontend calls Python directly via `window.pywebview.api.*`, wired up in `main.py`'s `Api` class.

## 11. Bugs found and fixed during implementation/testing (beyond section 5's list)

These were **not** in the original reference script's known-bugs list -- found by actually running the app end to end, not just reading the code:

1. **Inline-markup text truncation** (`engine.py`, `_element_full_text`). The reference script's `get_eng_strings_with_context`/`get_existing_strings` read only `element.text`, which in `lxml` only captures text *before* the first child tag. A string like `Hello <b>world</b>!` silently became just `"Hello "` -- everything after the inline markup was dropped. Fixed with a helper that walks the element's children + tails and reassembles the full content. **Do not revert to `s.text` directly** if this code is touched again.
2. **pywebview file-dialog filter format** (`main.py`, `choose_strings_file`). pywebview's `create_file_dialog(file_types=...)` requires each entry to match `"description (*.ext)"` with a literal wildcard -- `"strings.xml (strings.xml)"` (no `*.`) throws `ValueError` inside pywebview's own bridge thread, which surfaces to the user as "Browse does nothing," not an error dialog. Any new file filter added here must include the `*.` wildcard or it will fail silently the same way.
3. **Google Sheet sync scope bug** (`engine.py`, `build_sheet_rows`). Originally, syncing to Sheets re-uploaded *every* key that a touched language's file contained -- not just the keys translated in that run -- because it looped over all English keys and included any that existed in the language's (now-updated) file. In practice this meant a run that translated 14 new strings for German would re-upload all ~149 German rows to a fresh sheet tab, silently resurrecting rows the user had manually deleted from a previous tab. Fixed by having `LocalizationEngine.run()` track `written_keys` (the exact union of keys that got a new translation anywhere this run) and restricting `build_sheet_rows` to that set -- each included row is still backfilled across all languages for full context, just not padded out with untouched keys. **This is intentional, tested behavior -- do not change back to "every key in a touched language" without checking with the user first.**
4. **Silent/empty sheet-sync errors** (`main.py`, `_run_translation_thread`). `str(e)` on some `gspread`/`oauth2client` exceptions (notably permission errors) returns an empty string, which the UI then showed as "unknown error" with zero diagnostic value. Fixed to fall back to `f"{type(e).__name__} (no message -- see log for details)"` and to always log `type(e).__name__: str(e)` plus the full traceback to the Progress screen's log panel via `on_log`.

## 12. Section 8's open questions -- resolved

- **Editable translations in review, or select/deselect only?** -> Select/deselect only, per the recommended default. Not implemented as editable.
- **Retry a single failed key from the UI, or only full rerun?** -> Not built. A failed key (still missing after `MAX_RETRIES_PER_BATCH` retries) just gets picked up again automatically on the next Scan, since scan() diffs against what's actually in the file. No per-key retry button exists.
- **Recent paths remembered, or re-entered each time?** -> Remembered. `config.py`'s `add_recent_path()` keeps the last 5, shown as clickable chips on the Setup screen.
- **Google Sheet sync mandatory or optional?** -> Optional, toggleable per session via a checkbox on Setup (`sheet_sync_enabled`), off by default.
- **Batch size / max retries: fixed constants or exposed settings?** -> The one place this project deviated from the reference script's fixed constants -- both are user-adjustable number inputs on the Setup screen, persisted in `config.json`.

## 13. Feature added beyond the original spec: picking new languages to create

The original spec (section 3) only covered *auto-detecting* `values-*` folders that already exist. During testing, the user's project had **zero** existing language folders, so there was nothing to translate into. Added on top of the original scope:

- `engine.discover_res_layout()` still auto-detects existing folders, unrestricted, as originally designed.
- `LocalizationEngine.scan(additional_lang_codes=None)` now also accepts a list of language codes to treat as target languages even if their `values-<code>/` folder doesn't exist yet -- `run()` already handled creating a new folder from scratch (via `append_to_xml_file`'s `os.makedirs`), so no engine changes were needed there, only in how `scan()` builds `layout['languages']`.
- The Setup screen has a filterable, flag-emoji language picker (`engine.get_all_language_options()`, exposed via `Api.get_language_options()`) covering ~80 languages (`engine.LANG_DISPLAY_NAMES` plus `zh-rCN`/`zh-rTW`). The 10 languages the reference script's `LANG_MAP` already handled (`de, es, fr, in, it, ja, ko, pt, ru, zh-rCN`) are pre-checked by default (`LEGACY_LANG_MAP` in `engine.py`), but the user can check/uncheck any language freely -- **it is not restricted to the legacy 10**, an early iteration of this feature was but the user asked for full freedom of choice.
- Checked languages also show as a separate removable chip list above the filter box, so a selection isn't hidden once the filter text no longer matches it.

## 14. Known gotchas for whoever continues this

- **Google Sheet sync requires sharing the sheet with the service account's email**, same as inviting a collaborator -- the JSON's `client_email` field (e.g. `xxx@yyy.iam.gserviceaccount.com`) must be added as an Editor on the target sheet, or sync fails with a permission error. This is a Google Sheets/service-account fact of life, not something the app can work around.
- `google.generativeai` (used in `providers.py`) is a **deprecated package** per its own `FutureWarning` at import time -- still functional as of this writing, but Google wants callers on `google.genai` instead. Worth migrating eventually; not urgent.
- A lot of noisy `[pywebview] Error while processing window.native...` / WebView2 `COM`/accessibility-probe errors print to stdout on this Windows dev machine. These are **not app bugs** -- they're something external probing the native window's object tree (accessibility tooling) and hitting recursion limits walking WebView2's COM surface. The app itself has run stably through multiple real translation sessions despite this log noise; don't chase it as a real issue unless the app actually stops responding.
- Local machine already has real credentials configured (`config.json` has a real `google_sheet_id` and `service_account_path`; `keyring` has a real Gemini key). Don't print, log, or commit the contents of the service account JSON or the config file's values -- reading `client_email` out of it to tell the user which account to share a sheet with is fine (already done once), reading/exposing `private_key` is not.

## 15. Not yet done / possible next steps

- OpenAI provider path (`providers.get_openai_client`) is wired up but has **not been exercised end-to-end** in testing -- only Gemini has a real tested run behind it.
- No automated tests exist for `engine.py`'s logic (scan/run/build_sheet_rows/escaping). All verification so far has been manual, running the actual app.
- ~~No packaging/distribution step~~ -- done, see section 16. Packaging is Windows-only so far; no macOS/Linux build has been attempted.
- No per-key manual retry from the Results screen (see section 12).
- No code signing on the `.exe` -- Windows SmartScreen flags it as an unrecognized publisher (documented in the README, not a bug, but a real friction point for end users; a code-signing certificate would fix it and costs money/requires an identity-verified publisher account).

## 16. Public repo and the .exe release

The project is public: **https://github.com/adnaanaeem/Automate-Localization** (default branch `main`; a leftover empty `master` branch from repo creation still exists and can be deleted).

**Before the first push**, the whole tree was audited for secrets (grepped for API-key patterns, private-key markers, service-account fields -- all clean) and for real-but-not-credential internal identifiers. Two were found and genericized before pushing, both leftover from the reference script: a real Google Sheet ID (`localize_claude.py`'s `GOOGLE_SHEET_ID` and the matching UI placeholder in `web/index.html`) and an internal Android module path (`BASE_RES_PATH = "common-ui-android/..."`). **If you ever hardcode a real value into `localize_claude.py` or a UI placeholder while testing, remember to genericize it again before the next push** -- these aren't secrets in the credential sense, but they're real identifiers from someone's actual project and shouldn't leak just because they were convenient to test with. `.claude/` (local Claude Code tool state, has machine-specific file paths) and `build/`/`dist/` (PyInstaller output) are git-ignored and were never pushed.

**The `.exe` release** (`v1.0.0` tag, GitHub Release with the binary attached) is built via PyInstaller from `SmartLocalizationAutomation.spec` -- see section 13's sibling, the "Building the .exe yourself" section in `README.md`, for the exact command. Notable things learned building it:

- `app/main.py` needed a frozen-vs-dev path split for `WEB_DIR` (`sys._MEIPASS` when `sys.frozen`, else the source directory as before) -- otherwise the bundled `web/` assets can't be found once packaged.
- The naive `--collect-all` flags needed for `google.generativeai`/`grpc`/`gspread`/`oauth2client`/`keyring` also pull in matplotlib, pandas, pyarrow, and tkinter transitively, ballooning a first test build to 337MB for a --onedir build. Excluding those (`--exclude-module`) got a `--onefile --windowed` build down to ~69MB with no loss of function -- confirmed by an actual smoke-test run of the packaged exe (checked for a live WebView2-hosted process and the absence of any `Traceback`/`ModuleNotFoundError` in its output), not just a successful build.
- `pyinstaller` is a build-only dependency, kept in `requirements-build.txt` (`-r requirements.txt` + `pyinstaller`), not in the main `requirements.txt` that end users installing from source need.
- Uploading a ~70MB asset to a GitHub Release via the API can silently get cut off by a shell/tool-level timeout mid-transfer -- the first attempt returned an API "success" response with a plausible-looking size, but the asset was actually stuck in a non-downloadable state (`"state": "starter"`, 404 on the actual download URL) because the upload never finished. **Always verify a freshly uploaded release asset by actually fetching its `browser_download_url`** (expect a 200, not just a 302 redirect existing) rather than trusting the creation API's response alone. The fix was deleting the broken asset and re-uploading with the transfer unconstrained by any timeout.
- The API key already appearing "set" in a freshly built `.exe` on the same dev machine is expected, not a leak: `keyring`-backed keys live in the OS credential store (Windows Credential Manager, service name `SmartLocalizationAutomation`), keyed by the OS user account, not by which binary asks for it. Verified empirically that the actual key bytes are not present anywhere in the built `.exe` file. Someone else downloading the release on a different machine/account starts with no key configured, as expected.

## 17. Installer, self-update, and the rename to "Automate Localization" (v1.1.0)

Three things landed together in this pass: a real Windows installer (not just the portable exe from v1.0.0), in-app update checking against GitHub Releases, and a rename of the whole app from its original working name **"Smart Localization Automation"** to **"Automate Localization"**, matching the GitHub repo name (`Automate-Localization`) it had already been published under. A Menu (☰, top-right) and About screen were added too, since there needed to be somewhere to put "check for updates" once it stopped being a static exe.

**The installer** is `installer/setup.iss`, built with [Inno Setup](https://jrsoftware.org/isinfo.php) 6 (already present on the dev machine at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` -- no separate install needed there). It wraps the same PyInstaller-built `dist/AutomateLocalization.exe` as a payload, installs per-user by default (`PrivilegesRequired=lowest` + `PrivilegesRequiredOverridesAllowed=dialog`, so no UAC prompt unless the user explicitly asks for an all-users install), creates a Start Menu entry and optional desktop shortcut, and registers a proper uninstaller. `CloseApplications=yes` makes it detect and offer to close a running instance of the app before installing -- this is what makes "download the new installer and run it" behave like a real update instead of a file-in-use error.

**The self-update flow** (`app/updater.py` + `Api.check_for_update()`/`Api.download_and_install_update()` in `main.py`): on launch, and from Menu -> Check for updates, the app hits `GET /repos/adnaanaeem/Automate-Localization/releases/latest` (unauthenticated, no rate-limit concerns at this scale), compares the tag against `app/version.py`'s `APP_VERSION` via a plain parsed-integer-tuple comparison, and looks for an asset literally named `AutomateLocalizationSetup.exe` in that release -- if a newer tag exists but that exact asset isn't attached, `check_for_update` deliberately reports no update available rather than offering something that isn't there. **Every future release's installer asset must be named exactly `AutomateLocalizationSetup.exe`** (matching `updater.INSTALLER_ASSET_NAME`) or in-app update detection silently stops working -- there's no fuzzy matching. If "Download & Install" is clicked, the app downloads that asset to `%TEMP%`, launches it (not silently -- no `/VERYSILENT` flag is passed, so the user sees the normal installer UI and its own "close the running app" prompt), and then calls `os._exit(0)` immediately after to get out of the installer's way.

**The rename's config-migration shim** (`app/config.py`): `APP_NAME` changed from `"SmartLocalizationAutomation"` to `"AutomateLocalization"`, which is also the `keyring` service name and the config folder name under `%APPDATA%`. Changed blindly, this would have stranded every already-saved API key and setting on the dev machine (and anyone else's v1.0.0 install) -- the app would've looked in a keychain entry/config folder that no longer matched anything. Fixed with a one-way migration read: `get_api_key()` now falls back to the old service name (`SmartLocalizationAutomation`) if the new one has nothing, and copies the value forward on first read; `load_config()` does the same for `config.json` by reading from the legacy `%APPDATA%\SmartLocalizationAutomation\config.json` path if the new one doesn't exist yet. **If you ever rename this app again, repeat this pattern** -- it's cheap and it's the difference between a rename and a silent regression for existing users.

**Files renamed to match**: `SmartLocalizationAutomation.spec` -> `AutomateLocalization.spec` (and the `name=` inside it), producing `dist/AutomateLocalization.exe` instead of `dist/SmartLocalizationAutomation.exe`. `installer/setup.iss` outputs `dist_installer/AutomateLocalizationSetup.exe`. Window title and `<title>`/`<h1>` in `web/index.html` updated to "Automate Localization." `localize_claude.py` was **not** renamed or touched -- it's the historical reference script, section 1-9's context, and stays under its original name.

**About screen** (`web/index.html`'s `#about-modal`, wired in `app.js`): avatar comes straight from `https://github.com/adnaanaeem.png` (GitHub's no-auth-needed avatar endpoint), and name/location/company/profile-link are fetched live client-side from `https://api.github.com/users/adnaanaeem` (public, unauthenticated, CORS-enabled -- confirmed working from the app's local `file://`-style page) with the static values already in the HTML as an offline fallback if that fetch fails. **If the GitHub username ever changes, update `GITHUB_USERNAME` in `app.js` and the hardcoded fallback `href`/text in `index.html`'s `#about-modal`** -- both currently hardcode `adnaanaeem`.

**Verification done before shipping this**: rebuilt the PyInstaller exe under the new name and spec, compiled the installer, then actually ran a full install -> verify Start Menu + desktop shortcuts exist -> uninstall -> verify everything (files, shortcuts, registry key) was removed cleanly, all via silent CLI flags to a scratch directory rather than touching the real Program Files. Also unit-verified `updater.check_for_update()`'s version-comparison and asset-matching logic against both the real (older) v1.0.0 release on GitHub and a mocked v1.1.0-shaped response, confirming it correctly says "no update" when the current release has no installer asset by that name (true for v1.0.0, which predates this feature) and correctly detects an update once one exists with the right asset name.

## 18. App icon, a real launch-hang bug, and installer-only releases (v1.1.1)

**App icon**: `scripts/make_icon.py` generates `app/icon.ico` programmatically with PIL (`ImageDraw` primitives only -- ellipses, arcs, lines, a rounded-rect gradient mask) rather than depending on an SVG rasterizer or an external image generation tool, neither of which were reliably available. Design: a white globe outline (localization) with a white-badged circular sync-arrow (automation) in the bottom-right, on the app's own accent-blue diagonal gradient (`#5b93ff` -> `#2450b8`, matching `web/style.css`'s `--accent`). Checked visually at 16/32/48px before committing to it -- legible from 32px up, a bit soft at 16px like most detailed icons, judged acceptable. Wired in three places: `AutomateLocalization.spec`'s `EXE(..., icon='app/icon.ico')` (the .exe's own icon, what Explorer/taskbar show), `app/main.py`'s `webview.start(icon=ICON_PATH)` (window/taskbar icon at runtime, `ICON_PATH` resolved the same frozen-vs-dev way as `WEB_DIR`), and `installer/setup.iss`'s `SetupIconFile=..\app\icon.ico` (the installer .exe's own icon). Icon is also added to the spec's `datas` so it's extracted alongside `web/` in a frozen build. Verified by extracting the icon back out of the built exe (`System.Drawing.Icon.ExtractAssociatedIcon` in PowerShell) and eyeballing it, rather than trusting that specifying `icon=` in the spec did the right thing.

**A real bug, not a false alarm**: the user reported the app "hangs and doesn't respond for a while" on launch. Root cause: `Api.check_for_update()` (added in v1.1.0) called `updater.check_for_update()` -- a network request to GitHub's API -- directly and synchronously from the pywebview JS-API bridge, unlike `run_translation`/`download_and_install_update`, which both already ran on a `threading.Thread`. If GitHub is slow or unreachable, that blocks whatever's serializing calls on the bridge, and the whole UI reads as frozen until the request resolves or times out -- worse on unreliable connections, which is plausible here (`Menu -> About` shows the developer's own GitHub profile lists their location as Lahore, Pakistan, where GitHub connectivity issues aren't unheard of). **Fixed to match the existing pattern**: `check_for_update()` now spawns a thread and returns `{"ok": True}` immediately; the actual result arrives later via a new `onUpdateCheckResult` event, same as `onTranslationProgress`/`onTranslationDone` already do. `app.js`'s `checkForUpdate()` no longer awaits a return value -- it fires the call and returns; `window.onUpdateCheckResult` handles the result whenever it lands. **Lesson for later network calls added to this app**: anything exposed on the `Api` class that does I/O -- especially network I/O -- needs to be threaded like this from the start, not just the ones that "obviously" take a while. A 5-second `timeout=` in the Python request doesn't bound how long the *user* perceives the freeze if the call itself blocks a shared bridge.

**Release policy**: starting with this release, GitHub Releases only get the installer (`AutomateLocalizationSetup.exe`) attached, not the raw portable `dist/AutomateLocalization.exe` -- explicit user instruction, to keep the Releases page pointing people at one clear download. The portable exe still gets built locally (Inno Setup needs it as its payload regardless) and anyone can still produce it themselves via the "Building it yourself" README section; it's just not published as its own release asset anymore. `README.md`'s Download section was updated accordingly.

**Verification before shipping v1.1.1**: full rebuild (exe + installer) with the icon and threading fix included; confirmed the embedded icon is the real one (extracted and viewed, not assumed); smoke-tested the exe launches cleanly with no traceback. While checking running processes during that smoke test, found the user already had a real (non-scratch, default-location) v1.1.0 install running from a prior session at `%LOCALAPPDATA%\Programs\Automate Localization\` -- left that process alone rather than killing it, since it wasn't something this session started.

## 19. Switched from --onefile to --onedir after a real crash (v1.1.2)

v1.1.1 shipped, and the user hit `Failed to load Python DLL '...\_MEI111762\python314.dll'. LoadLibrary: The specified module could not be found.` on launch after updating. First guess was UPX corrupting the DLL during compression (`upx=True` was set in the spec) -- checked, and wrong: `upx.exe` isn't even installed on this dev/build machine, so `upx=True` was a no-op locally the whole time, meaning it couldn't have been the actual cause of what shipped. Don't repeat that guess; the real cause was structural, not a compression flag.

**Root cause**: `--onefile` mode bundles everything into a single exe that self-extracts to a fresh `%TEMP%\_MEI<pid>` folder *on every launch*, then loads `python314.dll` and its dependencies (`VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`, etc.) from there. This is a well-documented PyInstaller failure class -- antivirus interference with the freshly-extracted DLLs, extraction races, partial extraction -- and it's exactly the kind of thing that's more likely to bite a freshly-downloaded, unsigned, Mark-of-the-Web-flagged exe (which is what every real user's copy is) than a exe run straight from a dev folder (which is what all of this project's local smoke tests up to that point had been doing -- a real gap in how "verified" v1.1.0/v1.1.1 actually were).

**Fix**: switched `AutomateLocalization.spec` from a single onefile `EXE(...)` (with `a.binaries`/`a.datas` baked directly in) to the standard onedir split -- `EXE(..., exclude_binaries=True)` + a `COLLECT(...)` step -- which extracts everything **once, at build time**, into `dist/AutomateLocalization/` (the exe plus an `_internal/` folder sitting next to it, PyInstaller 6.x's default layout). No more per-launch extraction, so that whole failure class is gone by construction, not papered over. `upx=False` explicitly now too (harmless either way here, but removes the variable for good). `installer/setup.iss`'s `[Files]` section changed from copying one exe to `Source: "..\dist\AutomateLocalization\*"; ... Flags: ignoreversion recursesubdirs createallsubdirs` -- the installer bundles the whole folder. This is invisible to the end user (they still download and run one installer exe); only the internal PyInstaller packaging strategy changed.

**Also fixed in the same pass**: the user separately asked why the desktop/Start Menu shortcut icon didn't visually update after installing the version that added the app icon. Not a packaging bug -- Windows Explorer caches exe/shortcut icons aggressively and doesn't reliably notice an in-place icon change on the same file path. Added a `[Code]` section to `installer/setup.iss` that calls `SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0)` (from `shell32.dll`) in `CurStepChanged` at `ssPostInstall` -- the standard Inno Setup recipe for nudging the shell to refresh its icon cache after install/update, instead of leaving the user to manually restart Explorer.

**Verification this time was deliberately different from before**, specifically to catch what v1.1.1's testing missed: silently installed the onedir build to a scratch directory (`/VERYSILENT /DIR=...`), then **launched the exe from that installed location** (not `dist/AutomateLocalization.exe` in the dev folder) -- reproducing the actual shape of what a real user does, not just "does the build succeed." Confirmed: single process (onedir doesn't need onefile's launcher-plus-extracted-child pair, so process count itself is a useful signal), no DLL error, `VCRUNTIME140*.dll` visibly present in `_internal/` rather than needing extraction, icon still correctly embedded (re-extracted and viewed, same method as v1.1.1). Then ran the uninstaller and confirmed full cleanup, same as prior releases. **Lesson**: for a packaged desktop app, "the exe I built launches" and "the exe a user downloads and installs launches" are not the same test -- verify from the actual installed/extracted location a real update or fresh install would produce, not the build output sitting in the dev folder.

## 20. README download badges + changed setting defaults (v1.1.3)

Two small, independent things landed together:

**README download buttons**: added two shields.io badges at the very top of `README.md` -- a "Download for Windows" button and a "Latest release" version badge -- both linking through GitHub's stable `/releases/latest/download/<asset-name>` and `/releases/latest` URLs respectively. That URL pattern always resolves to whatever the current latest release is, so **these links never need to be hand-updated on future releases** as long as every release keeps attaching an asset literally named `AutomateLocalizationSetup.exe` (same constraint `updater.INSTALLER_ASSET_NAME` already has -- see section 17). Verified both the badge images (200) and the download link (302 -> 302 -> 200, matching the real asset) resolve correctly before committing, not just assumed the markdown syntax was right.

**Changed the shipped defaults** for two Setup-screen settings, per explicit request: `sheet_sync_enabled` now defaults to `True` (was `False`) and `max_retries` now defaults to `10` (was `2`). Both live in `config.DEFAULT_CONFIG`, with matching fallback values updated in `main.py`'s `get_settings()`/`_run_translation_thread()` and the HTML's initial `checked`/`value` attributes in `index.html` (so there's no flash of the old default before JS runs) -- see `app/config.py`, `app/main.py`, `app/web/index.html`. **Important nuance verified explicitly, not assumed**: `config.DEFAULT_CONFIG` only fills in keys that are *absent* from `config.json`. Since `scan()` re-saves the full merged config on every scan, any machine that's ever actually used the app (including this dev machine, extensively, throughout this project's testing) already has explicit `sheet_sync_enabled`/`max_retries` keys on disk from whatever they were at the time -- this change does **not** retroactively flip already-saved settings, only what a genuinely fresh install (no `config.json` yet) starts with. Confirmed by mocking `os.path.exists` to return `False` and checking `load_config()`'s output directly, rather than trying to test this through the GUI (not practical to click through from this environment) or assuming the dict literal alone was sufficient proof.

## 21. The maximize-hang investigation (v1.1.4) -- three attempts, two of them wrong

The user reported: launch the app, try to maximize the window, it goes "Not Responding." This section is deliberately detailed, including the two fixes that were tried and **did not work** (one of which made things worse), because the eventual root cause was in a completely different place than where the investigation started, and that path is worth understanding if anything like this recurs.

### How it was actually reproduced (mechanical detail worth keeping)

Bash-launched GUI processes and the PowerShell tool's session don't reliably share window-handle visibility in this environment -- `Get-Process -Name X | Select MainWindowHandle` sometimes returns `0`/empty for a process that unquestionably exists and has a real window, for no obvious reason tied to elapsed time (sometimes instant, sometimes never within 15+ seconds). **When this happens, just retry the same `Get-Process` call** (a fresh PowerShell invocation, not a longer sleep in the same one) -- it's flaky, not fundamentally broken, and every time in this session it eventually did resolve to a valid handle on a retry. Once a handle is in hand, `ShowWindow(hwnd, SW_MAXIMIZE/SW_RESTORE)` via a `user32.dll` P/Invoke `Add-Type`, toggled rapidly (~20x, 300ms apart) while polling `Get-Process -Id <pid> | Select Responding`, reliably reproduced the hang within the first couple of toggles every time it was actually present. **`Get-Process ... Responding` is the load-bearing check** -- it's implemented via `SendMessageTimeout` under the hood, so it reliably reports `False` for a genuinely hung message pump without itself hanging, unlike naive process-liveness checks.

When a diagnostic PowerShell script itself appears to hang (no output, tool-level timeout fires, command "moves to the background"), **that is itself a data point, not just tooling friction** -- in this investigation it happened because the script's own `ShowWindow` call blocked on a target window whose message pump was already dead, which only "resolved" (with misleading, stale-looking output) once the hung target process was killed from a separate command. Don't dismiss a stuck diagnostic script as noise without checking whether the *target* is actually the thing that's stuck.

**`py-spy dump --pid <pid>`** (`pip install py-spy`; ships a `py-spy.exe` console script, not a `-m py_spy`-invokable module) was what actually cracked this, twice: it attaches to a live process -- even a PyInstaller-frozen one -- and prints every thread's real Python stack. Two dumps a couple seconds apart, compared, is enough to tell "still legitimately working" from "permanently stuck at the exact same line" (the latter, unlike a slow-but-progressing call, doesn't move between dumps at all).

### Attempt 1 (wrong, but not harmful): rename `self.window`/`self.engine` to `self._window`/`self._engine`

A baseline py-spy dump (before touching anything) showed a background thread stuck deep in a **recursive** call to `webview/util.py`'s `get_functions()` -- pywebview's `inject_pywebview()`, which builds the JS-side `window.pywebview.api` bridge by walking every non-underscore, non-callable attribute on the exposed `Api` object, **recursing into any attribute that's itself a complex object**. `Api.window` (the live pywebview `Window`, backed by the entire WinForms/WebView2 COM object graph) was a public attribute, so this walk was descending into that whole graph on every call. This is real and worth fixing on its own merits (renamed to `self._window`, `self._engine`, `self._base_res_path` -- `get_functions()` explicitly skips names starting with `_`) -- **but it did not fix the hang**. A follow-up dump after this fix still showed a thread stuck (see attempt 2) via a *different* path, proving this wasn't the actual trigger for what the user hit. Kept the rename anyway; it's a legitimate improvement (recursing into a COM object graph to build a JS bridge has no upside) even though it wasn't the fix.

### Attempt 2 (actively made it worse): marshal `evaluate_js` onto the GUI thread with `Control.Invoke`

Separately, reading `webview/platforms/winforms.py` showed `window.evaluate_js()` is called with **no thread marshaling at all** in this pywebview version (6.2.1) -- unlike its own `maximize`/`minimize`/`restore`/`clear_cookies`, which all wrap their work in `self.Invoke(Func[Type](...))`. Every `_emit()` call in this app (translation progress, update checks, ...) calls `window.evaluate_js()` from a background thread, so this looked like a real, version-matching bug (there's an open upstream issue, pywebview#1823, about the same unmarshaled-cross-thread-call class of bug on different methods). The fix tried: reach into pywebview's internal `BrowserView.instances` and call `instance.Invoke(Func[Type](lambda: window.evaluate_js(script)))` from `_emit`, mirroring pywebview's own pattern exactly.

**This made the hang trigger on every single launch, unconditionally, no maximize needed** -- confirmed by two py-spy dumps a couple seconds apart showing the GUI/message-pump thread (identifiable by `create (winforms.py:808)` at the base of its stack -- pywebview's WinForms backend spawns the actual window on a dedicated thread, not the Python main thread that calls `webview.start()`) stuck at the exact same line both times: inside the `Invoke`-dispatched delegate, itself blocked in `evaluate_js`'s internal semaphore wait. The mechanism: `window.evaluate_js()` isn't fire-and-forget -- it's a *blocking* call that waits on a semaphore released by a JS-side callback message. `Control.Invoke` runs its delegate synchronously as part of the GUI thread's message dispatch; while that delegate is running, the GUI thread cannot return to its own message loop to receive the very callback that would release the wait it's now stuck in. Self-deadlock, entirely independent of any native resize/maximize event -- **`Invoke` was the wrong primitive for a delegate whose body itself blocks on further message-pump activity.**

Switching `Invoke` to `Control.BeginInvoke` (posts the delegate to the queue and returns immediately, instead of blocking until it's run) was tried next, on the theory that the delegate would then run as a normal dispatched message rather than nested inside another synchronous call. **Also did not fix it** -- a dump showed the exact same stuck-at-the-same-line signature. The dispatch mechanism (`Invoke` vs `BeginInvoke`) was never the actual variable; once the delegate body itself calls the blocking `evaluate_js()`, *any* path that runs it via the GUI thread's own message-triggered dispatch has the same problem, because `evaluate_js`'s internal wait needs that same thread to keep pumping messages to ever resolve.

### Attempt 3 (actually fixed it): stop pushing from Python into JS entirely

The real fix isn't a smarter way to call `window.evaluate_js()` from a background thread -- it's to never do that at all. `Api._emit()` now just appends `{fn_name, args}` to an in-memory list (`self._event_queue`, guarded by `self._event_lock`) instead of touching the window. A new `Api.poll_events()` (a normal, JS-initiated `js_api` call -- the *only* call direction pywebview's whole binding model actually guarantees is safe) drains and returns that queue. `app.js` runs one `setInterval(..., 250)` (`startEventPolling()`, started once in `init()`) that calls `poll_events()` and dispatches each returned event to `window[e.fn](...e.args)` -- i.e. the exact same `window.onTranslationProgress`/`onUpdateCheckResult`/etc. handler functions that already existed, completely unchanged. Only the delivery mechanism changed (push via `evaluate_js` -> pull via polling); every existing event name and handler signature is identical. `_safe_evaluate_js`, the `BrowserView`/pythonnet-`Invoke` reaching-into-internals code, and the now-unused `_js_arg`/`json` import were all deleted -- this ended up *simpler* than either of the two failed attempts, not more complex.

**Verified thoroughly, not just "it built"**: py-spy dumps immediately after launch and again several seconds later showed all threads idle, nothing stuck anywhere near `evaluate_js`. Then the full 20x rapid maximize/restore toggle stress test -- the one that reliably reproduced the original bug within 1-2 toggles every previous time it was run -- came back `Responding=True` for all 20 toggles, twice: once against the raw `dist/AutomateLocalization/` build, and again (after a fresh install/uninstall cycle) against the actual installed copy at its real install path, matching exactly what a real user's update would produce. No crash, no traceback, in either case.

**If a similar hang ever comes back**: don't start from "which pywebview method needs better thread marshaling" -- start with a py-spy dump of the actually-hung process and read what it says literally. Two out of three attempts here were plausible, targeted, and wrong; only the dump-driven ones (baseline vs. post-fix comparison) actually distinguished a real fix from a change that merely felt right.

## 22. Review-screen search filter, and README screenshots (v1.1.5)

**Search filter**: `web/index.html`'s Review screen got a filter input (`#review-filter-input`) above the table, plus a `#review-filter-count` "Showing X of Y" indicator. `app.js`'s `applyReviewFilter()` does a plain case-insensitive substring match against each row's `data-key`/`data-text` (set on the `<tr>` at render time, not read back out of the DOM cells -- avoids re-parsing escaped HTML) and toggles the existing `.hidden` utility class. `select-all`/`select-none` were changed to only touch `tr[data-key]:not(.hidden)` -- deliberately scoped to whatever's currently filtered, not the full list, since silently re-selecting hidden rows the user can't see would be surprising. Verified interactively, not just by reading the code: served `app/web/` over a plain local HTTP server (`file://` renders as an inert static snapshot in this environment's browser tool -- scripts never execute, easy to mistake for a passing test), seeded a fake `scanResult` and a stub `window.pywebview.api` via the JS console, then actually typed into the filter box and clicked select/deselect through the Browser tool -- confirmed filtering by key, filtering by English text, the count indicator, and the visible-only select-all/none scoping all behave correctly, with real keyboard/click events, not synthetic function calls.

**README screenshots** (`docs/screenshots/*.png`): generated, not hand-captured. `scripts/demo_setup.html`, `demo_review.html`, `demo_results.html` each duplicate the relevant slice of `index.html`'s markup with a fake `window.pywebview.api` (realistic sample paths/languages/strings) so the real, unmodified `app/web/app.js` and `style.css` render each screen without a running backend. Rendered headlessly with Edge (`msedge.exe --headless=new --screenshot=... --window-size=... <url>`, served over `python -m http.server` from the repo root so relative paths resolve) rather than relying on the Browser tool's inline screenshots, which have no way to save to a file for the repo. **Two real mistakes made while building these, worth not repeating**: (1) first attempt used `--default-background-color=00000000` (transparent) for a "clean" capture -- this corrupted nearly every text color in the PNG (headless PNG capture doesn't composite a transparent page background correctly); dropped the flag, since the page already sets its own solid `background: var(--bg)`. (2) first attempt at each demo page hand-wrote a trimmed-down `<body>` missing the menu/about-modal markup `wireMenu()`/`wireAboutModal()` expect -- `init()` threw partway through on the missing elements and silently skipped everything after (language picker, recent paths, injected path value all came out empty, with zero visible error in the screenshot itself). Fixed by copying `index.html`'s actual current markup wholesale into each demo page instead of a hand-trimmed guess at what it needed. **If `index.html`'s structure changes, these demo pages will drift out of sync silently the same way** -- there's a comment atop each one saying so; re-diff against the real `index.html` before regenerating screenshots after any structural UI change, don't assume the old copy still matches.

## 23. Language-picker spacing, removable recent-path chips (v1.1.6)

Two small UI requests from a screenshot the user sent (the selected-languages chip row sitting flush against the "Filter languages…" box below it): `.lang-selected-list` got `margin-bottom: 10px` in `style.css`.

**Removable recent paths**: each chip in `#recent-paths` now has a hover-revealed `×` (`.recent-path-remove`, `visibility: hidden` by default, flipped on `.recent-path-chip:hover`). Clicking it calls a new `Api.remove_recent_path(path)` (`main.py` -> `config.remove_recent_path(cfg, path)`, a straightforward list-filter-and-save mirroring the existing `add_recent_path`) and re-renders the chip list client-side rather than re-fetching all of `get_settings()`. The remove click handler calls `e.stopPropagation()` -- without it, the click would bubble to the chip's own listener and fill the path input with the very path just removed. `loadSettings()`'s inline chip-building code was factored out into a standalone `renderRecentPaths(paths)` so both the initial load and a post-removal re-render use the same path.

**Verified functionally, not just read the code**: with the Browser pane's screenshot compositing unavailable in that moment (a real, transient limitation of the tool, not a code issue -- came back on a later session), fell back to the same served-page-plus-JS-console technique as section 22, but purely through `javascript_tool` DOM assertions instead of `computer` clicks: confirmed both chips render with a `.recent-path-remove` child hidden by default, that a direct `.click()` on the `×` calls `remove_recent_path` with the correct path and removes exactly that chip, that doing so leaves `#path-input` untouched (proving `stopPropagation` actually works, not just present in the source), and that clicking the chip body still fills the path input as before (a regression check on existing behavior, not just the new feature). Regenerated `docs/screenshots/setup.png` afterward since the spacing change was visible in it.

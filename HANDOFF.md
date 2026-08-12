# Handoff: Android Localization Desktop App

> **Status as of 2026-08-12: built and working, tested against real translation runs (Gemini) including Google Sheet sync.**
> Sections 1-9 below are the *original* spec this was built from — still accurate as ground truth for the engine logic. If you're continuing this project, read sections 1-9 for context, then jump to **section 10 onward** for what's actually been built, bugs found beyond the original list, how the open questions in section 8 were resolved, and what's not done yet.

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
- No packaging/distribution step (e.g. PyInstaller) -- currently run via `python app/main.py` from source with dependencies installed globally, not in a venv.
- No per-key manual retry from the Results screen (see section 12).

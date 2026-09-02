"""
iOS localization support (Xcode String Catalog / .xcstrings format).

Deliberately separate from engine.py's Android logic rather than shoehorned
in: the workflows are fundamentally different axes. Android scans an
existing strings.xml and diffs many keys against one language at a time,
batched. iOS here has no scan step -- a developer types one English string
at a time, and it gets translated into every selected language in a single
call. Same AI providers, same retry-only-what's-missing philosophy, same
"never overwrite an existing translated value" rule as engine.py, but the
prompt shape, the file format, and the key derivation are all iOS-specific.
"""

import json
import os
import re
import time
from datetime import datetime
from typing import Callable, Optional

# --- iOS language table -------------------------------------------------
# iOS uses standard BCP-47-ish locale identifiers, which differ from
# Android's values-<code> folder convention for a few languages that
# matter here: Indonesian is 'id' (Android historically uses 'in'), and
# Simplified/Traditional Chinese are 'zh-Hans'/'zh-Hant' (Android uses
# 'zh-rCN'/'zh-rTW'). Flags are shared with engine.FLAG_EMOJI where the
# code lines up; iOS-specific codes get their own entries below.

IOS_LANG_DISPLAY_NAMES = {
    'de': 'German', 'es': 'Spanish', 'fr': 'French', 'id': 'Indonesian',
    'it': 'Italian', 'ja': 'Japanese', 'ko': 'Korean', 'pt-BR': 'Portuguese (Brazil)',
    'pt-PT': 'Portuguese (Portugal)', 'ru': 'Russian', 'zh-Hans': 'Chinese (Simplified)',
    'zh-Hant': 'Chinese (Traditional)', 'ar': 'Arabic', 'hi': 'Hindi', 'nl': 'Dutch',
    'pl': 'Polish', 'tr': 'Turkish', 'th': 'Thai', 'vi': 'Vietnamese', 'sv': 'Swedish',
    'da': 'Danish', 'fi': 'Finnish', 'nb': 'Norwegian Bokmal', 'cs': 'Czech',
    'el': 'Greek', 'he': 'Hebrew', 'hu': 'Hungarian', 'ro': 'Romanian', 'sk': 'Slovak',
    'uk': 'Ukrainian', 'ca': 'Catalan', 'fa': 'Persian', 'ms': 'Malay', 'sr': 'Serbian',
    'hr': 'Croatian', 'bg': 'Bulgarian', 'lt': 'Lithuanian', 'lv': 'Latvian',
    'et': 'Estonian', 'sl': 'Slovenian', 'sw': 'Swahili', 'ta': 'Tamil', 'te': 'Telugu',
    'bn': 'Bengali', 'ur': 'Urdu', 'km': 'Khmer', 'my': 'Burmese', 'ne': 'Nepali',
    'si': 'Sinhala', 'am': 'Amharic',
}

# Best-effort flags, mirroring engine.FLAG_EMOJI with iOS-specific codes added.
IOS_FLAG_EMOJI = {
    'de': '🇩🇪', 'es': '🇪🇸', 'fr': '🇫🇷', 'id': '🇮🇩', 'it': '🇮🇹', 'ja': '🇯🇵',
    'ko': '🇰🇷', 'pt-BR': '🇧🇷', 'pt-PT': '🇵🇹', 'ru': '🇷🇺', 'zh-Hans': '🇨🇳',
    'zh-Hant': '🇹🇼', 'ar': '🇸🇦', 'hi': '🇮🇳', 'nl': '🇳🇱', 'pl': '🇵🇱', 'tr': '🇹🇷',
    'th': '🇹🇭', 'vi': '🇻🇳', 'sv': '🇸🇪', 'da': '🇩🇰', 'fi': '🇫🇮', 'nb': '🇳🇴',
    'cs': '🇨🇿', 'el': '🇬🇷', 'he': '🇮🇱', 'hu': '🇭🇺', 'ro': '🇷🇴', 'sk': '🇸🇰',
    'uk': '🇺🇦', 'ca': '🇪🇸', 'fa': '🇮🇷', 'ms': '🇲🇾', 'sr': '🇷🇸', 'hr': '🇭🇷',
    'bg': '🇧🇬', 'lt': '🇱🇹', 'lv': '🇱🇻', 'et': '🇪🇪', 'sl': '🇸🇮', 'sw': '🇰🇪',
    'ta': '🇮🇳', 'te': '🇮🇳', 'bn': '🇧🇩', 'ur': '🇵🇰', 'km': '🇰🇭', 'my': '🇲🇲',
    'ne': '🇳🇵', 'si': '🇱🇰', 'am': '🇪🇹',
}

# Pre-checked default set: the same 10 languages engine.LEGACY_LANG_MAP
# handles for Android, translated to iOS locale codes, plus pt-PT as the
# one extra -- Android ships a single Portuguese variant, iOS apps
# conventionally ship both Brazil and Portugal.
IOS_DEFAULT_CODES = [
    'de', 'es', 'fr', 'ja', 'ko', 'pt-BR', 'pt-PT', 'ru', 'it', 'id', 'zh-Hans',
]


def get_all_ios_language_options():
    """Full list of {code, display_name, flag, is_default} for the iOS language picker."""
    options = []
    for code, name in IOS_LANG_DISPLAY_NAMES.items():
        options.append({
            'code': code,
            'display_name': name,
            'flag': IOS_FLAG_EMOJI.get(code, '🌐'),
            'is_default': code in IOS_DEFAULT_CODES,
        })
    options.sort(key=lambda o: o['display_name'])
    return options


# --- Key generation -------------------------------------------------------

# '.' and line breaks are treated as word separators (-> underscore), same
# as whitespace -- not just stripped. Handling this as its own pass, before
# the generic strip below, matters for text where a period isn't already
# adjacent to whitespace: "Hello.World" must become "hello_world", not
# "helloworld" (which is what stripping the period outright would produce,
# since with nothing whitespace-like next to it there'd be nothing left to
# collapse into a separator).
#
# "Line break" here means both an actual newline/tab character AND the
# literal two-character sequence '\n'/'\t' (backslash then a letter) --
# real-world text pasted in from a JSON snippet, a Sheet cell, or similar
# commonly carries the *escaped* form rather than a real control character.
# Without matching that too, "Device.\nPlease" (literal backslash-n) comes
# out as "..._device_nplease_..." -- the backslash gets stripped by the
# generic pass below same as any other punctuation, but the 'n' survives
# since it's alphanumeric, silently fusing onto the next word. Confirmed
# this exact bug from a real screenshot during testing, not hypothetical.
_KEY_SEPARATOR_RE = re.compile(r"\\n|\\t|[.\n\t]")
_KEY_STRIP_RE = re.compile(r"[^a-z0-9\s]")
_KEY_WHITESPACE_RE = re.compile(r"\s+")


def generate_key(english_text):
    """
    Derives an .xcstrings-style key from English text the way iOS devs do
    it by hand: lowercase, treat '.' and line breaks as word separators,
    drop remaining punctuation/special characters, collapse all whitespace
    into single underscores.

    "A request has been sent to Receiver Device.\\nPlease accept it to continue."
    -> "a_request_has_been_sent_to_receiver_device_please_accept_it_to_continue"
    """
    lowered = english_text.lower()
    with_separators = _KEY_SEPARATOR_RE.sub(" ", lowered)
    stripped = _KEY_STRIP_RE.sub("", with_separators)
    collapsed = _KEY_WHITESPACE_RE.sub("_", stripped.strip())
    return collapsed.strip("_")


# --- Catalog file I/O -------------------------------------------------------

def load_catalog(path):
    """
    Returns the parsed .xcstrings JSON dict, or a fresh empty catalog if
    the file doesn't exist yet. Returns None if the file exists but fails
    to parse -- callers must treat that as "do not touch this file", same
    rule as engine.get_existing_strings.
    """
    if not os.path.exists(path):
        return {"sourceLanguage": "en", "strings": {}, "version": "1.1"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "strings" not in data or not isinstance(data["strings"], dict):
            return None
        return data
    except Exception:
        return None


def save_catalog(path, catalog):
    """Writes the catalog back as UTF-8 JSON, matching Xcode's own formatting
    (2-space indent, non-ASCII left as literal characters, not \\u escapes)."""
    dir_path = os.path.dirname(path)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def add_string_to_catalog(catalog, key, english_text, translations, context=""):
    """
    Merges one string's translations into the catalog dict in place.
    Never overwrites an existing localization -- if the key already
    exists, only fills in languages that aren't already present there,
    mirroring engine.append_to_xml_file's "never touch an existing
    translated string" rule. Returns {'added': [codes], 'skipped_existing':
    [codes]} so the caller can report exactly what happened.

    context, if given, is stored as the entry's "comment" -- the same
    field Xcode itself populates from NSLocalizedString(..., comment: "..."),
    shown to translators in Xcode's own String Catalog editor. Only ever
    set if the entry doesn't already have a non-empty comment -- same
    never-overwrite rule as the localizations themselves, just applied to
    this field too.
    """
    strings = catalog.setdefault("strings", {})
    entry = strings.get(key)
    if entry is None:
        entry = {"extractionState": "manual", "localizations": {}}
        strings[key] = entry
    localizations = entry.setdefault("localizations", {})

    if context and not entry.get("comment"):
        entry["comment"] = context

    added = []
    skipped = []

    if "en" not in localizations:
        localizations["en"] = {"stringUnit": {"state": "translated", "value": english_text}}
        added.append("en")

    for code, text in translations.items():
        if code in localizations:
            skipped.append(code)
            continue
        localizations[code] = {"stringUnit": {"state": "needs_review", "value": text}}
        added.append(code)

    return {"added": added, "skipped_existing": skipped}


# --- Translation: one string, many languages (the inverse of engine.py's
# many-keys-one-language batching) ------------------------------------------

_MULTI_ESCAPE_RE = re.compile(r'\\+([nt])')


def _collapse_line_break_escapes(text):
    """Collapses a literal backslash-n/backslash-t the model wrote as text
    back into a real newline/tab character, mirroring engine._collapse_escapes."""
    return _MULTI_ESCAPE_RE.sub(lambda m: {'n': '\n', 't': '\t'}[m.group(1)], text)


def translate_string_to_languages(provider, client, text, context, target_langs):
    """
    Translates one string into every language in target_langs (a dict of
    {code: display_name}) with a single AI call. Returns {code: translated_text}
    for whatever languages actually came back.
    """
    if not target_langs or not client:
        return {}

    lang_names = list(target_langs.values())
    instructions = (
        "Translate this iOS app string into the following languages: "
        + ", ".join(lang_names) + ".\n"
        "Preserve iOS placeholder tokens exactly as they appear (%@, %d, %ld, %lld, "
        "%1$@, %2$@, and similar). If the source text contains a line break, represent "
        "it in your translation as the two literal characters \\n rather than an actual "
        "line break -- do not output a real newline inside a translation. "
        "Return ONLY 'LanguageName: TranslatedText' pairs, one pair per line, in the "
        "exact same language order as given above, using those exact language names. "
        "Do not use markdown, bullet points, code fences, or blank lines.\n\n"
        f"Text: {text}" + (f"\nContext: {context}" if context else "")
    )

    try:
        if provider == "gemini":
            response = client.generate_content(instructions)
            text_out = response.text
        else:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": instructions}],
                temperature=0.2,
            )
            text_out = response.choices[0].message.content

        name_to_code = {name: code for code, name in target_langs.items()}
        results = {}
        for line in text_out.strip().split('\n'):
            if ':' not in line:
                continue
            name, val = line.split(':', 1)
            name, val = name.strip(), val.strip()
            code = name_to_code.get(name)
            if code and val:
                results[code] = _collapse_line_break_escapes(val)
        return results
    except Exception as e:
        raise RuntimeError(f"{provider.upper()} error during translation: {e}") from e


def _chunk_lang_dict(d, size):
    """Same idea as engine.py's chunk_dict (not imported -- see this
    module's docstring for why it deliberately doesn't depend on
    engine.py), applied to target languages instead of keys."""
    items = list(d.items())
    for i in range(0, len(items), max(1, size)):
        yield dict(items[i:i + size])


def translate_string_with_retry(provider, client, text, context, target_langs,
                                 max_retries=2, batch_size=25,
                                 on_retry: Optional[Callable[[int, int], None]] = None):
    """
    Translates into every language in target_langs, retrying only the
    languages that didn't come back. Returns (results, still_missing_codes).

    Languages are batched `batch_size` at a time per AI call, same
    truncation-avoidance principle as Android's batch translation
    (engine.py's chunk_dict, see HANDOFF's "do not remove this" note) --
    asking one call to translate a string into a large number of languages
    at once risks the same silent truncation batching by key already fixes
    for Android. With the default ~10-11 selected languages this rarely
    produces more than one batch; it only matters once a user selects
    enough languages to approach `batch_size`. `max_retries` and
    `batch_size` both come from the same shared Settings values Android's
    batching already uses (`app/config.py`'s `max_retries`/`batch_size`),
    not separate iOS-only settings.
    """
    results = {}
    still_missing = []
    for batch_langs in _chunk_lang_dict(target_langs, batch_size):
        pending = dict(batch_langs)
        attempt = 0
        while pending and attempt <= max_retries:
            attempt += 1
            try:
                chunk_results = translate_string_to_languages(provider, client, text, context, pending)
            except RuntimeError:
                chunk_results = {}
            for code, val in chunk_results.items():
                if code in pending:
                    results[code] = val
            pending = {code: name for code, name in pending.items() if code not in results}
            if pending and attempt <= max_retries:
                if on_retry:
                    on_retry(attempt, len(pending))
                time.sleep(1)
        still_missing.extend(pending.keys())
    return results, still_missing


def build_sheet_rows_for_session(session_entries, lang_display_names):
    """
    Builds {key: {'English': ..., display_name: value, ...}} for the
    strings added in the current iOS session, matching the shape
    engine.build_sheet_rows produces for Android's Sheet export.
    session_entries: list of {'key', 'english_text', 'translations': {code: text}}
    """
    master_sheet = {}
    for item in session_entries:
        row = {'English': item['english_text']}
        for code, text in item['translations'].items():
            display_name = lang_display_names.get(code, code)
            row[display_name] = text
        master_sheet[item['key']] = row
    return master_sheet


def _client_email(service_account_path):
    """Best-effort read of just the client_email field, for a clearer
    permission-error message below -- never raises, "" on any failure."""
    try:
        with open(service_account_path, "r", encoding="utf-8") as f:
            return json.load(f).get("client_email", "")
    except Exception:
        return ""


def _open_sheet(gs_client, sheet_id, service_account_path):
    """gspread wraps a 403 in a bare, message-less PermissionError -- see
    engine._open_sheet's docstring (identical fix, this module deliberately
    doesn't import engine.py, see the module docstring, so it's duplicated
    here rather than shared)."""
    try:
        return gs_client.open_by_key(sheet_id)
    except PermissionError as e:
        email = _client_email(service_account_path)
        who = f" ({email})" if email else ""
        raise PermissionError(
            f"This service account{who} doesn't have access to this sheet. "
            "Share the sheet with that address as an Editor, then try again."
        ) from e


def sync_ios_to_google_sheet(sheet_id, service_account_path, provider_name, master_sheet, lang_display_list):
    """Same tab-per-run export as engine.sync_to_google_sheet, labeled for iOS."""
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(service_account_path, scope)
    gs_client = gspread.authorize(creds)
    sheet = _open_sheet(gs_client, sheet_id, service_account_path)

    tab_name = f"{provider_name.capitalize()} iOS Localization - {datetime.now().strftime('%b %d, %Y %I_%M %p')}"
    tab = sheet.add_worksheet(title=tab_name, rows=str(len(master_sheet) + 10), cols="20")

    # No "Key" column, languages alphabetized by display name (English
    # first) -- see engine.sync_to_google_sheet's identical comment for why
    # (matches the shape of externally-round-tripped sheets, and Import
    # already tolerates a key-less tab).
    sorted_langs = sorted(lang_display_list)
    headers = ["English"] + sorted_langs
    tab.append_row(headers)

    rows = [[d.get('English', '')] + [d.get(l, "") for l in sorted_langs] for d in master_sheet.values()]
    if rows:
        tab.append_rows(rows)

    return tab_name

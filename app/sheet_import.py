"""
Reads rows back from a Google Sheet tab and writes them into local Android
strings.xml / iOS .xcstrings files -- the reverse direction of
engine.sync_to_google_sheet / ios_engine.sync_ios_to_google_sheet.

Deliberately does NOT duplicate any write logic: writing to Android reuses
engine.append_to_xml_file (never overwrites an existing key, creates the
values-<code>/ folder if missing, same as every other Android write path
in this app); writing to iOS reuses ios_engine.add_string_to_catalog +
save_catalog (never overwrites an existing localization). This module's
only real job is bridging the Sheet's plain-text column headers ("German",
"Portuguese (Brazil)", ...) back to the internal language codes each
platform actually uses -- which is genuinely platform-dependent, not a
fixed mapping, since the same header text means a different code on
Android vs iOS (see _android_reverse_lang_map's docstring for the messiest
case, Portuguese/Indonesian).
"""

import engine
import ios_engine


def _get_gspread_client(service_account_path):
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(service_account_path, scope)
    return gspread.authorize(creds)


def list_worksheets(sheet_id, service_account_path):
    client = _get_gspread_client(service_account_path)
    sheet = client.open_by_key(sheet_id)
    return [ws.title for ws in sheet.worksheets()]


def fetch_sheet_rows(sheet_id, service_account_path, tab_name):
    """
    Returns {'headers': [lang display names present], 'rows': [{'key',
    'english', 'values': {header: value}, 'key_was_generated'}]}.

    Only an "English" column is actually required. A "Key" column is
    common (every tab this app's own Sheet sync produces has one) but not
    mandatory -- a sheet a translator built by hand, or exported from
    somewhere else, might just have English + language columns with no
    key at all. When the Key column is missing entirely, or a specific
    row's Key cell is empty while its English cell isn't, a key is
    auto-generated from that row's English text with
    ios_engine.generate_key -- the same lowercase-and-underscore
    convention iOS's "Add a string" screen already uses, reused here since
    "make a slug from English text" isn't actually iOS-specific, it just
    happened to be built there first. key_was_generated flags which rows
    this happened for, so the UI can show it rather than silently
    presenting a made-up key as if the sheet had specified it.

    Rows with no usable English text are skipped entirely -- there's
    nothing to derive a key from or anything to write. Raises ValueError
    only if there's no "English" column at all, since at that point
    there's nothing in the tab this function can work with.
    """
    client = _get_gspread_client(service_account_path)
    sheet = client.open_by_key(sheet_id)
    ws = sheet.worksheet(tab_name)
    all_values = ws.get_all_values()
    if not all_values:
        return {"headers": [], "rows": []}

    headers = all_values[0]
    try:
        eng_idx = headers.index("English")
    except ValueError:
        raise ValueError('This tab doesn\'t have an "English" column -- expected a tab this app generated via Sheet sync (or one shaped like it).')

    key_idx = headers.index("Key") if "Key" in headers else None
    skip_idxs = {eng_idx} if key_idx is None else {eng_idx, key_idx}
    lang_headers = [h for i, h in enumerate(headers) if i not in skip_idxs and h]

    rows = []
    for raw_row in all_values[1:]:
        if len(raw_row) <= eng_idx:
            continue
        english = raw_row[eng_idx].strip()
        if not english:
            continue

        key = ""
        if key_idx is not None and key_idx < len(raw_row):
            key = raw_row[key_idx].strip()
        key_was_generated = not key
        if key_was_generated:
            key = ios_engine.generate_key(english)
            if not key:
                continue  # English text had nothing alphanumeric to derive a key from

        values = {}
        for i, h in enumerate(headers):
            if i in skip_idxs or not h:
                continue
            if i < len(raw_row) and raw_row[i].strip():
                values[h] = raw_row[i].strip()
        rows.append({"key": key, "english": english, "values": values, "key_was_generated": key_was_generated})

    return {"headers": lang_headers, "rows": rows}


def _android_reverse_lang_map():
    """
    Sheet column header -> Android language code. Two real ambiguities,
    both a consequence of engine.py's own design, not something invented
    here:
    - "Indonesian" could have come from either the 'in' or 'id' folder
      (engine.LANG_DISPLAY_NAMES maps both to the same display name) --
      prefers 'in', matching LEGACY_LANG_MAP / the reference script.
    - A 'pt' column could read "Portuguese" (auto-detected from an
      existing values-pt/ folder, via classify_values_folder) or
      "Portuguese (Brazil)" (created through the legacy-default language
      picker, which uses LEGACY_LANG_MAP's naming) depending on how that
      folder came to exist. Both are accepted and map back to 'pt'.
    """
    reverse = {}
    for code, name in engine.LANG_DISPLAY_NAMES.items():
        reverse.setdefault(name, code)
    for code, name in engine.LEGACY_LANG_MAP.items():
        reverse[name] = code
    return reverse


def _ios_reverse_lang_map():
    return {name: code for code, name in ios_engine.IOS_LANG_DISPLAY_NAMES.items()}


def import_to_android(base_res_path, selected_rows):
    """
    selected_rows: the subset of fetch_sheet_rows()'s 'rows' the user
    checked. Writes the English column into values/strings.xml and every
    recognized language column into its values-<code>/strings.xml,
    creating folders as needed -- one append_to_xml_file call per target,
    each independently try/excepted so one unparseable existing file
    doesn't abort the whole import (same principle as engine.run()'s
    per-language handling).
    Returns {'written': {display_name: count}, 'failures': {display_name:
    error}, 'unrecognized_columns': [...]}.
    """
    reverse_map = _android_reverse_lang_map()
    written = {}
    failures = {}

    def _write(folder, data, label):
        if not data:
            return
        try:
            count = engine.append_to_xml_file(base_res_path, folder, data)
            if count:
                written[label] = written.get(label, 0) + count
        except Exception as e:
            failures[label] = str(e)

    english_data = {r["key"]: r["english"] for r in selected_rows}
    _write("values", english_data, "English")

    unrecognized_columns = set()
    per_lang_data = {}
    for row in selected_rows:
        for header, value in row["values"].items():
            code = reverse_map.get(header)
            if not code:
                unrecognized_columns.add(header)
                continue
            per_lang_data.setdefault(code, {})[row["key"]] = value

    for code, data in per_lang_data.items():
        _write(f"values-{code}", data, engine.LANG_DISPLAY_NAMES.get(code, code))

    return {"written": written, "failures": failures, "unrecognized_columns": sorted(unrecognized_columns)}


def import_to_ios(catalog_path, selected_rows):
    """
    Same idea for a .xcstrings catalog. Returns {'written_keys': n,
    'unrecognized_columns': [...]} or raises if the catalog can't be
    loaded/saved -- callers should treat that as "do not touch this file",
    same rule as everywhere else in this app.
    """
    reverse_map = _ios_reverse_lang_map()

    catalog = ios_engine.load_catalog(catalog_path)
    if catalog is None:
        raise RuntimeError(f"{catalog_path} exists but could not be parsed as a valid .xcstrings file -- refusing to write to it.")

    unrecognized_columns = set()
    written_keys = 0
    for row in selected_rows:
        translations = {}
        for header, value in row["values"].items():
            code = reverse_map.get(header)
            if not code:
                unrecognized_columns.add(header)
                continue
            translations[code] = value
        ios_engine.add_string_to_catalog(catalog, row["key"], row["english"], translations)
        written_keys += 1

    ios_engine.save_catalog(catalog_path, catalog)
    return {"written_keys": written_keys, "unrecognized_columns": sorted(unrecognized_columns)}

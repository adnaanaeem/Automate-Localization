"""
================================================================================
ANDROID LOCALIZATION AUTOMATION (Gemini + OpenAI + Google Sheets)  -- FIXED
================================================================================

WHAT CHANGED FROM THE ORIGINAL SCRIPT AND WHY
-----------------------------------------------
1. "New string" detection is now per-language, not just a diff against German.
   The original script compared English only to values-de/strings.xml, so any
   language that had fallen behind English for reasons unrelated to a given
   run (a manually edited file, a previous partial failure, etc.) never got
   backfilled. Now each language's own strings.xml is checked independently.

2. Translation requests are now sent in small batches (BATCH_SIZE) instead of
   one giant prompt containing every missing string. A single huge prompt can
   get truncated by the model's output limit, and the old code had no way to
   detect that -- it just silently kept whatever came back. Batching plus a
   per-batch retry means a partial/garbled response no longer causes strings
   to vanish.

3. After translating, the script checks which requested keys actually came
   back and retries the missing ones. Anything still missing after retries is
   printed in a clear summary at the end instead of disappearing silently.

4. XML escaping is more correct: real markup (<b>, <i>, etc.) is detected
   with a proper tag regex and wrapped in CDATA; everything else goes through
   proper XML escaping (&, ", ') instead of only handling apostrophes.

5. Existing localized strings are NEVER touched. append_to_xml_file only ever
   inserts strings whose key is not already present in the target file, and
   if a target file fails to parse, that file is skipped entirely (with a
   loud warning) rather than guessed-at, to avoid corrupting or duplicating
   content.

6. API keys are now read from environment variables, not hardcoded.
   IMPORTANT: the previous version of this script had live-looking Gemini and
   OpenAI API keys pasted directly into the source. If those keys are real,
   treat them as compromised (they were shared in a chat transcript) and
   rotate/revoke them in Google AI Studio and the OpenAI dashboard, then set
   the new ones as environment variables (or in a .env file you don't commit):
       export GEMINI_API_KEY="..."
       export OPENAI_API_KEY="..."

STEP 1: INSTALL LIBRARIES
--------------------------------------------------------------
python -m pip install lxml google-generativeai openai gspread oauth2client

STEP 2: PREREQUISITES
---------------------
1. GOOGLE SHEETS:
   - Go to Google Cloud Console, enable "Google Sheets API".
   - Create a "Service Account", download the JSON key.
   - Rename the JSON file to 'service_account.json' and put it in this folder.
   - SHARE your Google Sheet with the email address found in the JSON file.

2. AI KEYS (set as environment variables, do not hardcode them):
   - Gemini: https://aistudio.google.com/
   - OpenAI: https://platform.openai.com/

STEP 3: PROJECT STRUCTURE
-------------------------
- This script should be in your Android root or a subfolder.
- Ensure 'BASE_RES_PATH' below points to your 'src/main/res' folder.
================================================================================
"""

import os
import re
import time
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

import lxml.etree as ET
import google.generativeai as genai
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GOOGLE_SHEET_ID = "your-google-sheet-id-here"  # the ID segment from the sheet's URL
BASE_RES_PATH = "app/src/main/res"

# How many strings to send to the model per translation call. Keep this small
# enough that the model's response can never be truncated.
BATCH_SIZE = 25
MAX_RETRIES_PER_BATCH = 2

# Map Android folder suffixes to Language names for the AI
LANG_MAP = {
    'values-de': 'German', 'values-es': 'Spanish', 'values-fr': 'French',
    'values-in': 'Indonesian', 'values-it': 'Italian', 'values-ja': 'Japanese',
    'values-ko': 'Korean', 'values-pt': 'Portuguese (Brazil)', 'values-ru': 'Russian',
    'values-zh-rCN': 'Chinese (Simplified)'
}

# English-only folders that just receive the raw English string (Screen variants)
VAR_FOLDERS = [
    'values-land', 'values-sw600dp', 'values-sw600dp-land',
    'values-sw680dp', 'values-sw680dp-land', 'values-sw700dp', 'values-sw700dp-land'
]

TAG_RE = re.compile(r'</?[a-zA-Z][a-zA-Z0-9]*[^<>]*>')

# --- AI SETUP FUNCTIONS ---

def get_available_gemini_model():
    """Finds a working Gemini model for your specific API key."""
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY environment variable is not set.")
        return None
    print("🔍 Testing Gemini API Key and finding available models...")
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

        priority = ['models/gemini-1.5-flash', 'models/gemini-1.5-flash-latest', 'models/gemini-pro']
        for target in priority:
            if target in available_models:
                print(f"✅ Found working model: {target}")
                return genai.GenerativeModel(target)

        if available_models:
            print(f"⚠️ Preferred models not found. Using fallback: {available_models[0]}")
            return genai.GenerativeModel(available_models[0])

        return None
    except Exception as e:
        print(f"❌ Gemini Setup Error: {e}")
        return None


def setup_openai():
    """Initializes the OpenAI Client."""
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY environment variable is not set.")
        return None
    print("✅ Using OpenAI Provider: gpt-4o-mini")
    return OpenAI(api_key=OPENAI_API_KEY)

# --- CORE LOGIC ---

def get_eng_strings_with_context():
    """Reads main English strings and captures 'description' attribute for context."""
    path = os.path.join(BASE_RES_PATH, 'values', 'strings.xml')
    if not os.path.exists(path):
        print(f"❌ Error: English file not found at {path}")
        return {}

    tree = ET.parse(path)
    results = {}
    for s in tree.getroot().findall('string'):
        if s.get('translatable') != 'false' and s.get('name') and s.text:
            results[s.get('name')] = {
                'text': s.text,
                'context': s.get('description') or ""
            }
    return results


def get_existing_strings(path):
    """
    Returns {name: text} for every <string> already present in a strings.xml
    file. Returns {} if the file doesn't exist yet. Returns None if the file
    exists but could not be parsed -- callers should treat that as "do not
    touch this file" rather than guessing.
    """
    if not os.path.exists(path):
        return {}
    try:
        tree = ET.parse(path)
        return {
            s.get('name'): (s.text if s.text is not None else "")
            for s in tree.getroot().findall('string')
            if s.get('name')
        }
    except Exception as e:
        print(f"⚠️ Could not parse {path} ({e}). Skipping this file so nothing gets corrupted.")
        return None


def chunk_dict(d, size):
    """Yields successive dict chunks of at most `size` items."""
    items = list(d.items())
    for i in range(0, len(items), size):
        yield dict(items[i:i + size])


def translate_batch(provider, client, batch_data, target_lang):
    """Sends a batch of strings to the selected AI provider."""
    if not batch_data or not client:
        return {}

    prompt_items = [
        f"Key: {k}\nText: {v['text']}" + (f"\nContext: {v['context']}" if v['context'] else "")
        for k, v in batch_data.items()
    ]

    instructions = (
        f"Translate these Android strings into {target_lang}. "
        "Preserve HTML tags (<b>, <i>) and placeholders (%s, %d). "
        "Return ONLY 'Key: TranslatedText' pairs, one pair per line, in the exact "
        "same key order as given. Do not use markdown, bullet points, code fences, "
        "or blank lines. If the source text has no line break, your translation "
        "must not contain a line break either. Copy escape sequences like \\n, \\t, "
        "and \\' exactly as they appear -- do not add extra backslashes to them and "
        "do not convert them into actual line breaks.\n\n" +
        "\n---\n".join(prompt_items)
    )

    try:
        if provider == "gemini":
            response = client.generate_content(instructions)
            text_out = response.text
        else:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": instructions}],
                temperature=0.2
            )
            text_out = response.choices[0].message.content

        lines = text_out.strip().split('\n')
        result = {}
        for l in lines:
            if ':' not in l:
                continue
            key, val = l.split(':', 1)
            key, val = key.strip(), val.strip()
            # Only accept keys we actually asked about -- guards against the
            # model echoing headers, notes, or malformed lines as fake keys.
            if key in batch_data and val:
                result[key] = val
        return result
    except Exception as e:
        print(f"❌ {provider.upper()} Error during {target_lang} translation: {e}")
        return {}


def translate_batch_with_retry(provider, client, batch_data, target_lang, max_retries=MAX_RETRIES_PER_BATCH):
    """
    Translates a batch, and retries only the keys that didn't come back.
    Returns (results, still_missing) so callers can report real failures
    instead of silently losing strings.
    """
    results = {}
    pending = dict(batch_data)
    attempt = 0
    while pending and attempt <= max_retries:
        attempt += 1
        chunk_results = translate_batch(provider, client, pending, target_lang)
        for k, v in chunk_results.items():
            if k in pending:
                results[k] = v
        pending = {k: v for k, v in pending.items() if k not in results}
        if pending and attempt <= max_retries:
            print(f"   ↻ retry {attempt}: {len(pending)} key(s) missing for {target_lang}, retrying...")
            time.sleep(1)
    return results, pending


_MULTI_ESCAPE_RE = re.compile(r'\\+([nt\'"\\])')


def _collapse_escapes(text):
    """
    Collapses any run of one-or-more backslashes immediately followed by an
    Android escape character (n, t, ', ", \\) down to the single literal
    character it represents. This is what makes normalization idempotent no
    matter how many stray backslashes ended up in the text -- both "\\n"
    (correct) and "\\\\n" (the AI double-escaping it during translation)
    collapse to the same real newline character.
    """
    return _MULTI_ESCAPE_RE.sub(
        lambda m: {'n': '\n', 't': '\t', "'": "'", '"': '"', '\\': '\\'}[m.group(1)],
        text
    )


def escape_android_string(text):
    """Escapes a literal string for Android string-resource syntax, exactly once."""
    text = text.replace('\\', '\\\\')
    text = text.replace('\n', '\\n').replace('\t', '\\t')
    text = text.replace("'", "\\'")
    return text


def format_string_value(val):
    """Escapes a translated string for insertion into Android strings.xml."""
    if TAG_RE.search(val):
        # Contains real markup (e.g. <b>...</b>) -- preserve it via CDATA.
        return f'<![CDATA[{val}]]>'

    # Normalize first: collapse whatever escaping is already present in the
    # value (correct, missing, or -- as with the AI sometimes turning "\n"
    # into "\\n" during translation -- wrong) down to literal characters,
    # then re-escape exactly once, ourselves. This is what prevents a stray
    # extra backslash from ever reaching the XML file and breaking the build.
    literal = _collapse_escapes(val)
    escaped = escape_android_string(literal)
    escaped = xml_escape(escaped, {'"': '&quot;'})
    return escaped


def append_to_xml_file(folder, data_dict):
    """
    Surgical Append: Finds </resources> and inserts new strings before it.
    This preserves existing formatting and never overwrites an existing key.
    """
    if not data_dict:
        return

    dir_path = os.path.join(BASE_RES_PATH, folder)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    path = os.path.join(dir_path, 'strings.xml')

    existing_strings = get_existing_strings(path)
    if existing_strings is None:
        print(f"⛔ Skipping write to {path} -- file could not be parsed safely.")
        return
    existing_keys = existing_strings.keys()

    new_entries = []
    for key, val in data_dict.items():
        if key not in existing_keys:
            new_entries.append(f'    <string name="{key}">{format_string_value(val)}</string>')

    if not new_entries:
        return

    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        insert_pos = content.rfind('</resources>')
        if insert_pos != -1:
            new_text = "\n" + "\n".join(new_entries) + "\n"
            updated_content = content[:insert_pos] + new_text + content[insert_pos:]
            with open(path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            print(f"✅ {folder}: +{len(new_entries)} new strings.")
        else:
            print(f"⚠️ {folder}: couldn't find </resources> in {path}, skipping write.")
    else:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n')
            f.write("\n".join(new_entries))
            f.write('\n</resources>')
        print(f"✅ {folder}: Created new file with {len(new_entries)} strings.")


def main():
    print("\n--- Android Localization Automator ---")
    choice = input("Select AI Provider (1: Gemini, 2: OpenAI) [Default: 1]: ")
    is_gemini = False if choice == "2" else True

    provider_name = "gemini" if is_gemini else "openai"
    client_obj = get_available_gemini_model() if is_gemini else setup_openai()

    if not client_obj:
        print("❌ AI setup failed. Check your API keys and internet connection.")
        return

    print("🚀 Reading English source strings...")
    eng_data = get_eng_strings_with_context()
    if not eng_data:
        return
    print(f"📦 English source has {len(eng_data)} translatable strings.")

    master_sheet = {}
    failures = {}  # lang -> [keys still missing after retries]

    # Load each language's current strings once, up front. Reused both to
    # figure out what's missing per language AND, later, to backfill the QA
    # sheet with translations that already exist but weren't touched this
    # run, so the sheet shows the full cross-language picture per key.
    existing_by_folder = {}
    for folder, lang in LANG_MAP.items():
        lang_path = os.path.join(BASE_RES_PATH, folder, 'strings.xml')
        strings = get_existing_strings(lang_path)
        if strings is None:
            print(f"⛔ {lang} ({folder}): file could not be parsed safely, skipping entirely.")
        existing_by_folder[folder] = strings

    # 1. Localize each language independently, based on what THAT language
    #    is actually missing (not just a diff against German).
    for folder, lang in LANG_MAP.items():
        existing = existing_by_folder[folder]
        if existing is None:
            continue

        missing_keys = [k for k in eng_data if k not in existing]
        if not missing_keys:
            print(f"✅ {lang}: already up to date.")
            continue

        print(f"🌍 {lang}: {len(missing_keys)} string(s) missing. Translating in batches of {BATCH_SIZE}...")
        to_do = {k: eng_data[k] for k in missing_keys}
        lang_results = {}

        for chunk in chunk_dict(to_do, BATCH_SIZE):
            results, still_missing = translate_batch_with_retry(provider_name, client_obj, chunk, lang)
            lang_results.update(results)
            if still_missing:
                failures.setdefault(lang, []).extend(still_missing.keys())
            time.sleep(2 if is_gemini else 0.5)

        if lang_results:
            append_to_xml_file(folder, lang_results)
            for k, v in lang_results.items():
                master_sheet.setdefault(k, {'English': eng_data[k]['text']})[lang] = v
                existing_by_folder[folder][k] = v  # keep our in-memory snapshot current

    # 2. Update English Variants (no translation needed), also diffed per folder.
    for folder in VAR_FOLDERS:
        var_path = os.path.join(BASE_RES_PATH, folder, 'strings.xml')
        existing = get_existing_strings(var_path)
        if existing is None:
            print(f"⛔ Skipping variant {folder} -- existing file could not be parsed safely.")
            continue
        missing_keys = [k for k in eng_data if k not in existing]
        if not missing_keys:
            continue
        variant_data = {k: eng_data[k]['text'] for k in missing_keys}
        append_to_xml_file(folder, variant_data)

    if failures:
        print("\n⚠️ These strings could NOT be translated after retries -- fix manually or rerun:")
        for lang, keys in failures.items():
            print(f"   {lang}: {', '.join(sorted(set(keys)))}")

    if not master_sheet:
        print("\n💡 Nothing new to add anywhere. Everything is up to date.")
        return

    # 3. Backfill: for every key that got at least one new translation this
    #    run, also pull in whatever it ALREADY has in the other languages, so
    #    the sheet reflects the true current state per key instead of a blank
    #    cell that could be mistaken for "missing in the app".
    for key, row in master_sheet.items():
        for folder, lang in LANG_MAP.items():
            if lang in row:
                continue
            existing = existing_by_folder.get(folder)
            if existing and existing.get(key):
                row[lang] = existing[key]

    # 4. Google Sheets Export (The Source of Truth for QA)
    try:
        print("📊 Syncing new batch to Google Sheets...")
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('service_account.json', scope)
        gs_client = gspread.authorize(creds)
        sheet = gs_client.open_by_key(GOOGLE_SHEET_ID)

        # Google Sheets tab names can't contain : [ ] * / \ ? -- so the time
        # uses an underscore instead of a colon (e.g. "Gemini Localization - Aug 12, 2026 04_46 PM").
        tab_name = f"{provider_name.capitalize()} Localization - {datetime.now().strftime('%b %d, %Y %I_%M %p')}"
        tab = sheet.add_worksheet(title=tab_name, rows=str(len(master_sheet) + 10), cols="20")

        headers = ["Key", "English"] + list(LANG_MAP.values())
        tab.append_row(headers)

        rows = [[k, d['English']] + [d.get(l, "") for l in LANG_MAP.values()] for k, d in master_sheet.items()]
        tab.append_rows(rows)
        print(f"✅ Sheet tab created: {tab_name}")
    except Exception as e:
        print(f"⚠️ Google Sheet Error: {e}")

    print("\n🎉 Done! New strings have been added to XML and Google Sheets.")


if __name__ == "__main__":
    main()

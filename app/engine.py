"""
================================================================================
LOCALIZATION ENGINE (ported from localize_claude.py)
================================================================================

This is the tested translation/escaping/file-writing logic from the reference
CLI script, restructured so a UI can drive it and subscribe to progress
instead of it running straight through main() with input()/print().

Core logic (get_eng_strings_with_context, get_existing_strings, chunk_dict,
translate_batch, translate_batch_with_retry, _collapse_escapes,
escape_android_string, format_string_value, append_to_xml_file) is ported
as-is from the reference script -- treat it as correct and battle-tested.

What's new here:
  - Auto-detection of values-* folders instead of a hardcoded LANG_MAP/
    VAR_FOLDERS, so no language or variant folder is silently skipped.
  - LocalizationEngine.scan() / .run() split so a UI can show a checklist
    before translating and live per-language progress while translating.
"""

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional
from xml.sax.saxutils import escape as xml_escape

import lxml.etree as ET

BATCH_SIZE = 25
MAX_RETRIES_PER_BATCH = 2

TAG_RE = re.compile(r'</?[a-zA-Z][a-zA-Z0-9]*[^<>]*>')
_MULTI_ESCAPE_RE = re.compile(r'\\+([nt\'"\\])')

# --- values-* folder classification -----------------------------------------
# Android resource-qualifier tokens that are NOT languages (screen size,
# orientation, density, night mode, API level, input method, etc). A
# values-<suffix> folder made up entirely of these tokens is a "variant"
# folder: it gets a raw copy of the English text, never translated.
_NON_LANG_TOKENS = {
    'land', 'port', 'night', 'notnight', 'large', 'small', 'normal', 'xlarge',
    'long', 'notlong', 'round', 'notround', 'widecg', 'nowidecg', 'highdr', 'lowdr',
    'ldrtl', 'ldltr', 'anydpi', 'nodpi', 'tvdpi', 'ldpi', 'mdpi', 'hdpi', 'xhdpi',
    'xxhdpi', 'xxxhdpi', 'car', 'desk', 'television', 'appliance', 'watch',
    'vrheadset', 'keysexposed', 'keyshidden', 'keyssoft', 'nokeys', 'qwerty',
    '12key', 'navexposed', 'navhidden', 'nonav', 'dpad', 'trackball', 'wheel',
    'notouch', 'finger', 'stylus',
}
_NON_LANG_PREFIX_RE = re.compile(r'^(sw\d+dp|w\d+dp|h\d+dp|v\d+|mcc\d+|mnc\d+)$')
_LANG_CODE_RE = re.compile(r'^[a-z]{2,3}$')
_REGION_RE = re.compile(r'^r[A-Z]{2}$')
_BCP47_RE = re.compile(r'^b\+[A-Za-z0-9+]+$')

LANG_DISPLAY_NAMES = {
    'de': 'German', 'es': 'Spanish', 'fr': 'French', 'in': 'Indonesian',
    'id': 'Indonesian', 'it': 'Italian', 'ja': 'Japanese', 'ko': 'Korean',
    'pt': 'Portuguese', 'ru': 'Russian', 'zh': 'Chinese', 'ar': 'Arabic',
    'hi': 'Hindi', 'nl': 'Dutch', 'pl': 'Polish', 'tr': 'Turkish',
    'th': 'Thai', 'vi': 'Vietnamese', 'sv': 'Swedish', 'da': 'Danish',
    'fi': 'Finnish', 'no': 'Norwegian', 'nb': 'Norwegian Bokmal', 'cs': 'Czech',
    'el': 'Greek', 'he': 'Hebrew', 'iw': 'Hebrew', 'hu': 'Hungarian',
    'ro': 'Romanian', 'sk': 'Slovak', 'uk': 'Ukrainian', 'ca': 'Catalan',
    'fa': 'Persian', 'ms': 'Malay', 'sr': 'Serbian', 'hr': 'Croatian',
    'bg': 'Bulgarian', 'lt': 'Lithuanian', 'lv': 'Latvian', 'et': 'Estonian',
    'sl': 'Slovenian', 'sw': 'Swahili', 'ta': 'Tamil', 'te': 'Telugu',
    'bn': 'Bengali', 'ur': 'Urdu', 'fil': 'Filipino', 'km': 'Khmer',
    'my': 'Burmese', 'ne': 'Nepali', 'si': 'Sinhala', 'am': 'Amharic',
    'az': 'Azerbaijani', 'ka': 'Georgian', 'kk': 'Kazakh', 'mn': 'Mongolian',
    'is': 'Icelandic', 'af': 'Afrikaans', 'sq': 'Albanian', 'hy': 'Armenian',
    'eu': 'Basque', 'gl': 'Galician', 'zu': 'Zulu', 'lo': 'Lao', 'ml': 'Malayalam',
    'kn': 'Kannada', 'mr': 'Marathi', 'gu': 'Gujarati', 'pa': 'Punjabi',
    'uz': 'Uzbek', 'ky': 'Kyrgyz', 'be': 'Belarusian', 'mk': 'Macedonian',
    'bs': 'Bosnian', 'lb': 'Luxembourgish', 'mt': 'Maltese', 'ga': 'Irish',
    'cy': 'Welsh', 'eo': 'Esperanto',
}
REGION_DISPLAY_NAMES = {
    'CN': 'Simplified', 'TW': 'Traditional', 'HK': 'Hong Kong',
    'BR': 'Brazil', 'PT': 'Portugal', 'ES': 'Spain', 'MX': 'Mexico',
    'US': 'US', 'GB': 'UK', 'AU': 'Australia', 'CA': 'Canada',
}


def classify_values_folder(folder_name):
    """
    Classifies a values-* (or values) folder name.

    Returns a tuple:
      ('base', None, None)                     -- the values/ folder itself
      ('language', code, display_name)          -- e.g. ('de', 'German'),
                                                     ('zh-rCN', 'Chinese (Simplified)')
      ('variant', suffix, None)                 -- screen/orientation/etc,
                                                     raw copy, never translated
      ('unrecognized', suffix, None)            -- present but not confidently
                                                     classifiable; left alone
    """
    if folder_name == 'values':
        return ('base', None, None)
    if not folder_name.startswith('values-'):
        return ('unrecognized', folder_name, None)

    suffix = folder_name[len('values-'):]
    segments = suffix.split('-')
    first = segments[0]

    if _BCP47_RE.match(suffix):
        return ('language', suffix, suffix)

    if _LANG_CODE_RE.match(first):
        if len(segments) == 1:
            return ('language', first, LANG_DISPLAY_NAMES.get(first, first))
        if len(segments) == 2 and _REGION_RE.match(segments[1]):
            region = segments[1][1:]
            base_name = LANG_DISPLAY_NAMES.get(first, first)
            region_name = REGION_DISPLAY_NAMES.get(region, region)
            return ('language', suffix, f"{base_name} ({region_name})")
        # e.g. values-de-land -- language plus device qualifier combo.
        # Out of scope for auto-translation; leave untouched rather than guess.
        return ('unrecognized', suffix, None)

    if all(seg in _NON_LANG_TOKENS or _NON_LANG_PREFIX_RE.match(seg) for seg in segments):
        return ('variant', suffix, None)

    return ('unrecognized', suffix, None)


# Languages the reference script (localize_claude.py's LANG_MAP) already
# translated into. Used only to preselect defaults in the "add a new
# language" picker -- any other language recognized by
# classify_values_folder can still be added, see parse_target_language_code.
LEGACY_LANG_MAP = {
    'de': 'German', 'es': 'Spanish', 'fr': 'French', 'in': 'Indonesian',
    'it': 'Italian', 'ja': 'Japanese', 'ko': 'Korean', 'pt': 'Portuguese (Brazil)',
    'ru': 'Russian', 'zh-rCN': 'Chinese (Simplified)',
}

# Best-effort representative flag per language code, for the picker UI.
# Many languages aren't tied to a single country -- these are conventional
# choices, not a claim of exclusivity. Falls back to a globe if unmapped.
FLAG_EMOJI = {
    'de': '🇩🇪', 'es': '🇪🇸', 'fr': '🇫🇷', 'in': '🇮🇩', 'id': '🇮🇩', 'it': '🇮🇹',
    'ja': '🇯🇵', 'ko': '🇰🇷', 'pt': '🇵🇹', 'ru': '🇷🇺', 'zh': '🇨🇳', 'ar': '🇸🇦',
    'hi': '🇮🇳', 'nl': '🇳🇱', 'pl': '🇵🇱', 'tr': '🇹🇷', 'th': '🇹🇭', 'vi': '🇻🇳',
    'sv': '🇸🇪', 'da': '🇩🇰', 'fi': '🇫🇮', 'no': '🇳🇴', 'nb': '🇳🇴', 'cs': '🇨🇿',
    'el': '🇬🇷', 'he': '🇮🇱', 'iw': '🇮🇱', 'hu': '🇭🇺', 'ro': '🇷🇴', 'sk': '🇸🇰',
    'uk': '🇺🇦', 'ca': '🇪🇸', 'fa': '🇮🇷', 'ms': '🇲🇾', 'sr': '🇷🇸', 'hr': '🇭🇷',
    'bg': '🇧🇬', 'lt': '🇱🇹', 'lv': '🇱🇻', 'et': '🇪🇪', 'sl': '🇸🇮', 'sw': '🇰🇪',
    'ta': '🇮🇳', 'te': '🇮🇳', 'bn': '🇧🇩', 'ur': '🇵🇰', 'fil': '🇵🇭', 'km': '🇰🇭',
    'my': '🇲🇲', 'ne': '🇳🇵', 'si': '🇱🇰', 'am': '🇪🇹', 'az': '🇦🇿', 'ka': '🇬🇪',
    'kk': '🇰🇿', 'mn': '🇲🇳', 'is': '🇮🇸', 'af': '🇿🇦', 'sq': '🇦🇱', 'hy': '🇦🇲',
    'eu': '🌐', 'gl': '🇪🇸', 'zu': '🇿🇦', 'lo': '🇱🇦', 'ml': '🇮🇳', 'kn': '🇮🇳',
    'mr': '🇮🇳', 'gu': '🇮🇳', 'pa': '🇮🇳', 'uz': '🇺🇿', 'ky': '🇰🇬', 'be': '🇧🇾',
    'mk': '🇲🇰', 'bs': '🇧🇦', 'lb': '🇱🇺', 'mt': '🇲🇹', 'ga': '🇮🇪', 'cy': '🏴',
    'eo': '🌐', 'zh-rCN': '🇨🇳', 'zh-rTW': '🇹🇼',
}


def get_all_language_options():
    """
    Full list of {code, display_name, flag, legacy_default} for the "add a
    new language" picker UI, sorted by display name. Any entry's code can
    be passed to scan()'s additional_lang_codes -- legacy_default just
    marks the 10 languages the reference script already handled, so the UI
    can preselect them.
    """
    entries = list(LANG_DISPLAY_NAMES.items()) + [
        ('zh-rCN', 'Chinese (Simplified)'), ('zh-rTW', 'Chinese (Traditional)'),
    ]
    seen = set()
    options = []
    for code, name in entries:
        if code in seen:
            continue
        seen.add(code)
        options.append({
            'code': code,
            'display_name': name,
            'flag': FLAG_EMOJI.get(code, '🌐'),
            'legacy_default': code in LEGACY_LANG_MAP,
        })
    options.sort(key=lambda o: o['display_name'])
    return options


def parse_target_language_code(raw_code):
    """
    Validates a user-typed/checked target language code for creating a
    brand-new values-<code>/ folder. Accepts any code classify_values_folder
    recognizes as a language qualifier -- LEGACY_LANG_MAP only supplies the
    exact display name for the 10 reference-script languages (e.g. 'pt' ->
    'Portuguese (Brazil)', matching the original script) and is otherwise
    not a restriction. Returns (code, display_name), or None if not
    recognized as a language code at all.
    """
    code = raw_code.strip()
    if not code:
        return None
    if code in LEGACY_LANG_MAP:
        return code, LEGACY_LANG_MAP[code]
    kind, parsed_code, display_name = classify_values_folder('values-' + code)
    if kind != 'language':
        return None
    return parsed_code, display_name


def discover_res_layout(base_res_path):
    """
    Scans base_res_path for values-* folders and classifies each.
    Returns dict with keys: languages ({code: {'folder', 'display_name'}}),
    variant_folders (list of folder names), unrecognized_folders (list).
    """
    languages = {}
    variant_folders = []
    unrecognized_folders = []

    if not os.path.isdir(base_res_path):
        return {'languages': languages, 'variant_folders': variant_folders,
                'unrecognized_folders': unrecognized_folders}

    for entry in sorted(os.listdir(base_res_path)):
        full = os.path.join(base_res_path, entry)
        if not os.path.isdir(full):
            continue
        if entry == 'values':
            continue
        if not entry.startswith('values-'):
            continue
        kind, code, display_name = classify_values_folder(entry)
        if kind == 'language':
            languages[code] = {'folder': entry, 'display_name': display_name}
        elif kind == 'variant':
            variant_folders.append(entry)
        elif kind == 'unrecognized':
            unrecognized_folders.append(entry)

    return {'languages': languages, 'variant_folders': variant_folders,
            'unrecognized_folders': unrecognized_folders}


# --- Core logic, ported from localize_claude.py -----------------------------

def _element_full_text(elem):
    """
    Returns an element's full text content, including inline markup like
    <b>...</b> written as real XML child elements (not CDATA/escaped
    entities) rather than just elem.text -- which only covers text before
    the first child tag and silently drops everything after it. Android
    string resources commonly contain inline markup this way, so relying on
    elem.text alone truncates those strings.
    """
    parts = [elem.text or ""]
    for child in elem:
        parts.append(ET.tostring(child, encoding='unicode', with_tail=False))
        parts.append(child.tail or "")
    return "".join(parts)


def get_eng_strings_with_context(base_res_path):
    """Reads main English strings and captures 'description' attribute for context."""
    path = os.path.join(base_res_path, 'values', 'strings.xml')
    if not os.path.exists(path):
        raise FileNotFoundError(f"English file not found at {path}")

    tree = ET.parse(path)
    results = {}
    for s in tree.getroot().findall('string'):
        text = _element_full_text(s)
        if s.get('translatable') != 'false' and s.get('name') and text:
            results[s.get('name')] = {
                'text': text,
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
            s.get('name'): _element_full_text(s)
            for s in tree.getroot().findall('string')
            if s.get('name')
        }
    except Exception:
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
            if key in batch_data and val:
                result[key] = val
        return result
    except Exception as e:
        raise RuntimeError(f"{provider.upper()} error during {target_lang} translation: {e}") from e


def translate_batch_with_retry(provider, client, batch_data, target_lang, max_retries=MAX_RETRIES_PER_BATCH,
                                on_retry: Optional[Callable[[int, int], None]] = None):
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
        try:
            chunk_results = translate_batch(provider, client, pending, target_lang)
        except RuntimeError:
            chunk_results = {}
        for k, v in chunk_results.items():
            if k in pending:
                results[k] = v
        pending = {k: v for k, v in pending.items() if k not in results}
        if pending and attempt <= max_retries:
            if on_retry:
                on_retry(attempt, len(pending))
            time.sleep(1)
    return results, pending


def _collapse_escapes(text):
    """
    Collapses any run of one-or-more backslashes immediately followed by an
    Android escape character (n, t, ', ", \\) down to the single literal
    character it represents.
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
        return f'<![CDATA[{val}]]>'

    literal = _collapse_escapes(val)
    escaped = escape_android_string(literal)
    escaped = xml_escape(escaped, {'"': '&quot;'})
    return escaped


def append_to_xml_file(base_res_path, folder, data_dict):
    """
    Surgical Append: Finds </resources> and inserts new strings before it.
    This preserves existing formatting and never overwrites an existing key.
    Returns the number of strings actually written.
    """
    if not data_dict:
        return 0

    dir_path = os.path.join(base_res_path, folder)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    path = os.path.join(dir_path, 'strings.xml')

    existing_strings = get_existing_strings(path)
    if existing_strings is None:
        raise RuntimeError(f"{path} could not be parsed safely -- refusing to write to it.")
    existing_keys = existing_strings.keys()

    new_entries = []
    for key, val in data_dict.items():
        if key not in existing_keys:
            new_entries.append(f'    <string name="{key}">{format_string_value(val)}</string>')

    if not new_entries:
        return 0

    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        insert_pos = content.rfind('</resources>')
        if insert_pos != -1:
            new_text = "\n" + "\n".join(new_entries) + "\n"
            updated_content = content[:insert_pos] + new_text + content[insert_pos:]
            with open(path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
        else:
            raise RuntimeError(f"couldn't find </resources> in {path}, skipped write.")
    else:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n')
            f.write("\n".join(new_entries))
            f.write('\n</resources>')

    return len(new_entries)


# --- Scan / Run data structures ----------------------------------------------

@dataclass
class ScanKeyInfo:
    key: str
    text: str
    context: str
    missing_in: list = field(default_factory=list)   # list of language codes
    present_in: list = field(default_factory=list)    # list of language codes


@dataclass
class ScanResult:
    eng_count: int
    languages: dict            # code -> display_name
    variant_folders: list
    unrecognized_folders: list
    keys: list                 # list[ScanKeyInfo], only keys missing in >=1 language
    parse_errors: list         # folder names that failed to parse (skipped entirely)
    invalid_lang_codes: list = field(default_factory=list)  # requested codes not recognized


@dataclass
class RunResult:
    written: dict               # display_name -> count written
    failures: dict               # display_name -> list of keys still missing
    variant_written: dict        # variant folder -> count written
    sheet_status: str            # 'skipped' | 'synced' | 'error'
    sheet_error: Optional[str] = None
    sheet_tab_name: Optional[str] = None
    written_keys: set = field(default_factory=set)  # union of keys newly translated this run, any language


class LocalizationEngine:
    def __init__(self, base_res_path):
        self.base_res_path = base_res_path
        self._eng_data = None
        self._layout = None
        self._existing_by_lang = {}   # code -> {key: text} or None

    def scan(self, additional_lang_codes=None) -> ScanResult:
        eng_data = get_eng_strings_with_context(self.base_res_path)
        layout = discover_res_layout(self.base_res_path)

        invalid_lang_codes = []
        for raw in (additional_lang_codes or []):
            parsed = parse_target_language_code(raw)
            if parsed is None:
                invalid_lang_codes.append(raw.strip())
                continue
            code, display_name = parsed
            if code not in layout['languages']:
                # Folder doesn't exist yet -- run() creates it (via
                # append_to_xml_file) the same way it creates any missing
                # values-* folder, so no folder needs to exist here.
                layout['languages'][code] = {'folder': f'values-{code}', 'display_name': display_name}

        parse_errors = []
        existing_by_lang = {}
        for code, info in layout['languages'].items():
            lang_path = os.path.join(self.base_res_path, info['folder'], 'strings.xml')
            strings = get_existing_strings(lang_path)
            if strings is None:
                parse_errors.append(info['folder'])
            existing_by_lang[code] = strings

        key_infos = []
        for key, data in eng_data.items():
            missing_in = []
            present_in = []
            for code, info in layout['languages'].items():
                existing = existing_by_lang.get(code)
                if existing is None:
                    continue  # unparsable file -- do not report as missing or present
                if key in existing:
                    present_in.append(code)
                else:
                    missing_in.append(code)
            if missing_in:
                key_infos.append(ScanKeyInfo(
                    key=key, text=data['text'], context=data['context'],
                    missing_in=missing_in, present_in=present_in,
                ))

        self._eng_data = eng_data
        self._layout = layout
        self._existing_by_lang = existing_by_lang

        lang_display = {code: info['display_name'] for code, info in layout['languages'].items()}

        return ScanResult(
            eng_count=len(eng_data),
            languages=lang_display,
            variant_folders=layout['variant_folders'],
            unrecognized_folders=layout['unrecognized_folders'],
            keys=key_infos,
            parse_errors=parse_errors,
            invalid_lang_codes=invalid_lang_codes,
        )

    def run(self, selected_keys, provider, client, on_progress: Callable[[str, int, int], None],
            batch_size=BATCH_SIZE, max_retries=MAX_RETRIES_PER_BATCH,
            on_log: Optional[Callable[[str], None]] = None) -> RunResult:
        """
        Translates only selected_keys, batch by batch, per language.
        on_progress(display_name, done, total) fires after every batch.
        Writes results via append_to_xml_file as each language completes.
        """
        if self._eng_data is None or self._layout is None:
            raise RuntimeError("scan() must be called before run()")

        def log(msg):
            if on_log:
                on_log(msg)

        eng_data = self._eng_data
        layout = self._layout
        existing_by_lang = self._existing_by_lang

        written = {}
        failures = {}
        written_keys = set()

        for code, info in layout['languages'].items():
            display_name = info['display_name']
            existing = existing_by_lang.get(code)
            if existing is None:
                continue

            missing_keys = [k for k in selected_keys if k in eng_data and k not in existing]
            if not missing_keys:
                continue

            to_do = {k: eng_data[k] for k in missing_keys}
            total = len(to_do)
            done = 0
            lang_results = {}

            on_progress(display_name, 0, total)

            for chunk in chunk_dict(to_do, batch_size):
                def _on_retry(attempt, n_pending, _lang=display_name):
                    log(f"{_lang}: retry {attempt}, {n_pending} key(s) still missing, retrying...")

                try:
                    results, still_missing = translate_batch_with_retry(
                        provider, client, chunk, display_name,
                        max_retries=max_retries, on_retry=_on_retry,
                    )
                except Exception as e:
                    log(f"{display_name}: batch failed entirely: {e}")
                    results, still_missing = {}, chunk

                lang_results.update(results)
                if still_missing:
                    failures.setdefault(display_name, []).extend(still_missing.keys())

                done += len(chunk)
                on_progress(display_name, done, total)
                time.sleep(2 if provider == "gemini" else 0.5)

            if lang_results:
                count = append_to_xml_file(self.base_res_path, info['folder'], lang_results)
                written[display_name] = written.get(display_name, 0) + count
                written_keys.update(lang_results.keys())
                existing_by_lang[code].update(lang_results)

        # Variant folders: raw English copy, no translation, no AI call.
        variant_written = {}
        for folder in layout['variant_folders']:
            var_path = os.path.join(self.base_res_path, folder, 'strings.xml')
            existing = get_existing_strings(var_path)
            if existing is None:
                log(f"{folder}: existing file could not be parsed safely, skipped.")
                continue
            missing_keys = [k for k in selected_keys if k in eng_data and k not in existing]
            if not missing_keys:
                continue
            variant_data = {k: eng_data[k]['text'] for k in missing_keys}
            count = append_to_xml_file(self.base_res_path, folder, variant_data)
            if count:
                variant_written[folder] = count

        return RunResult(
            written=written,
            failures=failures,
            variant_written=variant_written,
            sheet_status='skipped',
            written_keys=written_keys,
        )

    def build_sheet_rows(self, written_keys):
        """
        Builds {key: {'English': ..., display_name: value, ...}} for exactly
        the keys in written_keys -- the ones that got a new translation
        somewhere in this run -- each backfilled with every language's
        current value (including languages this run didn't touch) so a row
        has full context. Keys that were already fully translated before
        this run, and untouched by it, are never included here even if
        their language received other new writes this run -- otherwise
        every sync would silently re-upload the whole existing sheet.
        """
        if self._eng_data is None or self._layout is None:
            raise RuntimeError("scan() must be called before build_sheet_rows()")

        eng_data = self._eng_data
        layout = self._layout
        existing_by_lang = self._existing_by_lang
        lang_display_list = [info['display_name'] for info in layout['languages'].values()]

        master_sheet = {}
        for key in written_keys:
            if key not in eng_data:
                continue
            row = {'English': eng_data[key]['text']}
            for code, info in layout['languages'].items():
                existing = existing_by_lang.get(code)
                if existing and existing.get(key):
                    row[info['display_name']] = existing[key]
            master_sheet[key] = row

        return master_sheet, lang_display_list


def sync_to_google_sheet(sheet_id, service_account_path, provider_name, master_sheet, lang_display_list):
    """
    Exports master_sheet rows to a new tab in the given Google Sheet.
    Returns the tab name on success. Raises on failure.
    """
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(service_account_path, scope)
    gs_client = gspread.authorize(creds)
    sheet = gs_client.open_by_key(sheet_id)

    # Google Sheets tab names can't contain : [ ] * / \ ? -- use an
    # underscore in place of the colon in the time, e.g.
    # "Gemini Localization - Aug 12, 2026 04_46 PM".
    tab_name = f"{provider_name.capitalize()} Localization - {datetime.now().strftime('%b %d, %Y %I_%M %p')}"
    tab = sheet.add_worksheet(title=tab_name, rows=str(len(master_sheet) + 10), cols="20")

    headers = ["Key", "English"] + lang_display_list
    tab.append_row(headers)

    rows = [[k, d.get('English', '')] + [d.get(l, "") for l in lang_display_list] for k, d in master_sheet.items()]
    if rows:
        tab.append_rows(rows)

    return tab_name

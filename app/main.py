"""
Desktop app entry point (pywebview). Exposes an Api object to the JS
frontend in web/index.html; the Python side is the engine from engine.py
called directly, no HTTP server involved.
"""

import json
import os
import sys
import threading
import traceback

import webview

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from engine import LocalizationEngine, sync_to_google_sheet, get_all_language_options
import providers

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def _js_arg(value):
    """json.dumps a Python value for safe embedding as a single JS call argument."""
    return json.dumps(value)


class Api:
    def __init__(self):
        self.window = None
        self.engine = None
        self.base_res_path = None

    def set_window(self, window):
        self.window = window

    # --- settings / config -------------------------------------------------

    def get_settings(self):
        cfg = config.load_config()
        return {
            "recent_paths": cfg.get("recent_paths", []),
            "last_provider": cfg.get("last_provider", "gemini"),
            "batch_size": cfg.get("batch_size", 25),
            "max_retries": cfg.get("max_retries", 2),
            "sheet_sync_enabled": cfg.get("sheet_sync_enabled", False),
            "google_sheet_id": cfg.get("google_sheet_id", ""),
            "service_account_path": cfg.get("service_account_path", ""),
            "has_gemini_key": config.has_api_key("gemini"),
            "has_openai_key": config.has_api_key("openai"),
        }

    def save_settings(self, settings):
        cfg = config.load_config()
        for field in ("last_provider", "batch_size", "max_retries",
                       "sheet_sync_enabled", "google_sheet_id", "service_account_path"):
            if field in settings:
                cfg[field] = settings[field]
        config.save_config(cfg)
        return {"ok": True}

    def set_api_key(self, provider, key):
        if not key:
            config.delete_api_key(provider)
        else:
            config.set_api_key(provider, key)
        return {"ok": True}

    def get_language_options(self):
        return get_all_language_options()

    # --- file pickers --------------------------------------------------------

    def choose_strings_file(self):
        result = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("XML files (*.xml)", "All files (*.*)"),
        )
        if not result:
            return {"ok": False}
        path = result[0]
        if os.path.basename(path) != "strings.xml":
            return {"ok": False, "error": "Please select the English strings.xml file (the one under values/)."}
        parent = os.path.basename(os.path.dirname(path))
        if parent != "values":
            return {"ok": False, "error": f"Selected file is in '{parent}/', expected a 'values/' folder. Pick the English strings.xml under res/values/."}
        return {"ok": True, "path": path}

    def choose_service_account_file(self):
        result = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("JSON files (*.json)", "All files (*.*)"),
        )
        if not result:
            return {"ok": False}
        return {"ok": True, "path": result[0]}

    # --- scan ----------------------------------------------------------------

    def scan(self, strings_xml_path, additional_lang_codes=None):
        try:
            base_res_path = os.path.dirname(os.path.dirname(strings_xml_path))
            engine = LocalizationEngine(base_res_path)
            result = engine.scan(additional_lang_codes)

            self.engine = engine
            self.base_res_path = base_res_path

            cfg = config.load_config()
            config.add_recent_path(cfg, strings_xml_path)
            config.save_config(cfg)

            keys = [
                {
                    "key": k.key,
                    "text": k.text,
                    "context": k.context,
                    "missing_in": k.missing_in,
                    "present_in": k.present_in,
                }
                for k in result.keys
            ]

            return {
                "ok": True,
                "result": {
                    "eng_count": result.eng_count,
                    "languages": result.languages,
                    "variant_folders": result.variant_folders,
                    "unrecognized_folders": result.unrecognized_folders,
                    "parse_errors": result.parse_errors,
                    "invalid_lang_codes": result.invalid_lang_codes,
                    "keys": keys,
                },
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --- run -------------------------------------------------------------------

    def run_translation(self, selected_keys, provider, sync_sheet):
        if not self.engine:
            return {"ok": False, "error": "Run scan() first."}
        threading.Thread(
            target=self._run_translation_thread,
            args=(list(selected_keys), provider, bool(sync_sheet)),
            daemon=True,
        ).start()
        return {"ok": True}

    def _emit(self, fn_name, *args):
        js_args = ", ".join(_js_arg(a) for a in args)
        self.window.evaluate_js(f"window.{fn_name}({js_args})")

    def _run_translation_thread(self, selected_keys, provider, sync_sheet):
        try:
            api_key = config.get_api_key(provider)
            client, model_name = providers.get_client(provider, api_key)
        except Exception as e:
            self._emit("onTranslationError", str(e))
            return

        cfg = config.load_config()
        batch_size = int(cfg.get("batch_size", 25) or 25)
        max_retries = int(cfg.get("max_retries", 2) or 2)

        def on_progress(lang, done, total):
            self._emit("onTranslationProgress", lang, done, total)

        def on_log(msg):
            self._emit("onTranslationLog", msg)

        try:
            result = self.engine.run(
                set(selected_keys), provider, client,
                on_progress=on_progress, on_log=on_log,
                batch_size=batch_size, max_retries=max_retries,
            )
        except Exception as e:
            self._emit("onTranslationError", str(e))
            return

        sheet_status = "skipped"
        sheet_error = None
        sheet_tab_name = None

        if sync_sheet and result.written_keys:
            sheet_id = cfg.get("google_sheet_id", "")
            sa_path = cfg.get("service_account_path", "")
            if not sheet_id or not sa_path:
                sheet_status = "error"
                sheet_error = "Sheet sync is on but Sheet ID or service account file isn't configured."
            else:
                try:
                    master_sheet, lang_display_list = self.engine.build_sheet_rows(result.written_keys)
                    sheet_tab_name = sync_to_google_sheet(
                        sheet_id, sa_path, provider, master_sheet, lang_display_list
                    )
                    sheet_status = "synced"
                except Exception as e:
                    sheet_status = "error"
                    sheet_error = str(e) or f"{type(e).__name__} (no message -- see log for details)"
                    on_log(f"Sheet sync failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")

        payload = {
            "written": result.written,
            "failures": result.failures,
            "variant_written": result.variant_written,
            "sheet_status": sheet_status,
            "sheet_error": sheet_error,
            "sheet_tab_name": sheet_tab_name,
        }
        self._emit("onTranslationDone", payload)


def main():
    api = Api()
    window = webview.create_window(
        "Smart Localization Automation",
        url=os.path.join(WEB_DIR, "index.html"),
        js_api=api,
        width=1100,
        height=780,
        min_size=(820, 600),
    )
    api.set_window(window)
    webview.start()


if __name__ == "__main__":
    main()

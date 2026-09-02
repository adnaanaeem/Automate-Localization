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

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-built .exe -- bundled files (including web/)
    # are extracted to sys._MEIPASS, and sibling modules are already on
    # sys.path via the bundle itself.
    APP_DIR = sys._MEIPASS
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, APP_DIR)

import config
from engine import LocalizationEngine, sync_to_google_sheet, get_all_language_options
import ios_engine
import providers
import sheet_import
import updater
from version import APP_VERSION

WEB_DIR = os.path.join(APP_DIR, "web")
# pywebview's `icon` param to webview.start() is documented as "supported
# only on GTK/QT" (silently ignored on the Windows/macOS backends this app
# actually ships for), but pass the platform-correct file anyway rather than
# always the Windows .ico -- harmless now, correct if that ever changes.
ICON_PATH = os.path.join(APP_DIR, "icon.icns" if sys.platform == "darwin" else "icon.ico")


class Api:
    def __init__(self):
        # Underscore-prefixed on purpose: pywebview's inject_pywebview()
        # walks every non-underscore, non-callable attribute on this object
        # recursively to build the JS bridge (webview/util.py's
        # get_functions()). self._window is the live Window object with a
        # huge WinForms/WebView2 COM object graph behind it -- if it were a
        # public attribute, that recursive walk would descend into it and
        # touch pythonnet/COM objects from whatever thread inject_pywebview
        # runs on (WebView2's own navigation-completed event, not
        # necessarily the GUI thread), which reproduced as the whole app
        # going "Not Responding" if the user maximized while that walk was
        # still in flight shortly after launch. Confirmed via py-spy stack
        # dump of a hung process -- do not make these public again.
        self._window = None
        self._engine = None
        self._base_res_path = None
        self._event_queue = []
        self._event_lock = threading.Lock()

    def set_window(self, window):
        self._window = window

    # --- settings / config -------------------------------------------------

    def get_settings(self):
        cfg = config.load_config()
        return {
            "recent_paths": cfg.get("recent_paths", []),
            "recent_ios_paths": cfg.get("recent_ios_paths", []),
            "last_provider": cfg.get("last_provider", "gemini"),
            "batch_size": cfg.get("batch_size", 25),
            "max_retries": cfg.get("max_retries", 10),
            "sheet_sync_enabled": cfg.get("sheet_sync_enabled", True),
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

    def remove_recent_path(self, path, key="recent_paths"):
        cfg = config.load_config()
        config.remove_recent_path(cfg, path, key=key)
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

    # --- updates -------------------------------------------------------------

    def get_app_version(self):
        return APP_VERSION

    def check_for_update(self):
        threading.Thread(target=self._check_for_update_thread, daemon=True).start()
        return {"ok": True}

    def _check_for_update_thread(self):
        info = updater.check_for_update(APP_VERSION)
        self._emit("onUpdateCheckResult", info)

    def download_and_install_update(self, download_url):
        threading.Thread(
            target=self._download_and_install_update_thread,
            args=(download_url,),
            daemon=True,
        ).start()
        return {"ok": True}

    def _download_and_install_update_thread(self, download_url):
        def on_progress(downloaded, total):
            self._emit("onUpdateDownloadProgress", downloaded, total)

        try:
            updater.download_and_launch_installer(download_url, on_progress=on_progress)
        except Exception as e:
            self._emit("onUpdateError", str(e))
            return
        self._emit("onUpdateInstalling")
        # The installer's CloseApplications setting waits for this process
        # to exit before it can replace the running exe -- exit now that
        # it's launched, rather than leaving the window open indefinitely.
        os._exit(0)

    # --- file pickers --------------------------------------------------------

    def choose_strings_file(self):
        result = self._window.create_file_dialog(
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
        result = self._window.create_file_dialog(
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

            self._engine = engine
            self._base_res_path = base_res_path

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
        if not self._engine:
            return {"ok": False, "error": "Run scan() first."}
        threading.Thread(
            target=self._run_translation_thread,
            args=(list(selected_keys), provider, bool(sync_sheet)),
            daemon=True,
        ).start()
        return {"ok": True}

    def _emit(self, fn_name, *args):
        """
        Queues an event for JS to pick up on its next poll -- see
        poll_events(). Deliberately does NOT call window.evaluate_js() from
        here, which every caller of _emit() does from a background thread
        (translation progress, update checks, ...).

        Two things were tried and both hung the app ("Not Responding") --
        confirmed each time with a py-spy stack dump of the actual hung
        process, not just theorized:

        1. Calling window.evaluate_js() directly from a background thread.
           pywebview 6.2.1's WinForms/EdgeChromium backend does this with no
           Control.Invoke marshaling at all (unlike its own maximize/
           minimize/restore/clear_cookies, which do marshal) -- a raw
           cross-thread touch of the WebView2 control.
        2. Marshaling that same call onto the GUI thread via
           Control.Invoke/BeginInvoke (matching pywebview's own pattern for
           its thread-safe methods) -- this does NOT help, because
           window.evaluate_js() is itself a blocking call that waits on a
           semaphore released by a JS callback message. Once the delegate
           is dispatched and actually running, the GUI/message-pump thread
           is sitting inside it, unable to return to its own message loop
           to ever receive the callback that would release that wait --
           self-deadlock, independent of Invoke vs BeginInvoke.

        JS calling INTO Python (the js_api bridge direction) has always
        been safe here -- pywebview's whole binding model depends on that
        direction working -- so the fix is to only ever go that direction:
        background threads write into this queue, and app.js polls
        poll_events() on a plain setInterval, dispatching each queued
        {fn, args} to the same window.onXxx(...) handlers as before. No
        evaluate_js call from a background thread, ever.
        """
        with self._event_lock:
            self._event_queue.append({"fn": fn_name, "args": list(args)})

    def poll_events(self):
        with self._event_lock:
            events = self._event_queue
            self._event_queue = []
        return events

    def _run_translation_thread(self, selected_keys, provider, sync_sheet):
        try:
            api_key = config.get_api_key(provider)
            client, model_name = providers.get_client(provider, api_key)
        except Exception as e:
            self._emit("onTranslationError", str(e))
            return

        cfg = config.load_config()
        batch_size = int(cfg.get("batch_size", 25) or 25)
        max_retries = int(cfg.get("max_retries", 10) or 10)

        def on_progress(lang, done, total):
            self._emit("onTranslationProgress", lang, done, total)

        def on_log(msg):
            self._emit("onTranslationLog", msg)

        try:
            result = self._engine.run(
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
                    master_sheet, lang_display_list = self._engine.build_sheet_rows(result.written_keys)
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

    # --- iOS -------------------------------------------------------------------
    # Fundamentally different shape from the Android flow above: no scan/diff
    # step, no batching -- a developer types one English string at a time and
    # it's translated into every selected language in one call. See
    # ios_engine.py's module docstring for why this is a separate module
    # rather than bolted onto engine.py.

    def get_ios_language_options(self):
        return ios_engine.get_all_ios_language_options()

    def ios_generate_key(self, english_text):
        return ios_engine.generate_key(english_text)

    def choose_ios_catalog_file(self):
        result = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            file_types=("Xcode String Catalog (*.xcstrings)", "All files (*.*)"),
            save_filename="Localizable.xcstrings",
        )
        if not result:
            return {"ok": False}
        return {"ok": True, "path": result[0]}

    def ios_load_catalog_info(self, catalog_path):
        if not catalog_path.lower().endswith(".xcstrings"):
            return {"ok": False, "error": "That doesn't look like a .xcstrings path -- paste or browse to the actual file (e.g. .../Localizable.xcstrings), not the English text you're localizing."}

        catalog = ios_engine.load_catalog(catalog_path)
        if catalog is None:
            return {"ok": False, "error": f"{catalog_path} exists but could not be parsed as a valid .xcstrings file -- refusing to touch it."}

        cfg = config.load_config()
        config.add_recent_path(cfg, catalog_path, key="recent_ios_paths")
        config.save_config(cfg)

        return {"ok": True, "existing_key_count": len(catalog.get("strings", {}))}

    def ios_translate_and_add(self, catalog_path, key, english_text, context, target_codes, provider):
        threading.Thread(
            target=self._ios_translate_and_add_thread,
            args=(catalog_path, key, english_text, context, list(target_codes), provider),
            daemon=True,
        ).start()
        return {"ok": True}

    def _ios_translate_and_add_thread(self, catalog_path, key, english_text, context, target_codes, provider):
        try:
            api_key = config.get_api_key(provider)
            client, model_name = providers.get_client(provider, api_key)
        except Exception as e:
            self._emit("onIosAddError", str(e))
            return

        catalog = ios_engine.load_catalog(catalog_path)
        if catalog is None:
            self._emit("onIosAddError", f"{catalog_path} exists but could not be parsed as a valid .xcstrings file -- refusing to write to it.")
            return

        target_langs = {c: n for c, n in ios_engine.IOS_LANG_DISPLAY_NAMES.items() if c in target_codes}

        def on_retry(attempt, n_pending):
            self._emit("onIosAddLog", f"Retry {attempt}: {n_pending} language(s) still missing, retrying...")

        try:
            translations, still_missing = ios_engine.translate_string_with_retry(
                provider, client, english_text, context, target_langs, on_retry=on_retry,
            )
        except Exception as e:
            self._emit("onIosAddError", str(e))
            return

        merge_result = ios_engine.add_string_to_catalog(catalog, key, english_text, translations, context=context)
        try:
            ios_engine.save_catalog(catalog_path, catalog)
        except Exception as e:
            self._emit("onIosAddError", f"Translated successfully but failed to write {catalog_path}: {e}")
            return

        self._emit("onIosAddDone", {
            "key": key,
            "english_text": english_text,
            "translations": translations,
            "added": merge_result["added"],
            "skipped_existing": merge_result["skipped_existing"],
            "still_missing": still_missing,
        })

    def ios_upload_session_to_sheet(self, session_entries, provider):
        threading.Thread(
            target=self._ios_upload_session_thread,
            args=(list(session_entries), provider),
            daemon=True,
        ).start()
        return {"ok": True}

    def _ios_upload_session_thread(self, session_entries, provider):
        cfg = config.load_config()
        sheet_id = cfg.get("google_sheet_id", "")
        sa_path = cfg.get("service_account_path", "")
        if not sheet_id or not sa_path:
            self._emit("onIosSheetUploadError", "Sheet ID or service account file isn't configured (Settings screen).")
            return

        used_codes = {code for item in session_entries for code in item.get("translations", {})}
        lang_display_list = [ios_engine.IOS_LANG_DISPLAY_NAMES[c] for c in used_codes if c in ios_engine.IOS_LANG_DISPLAY_NAMES]
        lang_display_map = {c: ios_engine.IOS_LANG_DISPLAY_NAMES[c] for c in used_codes if c in ios_engine.IOS_LANG_DISPLAY_NAMES}

        master_sheet = ios_engine.build_sheet_rows_for_session(session_entries, lang_display_map)
        try:
            tab_name = ios_engine.sync_ios_to_google_sheet(sheet_id, sa_path, provider, master_sheet, lang_display_list)
        except Exception as e:
            self._emit("onIosSheetUploadError", str(e) or f"{type(e).__name__} (no message -- see log for details)")
            return
        self._emit("onIosSheetUploadDone", {"tab_name": tab_name, "count": len(session_entries)})

    # --- Import from Sheet ------------------------------------------------
    # The reverse direction of both platforms' Sheet sync above: read rows
    # a reviewer has already QA'd/edited in the Sheet back out, let the
    # user pick which ones, then write them into a local project file.
    # Writing itself reuses engine.append_to_xml_file / ios_engine's
    # add_string_to_catalog+save_catalog -- see sheet_import.py, this is
    # just the Api-layer plumbing (background threads + the event queue,
    # same pattern as every other network/file call in this class).

    def get_service_account_email(self):
        """
        Reads just the client_email field out of the configured service
        account JSON, so Settings/Import can show it directly instead of
        sending the user to go dig it out of the file themselves.
        Deliberately reads nothing else out of that file -- exposing
        private_key here would defeat the whole point of keeping it out of
        the UI. Returns "" on any error (missing/unset path, unreadable
        file, malformed JSON, missing field) rather than raising -- this is
        a convenience hint, not something that should ever block using the
        app.
        """
        sa_path = config.load_config().get("service_account_path", "")
        if not sa_path:
            return ""
        try:
            with open(sa_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("client_email", "")
        except Exception:
            return ""

    def sheet_list_tabs(self):
        threading.Thread(target=self._sheet_list_tabs_thread, daemon=True).start()
        return {"ok": True}

    def _sheet_list_tabs_thread(self):
        # Sheet ID and service account both come from the shared Settings
        # config now -- Import no longer has its own override fields, so
        # there's a single source of truth for "which sheet/account".
        cfg = config.load_config()
        sheet_id = cfg.get("google_sheet_id", "")
        sa_path = cfg.get("service_account_path", "")
        if not sheet_id:
            self._emit("onSheetTabsError", "Set a Google Sheet ID on the Settings screen first.")
            return
        if not sa_path:
            self._emit("onSheetTabsError", "Set a service account JSON on the Settings screen first.")
            return
        try:
            tabs = sheet_import.list_worksheets(sheet_id, sa_path)
        except Exception as e:
            self._emit("onSheetTabsError", str(e) or f"{type(e).__name__} (no message -- see log for details)")
            return
        self._emit("onSheetTabsDone", tabs)

    def sheet_fetch_tab(self, tab_name):
        threading.Thread(target=self._sheet_fetch_tab_thread, args=(tab_name,), daemon=True).start()
        return {"ok": True}

    def _sheet_fetch_tab_thread(self, tab_name):
        cfg = config.load_config()
        sheet_id = cfg.get("google_sheet_id", "")
        sa_path = cfg.get("service_account_path", "")
        if not sheet_id:
            self._emit("onSheetFetchError", "Set a Google Sheet ID on the Settings screen first.")
            return
        if not sa_path:
            self._emit("onSheetFetchError", "Set a service account JSON on the Settings screen first.")
            return
        try:
            result = sheet_import.fetch_sheet_rows(sheet_id, sa_path, tab_name)
        except Exception as e:
            self._emit("onSheetFetchError", str(e) or f"{type(e).__name__} (no message -- see log for details)")
            return
        self._emit("onSheetFetchDone", result)

    def sheet_import_write(self, platform, path, selected_rows):
        threading.Thread(
            target=self._sheet_import_write_thread,
            args=(platform, path, list(selected_rows)),
            daemon=True,
        ).start()
        return {"ok": True}

    def _sheet_import_write_thread(self, platform, path, selected_rows):
        try:
            if platform == "android":
                base_res_path = os.path.dirname(os.path.dirname(path))
                result = sheet_import.import_to_android(base_res_path, selected_rows)
                self._emit("onSheetImportDone", {"platform": "android", **result})
            else:
                result = sheet_import.import_to_ios(path, selected_rows)
                self._emit("onSheetImportDone", {"platform": "ios", **result})
        except Exception as e:
            self._emit("onSheetImportError", str(e) or f"{type(e).__name__} (no message -- see log for details)")


def main():
    api = Api()
    window = webview.create_window(
        "Automate Localization",
        url=os.path.join(WEB_DIR, "index.html"),
        js_api=api,
        width=1100,
        height=780,
        min_size=(820, 600),
    )
    api.set_window(window)
    webview.start(icon=ICON_PATH)


if __name__ == "__main__":
    main()

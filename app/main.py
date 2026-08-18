"""
Desktop app entry point (pywebview). Exposes an Api object to the JS
frontend in web/index.html; the Python side is the engine from engine.py
called directly, no HTTP server involved.
"""

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
import providers
import updater
from version import APP_VERSION

WEB_DIR = os.path.join(APP_DIR, "web")
ICON_PATH = os.path.join(APP_DIR, "icon.ico")


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

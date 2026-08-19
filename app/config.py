"""
Local app config (recent paths, provider settings, batch/retry settings,
sheet settings) plus API-key storage via the OS keychain.

API keys are NEVER written to the local config file -- only to the OS
keychain via `keyring`. The config file only holds non-secret preferences.
"""

import json
import os
import sys

import keyring

APP_NAME = "AutomateLocalization"
KEYRING_SERVICE = APP_NAME

# The app was originally named SmartLocalizationAutomation -- these let an
# existing install transparently pick up its old config/API keys after the
# rename instead of the user having to redo setup.
_LEGACY_APP_NAME = "SmartLocalizationAutomation"
_LEGACY_KEYRING_SERVICE = _LEGACY_APP_NAME

DEFAULT_CONFIG = {
    "recent_paths": [],
    "last_provider": "gemini",
    "batch_size": 25,
    "max_retries": 10,
    "sheet_sync_enabled": True,
    "google_sheet_id": "",
    "service_account_path": "",
}


def _config_base_dir():
    if sys.platform == "win32":
        return os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    else:
        return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def get_config_dir():
    d = os.path.join(_config_base_dir(), APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def get_config_path():
    return os.path.join(get_config_dir(), "config.json")


def _legacy_config_path():
    return os.path.join(_config_base_dir(), _LEGACY_APP_NAME, "config.json")


def load_config():
    path = get_config_path()
    if not os.path.exists(path):
        legacy_path = _legacy_config_path()
        if os.path.exists(legacy_path):
            path = legacy_path
        else:
            return dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(data)
        return cfg
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(cfg):
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def add_recent_path(cfg, path):
    paths = cfg.get("recent_paths", [])
    paths = [p for p in paths if p != path]
    paths.insert(0, path)
    cfg["recent_paths"] = paths[:5]
    return cfg


def remove_recent_path(cfg, path):
    cfg["recent_paths"] = [p for p in cfg.get("recent_paths", []) if p != path]
    return cfg


# --- API keys (OS keychain, never in config.json / never in source) --------

def get_api_key(provider):
    try:
        key = keyring.get_password(KEYRING_SERVICE, provider)
        if key:
            return key
        legacy_key = keyring.get_password(_LEGACY_KEYRING_SERVICE, provider)
        if legacy_key:
            keyring.set_password(KEYRING_SERVICE, provider, legacy_key)
            return legacy_key
        return ""
    except Exception:
        return ""


def set_api_key(provider, key):
    keyring.set_password(KEYRING_SERVICE, provider, key)


def has_api_key(provider):
    return bool(get_api_key(provider))


def delete_api_key(provider):
    try:
        keyring.delete_password(KEYRING_SERVICE, provider)
    except Exception:
        pass

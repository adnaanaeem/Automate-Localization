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

APP_NAME = "SmartLocalizationAutomation"
KEYRING_SERVICE = APP_NAME

DEFAULT_CONFIG = {
    "recent_paths": [],
    "last_provider": "gemini",
    "batch_size": 25,
    "max_retries": 2,
    "sheet_sync_enabled": False,
    "google_sheet_id": "",
    "service_account_path": "",
}


def get_config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def get_config_path():
    return os.path.join(get_config_dir(), "config.json")


def load_config():
    path = get_config_path()
    if not os.path.exists(path):
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


# --- API keys (OS keychain, never in config.json / never in source) --------

def get_api_key(provider):
    try:
        return keyring.get_password(KEYRING_SERVICE, provider) or ""
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

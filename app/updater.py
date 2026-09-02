"""
Checks GitHub Releases for a newer version and can download + launch the
installer for it. Stdlib-only (urllib) so it works identically whether
running from source or as a frozen .exe -- no extra packaging dependency.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

REPO = "adnaanaeem/Automate-Localization"
API_LATEST_RELEASE = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALLER_ASSET_NAME = "AutomateLocalizationSetup.exe"
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "AutomateLocalization"}


def _parse_version(v):
    """'v1.2.3' or '1.2.3' -> (1, 2, 3), for a plain tuple comparison."""
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) or (0,)


def check_for_update(current_version, timeout=5):
    """
    Returns {'available': False} if already up to date, the latest release
    has no installer asset, or the check fails for any reason (network
    errors are swallowed on purpose -- a failed update check must never
    block using the app). Otherwise returns
    {'available': True, 'version', 'notes', 'download_url'}.
    """
    try:
        req = urllib.request.Request(API_LATEST_RELEASE, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"available": False}

    latest_tag = data.get("tag_name", "")
    if _parse_version(latest_tag) <= _parse_version(current_version):
        return {"available": False}

    download_url = next(
        (a.get("browser_download_url") for a in data.get("assets", [])
         if a.get("name") == INSTALLER_ASSET_NAME),
        None,
    )
    if not download_url:
        return {"available": False}

    return {
        "available": True,
        "version": latest_tag,
        "notes": data.get("body", ""),
        "download_url": download_url,
    }


def download_and_launch_installer(download_url, on_progress=None):
    """
    Downloads the installer to a temp file and launches it. Does NOT exit
    this process -- the caller must do that once this returns, so the
    installer (which waits for/closes the running app via its
    CloseApplications setting) can replace files cleanly. Raises on
    download failure.
    """
    installer_path = os.path.join(tempfile.gettempdir(), INSTALLER_ASSET_NAME)

    req = urllib.request.Request(download_url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        with open(installer_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)

    # Detach the installer so it survives this process exiting right after.
    # subprocess.DETACHED_PROCESS/CREATE_NEW_PROCESS_GROUP only exist on
    # Windows (AttributeError on Mac/Linux) -- there's no shipped installer
    # asset for those platforms yet (INSTALLER_ASSET_NAME above is Windows-
    # only, so check_for_update() never reports an update on them and this
    # function is unreachable there today), but this is cheap to make
    # correct now rather than leave as a landmine for whenever that changes.
    if sys.platform == "win32":
        subprocess.Popen(
            [installer_path],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        subprocess.Popen([installer_path], start_new_session=True)
    return installer_path

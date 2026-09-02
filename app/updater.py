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
# Was hardcoded to the Windows installer only, which meant check_for_update()
# silently never reported an update on macOS -- it found a newer tag, then
# failed to find "AutomateLocalizationSetup.exe" among that release's assets
# (only "AutomateLocalization.dmg" is there) and gave up quietly. Now picks
# the asset name that actually exists for the platform this is running on.
INSTALLER_ASSET_NAME = "AutomateLocalization.dmg" if sys.platform == "darwin" else "AutomateLocalizationSetup.exe"
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
    Downloads the installer/disk-image to a temp file and opens it.

    On Windows this behaves as a real silent handoff: the .exe installer is
    launched detached (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP) so it
    survives this process exiting, and its CloseApplications setting waits
    for that exit before it can replace the running exe's files -- the
    caller must exit right after this returns.

    On macOS there's no equivalent "close the app, replace it, relaunch"
    flow for a .dmg -- `open`ing it just mounts it in Finder, the same as
    double-clicking a freshly downloaded one, and the user drags the app
    into Applications themselves. There's nothing here for the running app
    to wait for or exit over, so **the caller should not exit the process**
    on this platform, unlike Windows.

    Raises on download failure.
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

    if sys.platform == "win32":
        subprocess.Popen(
            [installer_path],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    elif sys.platform == "darwin":
        subprocess.Popen(["open", installer_path])
    else:
        subprocess.Popen([installer_path], start_new_session=True)
    return installer_path

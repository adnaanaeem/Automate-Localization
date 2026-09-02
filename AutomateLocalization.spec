# -*- mode: python ; coding: utf-8 -*-
import sys

from PyInstaller.utils.hooks import collect_all

sys.path.insert(0, "app")
from version import APP_VERSION  # noqa: E402

IS_MACOS = sys.platform == "darwin"

datas = [('app/web', 'web'), ('app/icon.ico', '.'), ('app/icon.icns', '.')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('google.generativeai')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('google.ai.generativelanguage')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('grpc')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('gspread')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('oauth2client')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('keyring')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app/main.py'],
    pathex=['app'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'pandas', 'pyarrow', 'tkinter', '_tkinter', 'IPython', 'notebook', 'jupyter', 'scipy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# --onedir, not --onefile: a onefile exe re-extracts itself to a fresh
# %TEMP%\_MEI* folder on every launch, which is a well-documented source of
# "Failed to load Python DLL" errors (antivirus interference, extraction
# races) on end-user machines. onedir extracts once at build time instead --
# no per-launch extraction step, so that whole failure class goes away. The
# Windows installer bundles the resulting folder (see installer/setup.iss);
# on macOS, COLLECT's output instead becomes BUNDLE's input below, producing
# a normal double-clickable .app (itself just a folder under the hood, same
# "extract once at build time" property applies).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AutomateLocalization',
    icon='app/icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AutomateLocalization',
)

if IS_MACOS:
    # macOS-only: wraps COLLECT's onedir output into a proper .app bundle
    # (Info.plist, dock icon, double-click launch). Not signed or notarized
    # -- no Apple Developer certificate available to this build -- so
    # Gatekeeper will refuse a plain double-click on a fresh download the
    # same way Windows SmartScreen flags the unsigned .exe; the CI workflow
    # and README both call this out rather than claiming it "just works".
    app = BUNDLE(
        coll,
        name='AutomateLocalization.app',
        icon='app/icon.icns',
        bundle_identifier='com.adnaanaeem.automatelocalization',
        version=APP_VERSION,
        info_plist={
            'CFBundleName': 'Automate Localization',
            'CFBundleDisplayName': 'Automate Localization',
            'CFBundleShortVersionString': APP_VERSION,
            'CFBundleVersion': APP_VERSION,
            'NSHighResolutionCapable': True,
            'NSHumanReadableCopyright': 'Adnan Naeem',
        },
    )

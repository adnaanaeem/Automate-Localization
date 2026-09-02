; Inno Setup script for Automate Localization.
; Build with: python -m PyInstaller AutomateLocalization.spec --noconfirm  (produces the
;             dist\AutomateLocalization\ folder -- onedir, not onefile, see the .spec's
;             comment for why)
; then:       "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
; Output:     dist_installer\AutomateLocalizationSetup.exe
;
; MyAppVersion must match app/version.py's APP_VERSION -- updater.py compares
; the GitHub release tag against that value, not this one, but keeping them
; in sync avoids a confusing mismatch between "installed version" (shown by
; Windows' Add/Remove Programs, driven by this file) and what the app itself
; reports.

#define MyAppName "Automate Localization"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "Adnan Naeem"
#define MyAppExeName "AutomateLocalization.exe"
#define MyAppURL "https://github.com/adnaanaeem/Automate-Localization"

[Setup]
AppId={{B4E1F2A0-6C3D-4E7A-9B2F-3D6C8E1A9F02}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
SetupIconFile=..\app\icon.ico
; Per-user install by default (no UAC prompt); the wizard still offers an
; "install for all users" option if the user explicitly wants it.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist_installer
OutputBaseFilename=AutomateLocalizationSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Detects a running instance of the app and offers to close it before
; installing/updating -- what makes "download the new installer and run it"
; a smooth update instead of a "file in use" error.
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\AutomateLocalization\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  SHCNE_ASSOCCHANGED = $8000000;
  SHCNF_IDLIST = $0;

procedure SHChangeNotify(wEventId: Longint; uFlags: Longint; dwItem1: Longint; dwItem2: Longint);
external 'SHChangeNotify@shell32.dll stdcall';

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // Windows caches shortcut/exe icons aggressively -- updating the exe in
  // place (same path) doesn't reliably make Explorer notice the icon
  // changed on its own. Nudge the shell to refresh after install/update.
  if CurStep = ssPostInstall then
    SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0);
end;

; Inno Setup script for Automate Localization.
; Build with: python -m PyInstaller AutomateLocalization.spec --noconfirm  (produces dist\AutomateLocalization.exe)
; then:       "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
; Output:     dist_installer\AutomateLocalizationSetup.exe
;
; MyAppVersion must match app/version.py's APP_VERSION -- updater.py compares
; the GitHub release tag against that value, not this one, but keeping them
; in sync avoids a confusing mismatch between "installed version" (shown by
; Windows' Add/Remove Programs, driven by this file) and what the app itself
; reports.

#define MyAppName "Automate Localization"
#define MyAppVersion "1.1.0"
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
Source: "..\dist\AutomateLocalization.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

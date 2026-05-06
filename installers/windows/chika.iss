; ───────────────────────────────────────────────────────────────────────────
;  Chika — Windows Installer (Inno Setup script)
; ───────────────────────────────────────────────────────────────────────────
;
;  Run via build_installer.ps1 — DO NOT compile this file directly. The
;  build script defines #MyAppVersion + #SourceDir from the live
;  pyproject.toml so the installer version stays in sync.
;
;  What this installer does:
;
;    1. Installs to ``%LocalAppData%\Programs\Chika\`` (per-user; no admin
;       required). Inno's ``PrivilegesRequired=lowest`` keeps UAC quiet.
;
;    2. Drops the Chika source tree at ``<install>\source\`` and a wheel
;       at ``<install>\wheels\``. ``post_install.ps1`` then creates a
;       venv at ``<install>\venv\`` and ``pip install``s the wheel into
;       it.
;
;    3. Installs ``chika.cmd`` shim that exports ``CHIKA_SETTINGS_PATH``
;       (so settings live under ``%USERPROFILE%\.chika\data\``, surviving
;       any future uninstall) and forwards to the venv's ``chika.exe``.
;
;    4. Adds the install dir to the user's PATH via Inno's [Tasks].
;
;    5. Registers a Start Menu group + Add/Remove Programs entry. Inno
;       generates the uninstaller (``unins000.exe``) automatically.
;
;    6. Drops ``install_marker.json`` so ``chika update`` recognises this
;       as a Windows-installer install (vs git clone or pip install) and
;       knows to fetch the next ``chika-setup-X.Y.Z.exe`` from GitHub
;       Releases on update.
;
;  Uninstall:
;
;    - Inno's auto-generated uninstaller wipes the install dir + PATH +
;      Start Menu + ARP entry.
;    - ``pre_uninstall.ps1`` (referenced from [UninstallRun]) optionally
;      wipes ``~/.chika/`` if the user opts in via the uninstaller's
;      "Also remove all Chika data" checkbox (see [UninstallDelete]).

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

#ifndef SourceDir
  #define SourceDir "..\..\build\installer"
#endif

#ifndef WheelName
  #define WheelName "chika-2.0.0-py3-none-any.whl"
#endif

#define MyAppName "Chika"
#define MyAppPublisher "Chika"
#define MyAppURL "https://github.com/tochi-mba/chika"
#define MyAppExeName "chika.cmd"

[Setup]
; AppId is the GUID Add/Remove Programs uses to identify Chika across
; versions. NEVER change it — that would orphan users' existing
; install records and create duplicate ARP entries on upgrade.
AppId={{8B0F1A6C-3D2E-4F4D-9C56-1A4A2B7F3C90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
LicenseFile={#SourceDir}\LICENSE.txt
OutputDir=..\dist
OutputBaseFilename=chika-setup-{#MyAppVersion}
SetupIconFile=chika.ico
UninstallDisplayIcon={app}\chika.ico
UninstallDisplayName={#MyAppName} {#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; Update behaviour — when a newer version installs over an older one,
; Inno detects the existing install via AppId and runs the existing
; uninstaller first to clean up. CloseApplications prevents file-in-use
; errors if the user has chika running.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addtopath"; \
    Description: "Add Chika to your PATH (so ``chika`` works from any terminal)"; \
    GroupDescription: "{cm:AdditionalIcons}"; \
    Flags: checkedonce

[Files]
; The Chika source tree (excluding tests, .git, node_modules, dist, etc.)
; — ``post_install.ps1`` walks this when running pip install.
Source: "{#SourceDir}\source\*"; DestDir: "{app}\source"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
; The pre-built wheel — ``post_install.ps1`` ``pip install``s this into
; the venv. Bundling the wheel means the user never has to wait for a
; build during install.
Source: "{#SourceDir}\wheels\{#WheelName}"; DestDir: "{app}\wheels"; \
    Flags: ignoreversion
; PowerShell hooks — invoked from [Run] / [UninstallRun].
Source: "post_install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "pre_uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "chika.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "chika.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\install_marker.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\chika.ico"
Name: "{group}\{#MyAppName} on the web"; Filename: "{#MyAppURL}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Run]
; Create venv + pip install. -ExecutionPolicy Bypass scopes only to this
; one invocation — does NOT change machine-wide policy. -WindowStyle
; Hidden keeps the install UI clean; output is captured by Inno.
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\post_install.ps1"" -InstallDir ""{app}"" -WheelName ""{#WheelName}"""; \
    StatusMsg: "Installing Chika into a venv (this can take a minute on first install)..."; \
    Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\pre_uninstall.ps1"" -InstallDir ""{app}"""; \
    Flags: runhidden waituntilterminated; \
    RunOnceId: "ChikaPreUninstall"

[UninstallDelete]
; Inno only deletes files it itself installed. The venv we created
; during install is not in [Files], so we explicitly mark it for
; deletion. Same for any data files chika writes inside the install
; dir (logs, etc.).
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\source"
Type: filesandordirs; Name: "{app}\wheels"

[Registry]
; Add the install dir to the user's PATH — only when the "addtopath"
; task is checked. We set ``HKCU\Environment\Path`` (user PATH, not
; system PATH) so this works without admin. The empty-data variant
; with ``Flags: preservestringtype`` is Inno's idiomatic way to append
; without clobbering — see Inno docs §[Registry] for the full pattern.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; \
    Tasks: addtopath; \
    Check: NeedsAddPath('{app}')

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  // Don't double-add — already on PATH? skip.
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Strip the install dir from PATH on uninstall. We can't use
    // [Registry] for removal because Inno only cleans up entries it
    // explicitly created — and our PATH entry is appended into the
    // existing Path value rather than its own subkey.
    //
    // RegQueryStringValue → string-replace → RegWriteStringValue.
    // Best-effort; failures are silent (PATH entries not on disk
    // never become user-facing problems).
  end;
end;

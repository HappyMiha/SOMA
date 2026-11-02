[Setup]
AppId={{6E776649-ECA7-47A7-9A36-7775AD4F13A8}
AppName=SOMA
AppVersion=0.2.0
DefaultDirName={localappdata}\Programs\SOMA
DefaultGroupName=SOMA
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir=..\..\artifacts\win32
OutputBaseFilename=SOMA-0.2.0-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\SOMA.exe

[Tasks]
Name: autostart; Description: "Start SOMA after sign-in to this desktop session"; Flags: checkedonce
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\win32\SOMA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove only the obsolete, proven-conflicting libraries from prior SOMA bundles.
Type: files; Name: "{app}\_internal\icuuc.dll"
Type: files; Name: "{app}\_internal\icudt78.dll"

[Icons]
Name: "{group}\SOMA"; Filename: "{app}\SOMA.exe"
Name: "{userdesktop}\SOMA"; Filename: "{app}\SOMA.exe"; Tasks: desktopicon
Name: "{userstartup}\SOMA"; Filename: "{app}\SOMA.exe"; Tasks: autostart

[Run]
Filename: "{app}\SOMA.exe"; Description: "Open SOMA"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\SOMA.exe"; Parameters: "--quit"; RunOnceId: "SaveSomaState"; Flags: runhidden waituntilterminated

[Code]
{ Let a running SOMA checkpoint and exit before files are replaced,
  instead of relying on Restart Manager to close it. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  if FileExists(ExpandConstant('{app}\SOMA.exe')) then
    Exec(ExpandConstant('{app}\SOMA.exe'), '--quit', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

; The world and its inhabitants' homes under LOCALAPPDATA\SOMA are intentionally preserved on
; upgrade/uninstall. No application files are touched by the runtime.

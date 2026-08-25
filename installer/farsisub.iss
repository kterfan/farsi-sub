; Inno Setup script for FarsiSub.
;
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\farsisub.iss
;
; Installs per user, into LocalAppData\Programs, so no administrator rights are
; needed and the program folder stays writable -- which is what lets the app
; keep its models and settings beside itself.

#define AppName "FarsiSub"
#define AppVersion "1.1"
#define AppPublisher "Erfan"
#define AppExe "FarsiSub.exe"

[Setup]
AppId={{8E4C1F72-3B21-4A5E-9C6D-FA7B25D40E11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=FarsiSub-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The model weights are downloaded on first run, so the installer itself only
; has to carry the program and the engine.
DiskSpanning=no
UninstallDisplayName={#AppName} {#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "ساخت میان‌بر روی دسکتاپ"; GroupDescription: "میان‌برها"; Flags: checkedonce

[Files]
; data\ holds models, logs and the glossary: it belongs to whoever runs the
; program, never to the installer.
Source: "..\dist\FarsiSub\*"; DestDir: "{app}"; Excludes: "data\*,data"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\حذف {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "اجرای {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Logs and cached projects are ours; models and the glossary are the user's, so
; they are deliberately left behind.
Type: filesandordirs; Name: "{app}\data\logs"

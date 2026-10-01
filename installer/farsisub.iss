; Inno Setup script for FarsiSub.
;
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\farsisub.iss
;
; Installs per user, into LocalAppData\Programs, so no administrator rights are
; needed and the program folder stays writable -- which is what lets the app
; keep its models and settings beside itself.
;
; The wizard is Persian and right to left (installer\Farsi.isl, the unofficial
; translation from the Inno Setup repository). Its images come from
; assets\brand, rendered by tools\make_brand.py from the same mark the app
; draws.

#define AppName "FarsiSub"
#define AppNameFa "فارسی‌ساب"
; Same number as __version__ in src/farsisub/__init__.py.
#define AppVersion "1.7.0"
#define AppPublisher "Erfan Esmailzadeh (عرفان اسمعیل‌زاده)"
#define AppUrl "https://github.com/kterfan/farsi-sub"
#define AppExe "FarsiSub.exe"

[Setup]
; Never change the AppId: it is what makes a new version install over the old.
AppId={{8E4C1F72-3B21-4A5E-9C6D-FA7B25D40E11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
AppCopyright=© Erfan Esmailzadeh · MIT
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Erfan Esmailzadeh
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=FarsiSub-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
WizardImageFile=..\assets\brand\wizard.bmp,..\assets\brand\wizard-2x.bmp
WizardSmallImageFile=..\assets\brand\wizard-small.bmp,..\assets\brand\wizard-small-2x.bmp
WizardImageStretch=yes
SetupIconFile=..\assets\brand\farsisub.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
ShowLanguageDialog=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The model weights are downloaded on first run, so the installer itself only
; has to carry the program and the engine.
DiskSpanning=no
; Closing a running copy first: replacing files under a live app fails.
CloseApplications=yes

[Languages]
Name: "farsi"; MessagesFile: "Farsi.isl"

[Messages]
WelcomeLabel1=به {#AppName} خوش آمدی
WelcomeLabel2={#AppNameFa} نسخه {#AppVersion} روی این کامپیوتر نصب می‌شود.%n%nزیرنویس فارسی از روی ویدیو، کاملاً روی همین کامپیوتر؛ بدون اینترنت و بدون فرستادن فایل به جایی.%n%nاگر نسخه قبلی نصب است، روی همان نصب می‌شود و مدل‌ها، دیکشنری و پروژه‌هایت دست نمی‌خورند.%n%nطراحی و برنامه‌نویسی: عرفان اسمعیل‌زاده — Erfan Esmailzadeh%ngithub.com/kterfan/farsi-sub
FinishedHeadingLabel=نصب {#AppName} تمام شد
FinishedLabel={#AppNameFa} آماده است. از میان‌بر روی دسکتاپ یا منوی استارت اجرا می‌شود.%n%nساخته‌ی عرفان اسمعیل‌زاده · github.com/kterfan/farsi-sub

[Tasks]
Name: "desktopicon"; Description: "ساخت میان‌بر روی دسکتاپ"; GroupDescription: "میان‌برها"; Flags: checkedonce

[Files]
; data\ holds models, logs and the glossary: it belongs to whoever runs the
; program, never to the installer. The leading backslash anchors the pattern
; to the top level -- without it Inno also dropped _internal\hazm\data, and
; the app died on its first Persian sentence.
Source: "..\dist\FarsiSub\*"; DestDir: "{app}"; Excludes: "\data\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "زیرنویس فارسی از روی ویدیو"
Name: "{group}\صفحه پروژه در گیت‌هاب"; Filename: "{#AppUrl}"
Name: "{group}\حذف {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; Comment: "زیرنویس فارسی از روی ویدیو"

[Run]
Filename: "{app}\{#AppExe}"; Description: "اجرای {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Logs and cached projects are ours; models and the glossary are the user's, so
; they are deliberately left behind.
Type: filesandordirs; Name: "{app}\data\logs"

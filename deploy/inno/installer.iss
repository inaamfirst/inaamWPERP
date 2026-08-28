#define MyAppName "Enterprise Commerce ERP"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "ChoiceOye"
#define MyAppExeName "erp-desktop.exe"

[Setup]
AppId={{2F7A8611-A5CF-4E3D-B7F4-6E5F05833B57}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ChoiceOye\Enterprise Commerce ERP
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=EnterpriseCommerceERP-Setup-{#MyAppVersion}
OutputDir=..\..\release_builds\installer
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
WizardStyle=modern
UninstallDisplayIcon={app}\erp-desktop\{#MyAppExeName}
; Configure code signing in CI or the release workstation, for example:
; SignTool=signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a $f

[Dirs]
Name: "{commonappdata}\ChoiceOye\Enterprise Commerce ERP\runtime_data"
Name: "{commonappdata}\ChoiceOye\Enterprise Commerce ERP\runtime_data\logs"
Name: "{commonappdata}\ChoiceOye\Enterprise Commerce ERP\runtime_data\diagnostics"
Name: "{commonappdata}\ChoiceOye\Enterprise Commerce ERP\runtime_data\uploads"
Name: "{commonappdata}\ChoiceOye\Enterprise Commerce ERP\runtime_data\license"
Name: "{commonappdata}\ChoiceOye\Enterprise Commerce ERP\backups"

[Files]
Source: "..\..\release_builds\dist\erp-api\*"; DestDir: "{app}\erp-api"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\release_builds\dist\erp-worker\*"; DestDir: "{app}\erp-worker"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\release_builds\dist\erp-desktop\*"; DestDir: "{app}\erp-desktop"; Flags: ignoreversion recursesubdirs createallsubdirs
; Includes launchers, migrate_database.ps1, preflight/task tooling, and PostgreSQL backup/restore scripts.
Source: "..\..\release_builds\dist\*.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\release_builds\dist\env.production.example"; DestDir: "{commonappdata}\ChoiceOye\Enterprise Commerce ERP"; DestName: "production.env.example"; Flags: ignoreversion

[Icons]
Name: "{group}\Enterprise Commerce ERP"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start_desktop.ps1"""; WorkingDir: "{app}"
Name: "{commondesktop}\Enterprise Commerce ERP"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start_desktop.ps1"""; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\uninstall_managed_tasks.ps1"""; Flags: runhidden
; 免费投屏 NealCast — Windows 安装包
; 编译：ISCC.exe installer.iss

#define MyAppName "免费投屏 NealCast"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "NealCast contributors"
#define MyAppExeName "NealCast.exe"

[Setup]
AppId={{7B2E1C4A-9F3D-4E8B-A1C6-2D5F8E9A0B31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\NealCast
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=NealCast-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; 装到用户目录，免管理员、不弹 UAC
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; ffmpeg 为独立第三方程序（GPL v3），随包分发需附其许可证文本
Source: "ffmpeg.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "ffmpeg-LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

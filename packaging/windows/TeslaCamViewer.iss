#define AppName "TeslaCamViewer"
#define AppVersion GetEnv("TESLACAMVIEWER_VERSION")
#if AppVersion == ""
#define AppVersion "0.1.0"
#endif
#define SourceDir "..\..\dist\TeslaCamViewer.dist"
#define OutputDir "..\..\dist\installer"

[Setup]
AppId={{E5E2F2E1-7E55-4D8B-8AF4-4A62B3F3220B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=TeslaCamViewer
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile={#SourceDir}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=TeslaCamViewer-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\qtTeslaCam.exe

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TeslaCamViewer"; Filename: "{app}\qtTeslaCam.exe"
Name: "{autodesktop}\TeslaCamViewer"; Filename: "{app}\qtTeslaCam.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\qtTeslaCam.exe"; Description: "Launch TeslaCamViewer"; Flags: nowait postinstall skipifsilent

; Instalador do LeafDraw (Inno Setup 6). Gerado por packaging/build.ps1:
;   ISCC.exe /DAppVersion=0.1.0b1 /DDistDir=..\dist\LeafDraw packaging\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist\LeafDraw"
#endif

[Setup]
AppId={{6B3F2C1E-5A7D-4E9B-9C2F-1D4E8A7B6C5F}
AppName=LeafDraw
AppVersion={#AppVersion}
AppVerName=LeafDraw {#AppVersion}
AppPublisher=LeafDraw
AppPublisherURL=https://github.com/francisreboucas/leafdraw
AppSupportURL=https://github.com/francisreboucas/leafdraw/issues
DefaultDirName={autopf}\LeafDraw
DefaultGroupName=LeafDraw
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=LeafDraw-{#AppVersion}-setup
SetupIconFile=leafdraw.ico
UninstallDisplayIcon={app}\LeafDraw.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; sem administrador por padrão; o usuário pode escolher instalar para todos
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "Abrir arquivos .leaf com o LeafDraw"; GroupDescription: "Associações:"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LeafDraw"; Filename: "{app}\LeafDraw.exe"
Name: "{autodesktop}\LeafDraw"; Filename: "{app}\LeafDraw.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.leaf"; ValueType: string; ValueName: ""; ValueData: "LeafDraw.Project"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\LeafDraw.Project"; ValueType: string; ValueName: ""; ValueData: "Projeto LeafDraw"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\LeafDraw.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\LeafDraw.exe,0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\LeafDraw.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\LeafDraw.exe"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\LeafDraw.exe"; Description: "{cm:LaunchProgram,LeafDraw}"; Flags: nowait postinstall skipifsilent

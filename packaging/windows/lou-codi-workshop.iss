#ifndef AppVersion
  #define AppVersion "2.0.0a7"
#endif
#ifndef ProjectDir
  #define ProjectDir "."
#endif

[Setup]
AppId={{7F850D63-0D6B-4C7E-A4A4-6BF7D8AB48C3}
AppName=Lou Còdi Workshop
AppVersion={#AppVersion}
AppPublisher=Lou Còdi
AppPublisherURL=https://github.com/preventionpaca/pdf-converter-lou-codi
DefaultDirName={localappdata}\Programs\Lou Còdi Workshop
DefaultGroupName=Lou Còdi Workshop
DisableProgramGroupPage=yes
OutputDir={#ProjectDir}\dist\installers
OutputBaseFilename=Lou-Codi-Workshop-{#AppVersion}-Setup-x64
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
SetupLogging=yes
UninstallDisplayIcon={app}\lou-codi-pdf-converter.exe
VersionInfoVersion=2.0.0.7

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Types]
Name: "full"; Description: "Installation complète (recommandée)"
Name: "custom"; Description: "Installation personnalisée"; Flags: iscustom

[Components]
Name: "core"; Description: "Lou Còdi Workshop (obligatoire)"; Types: full custom; Flags: fixed
Name: "modules"; Description: "Modules du Workshop"; Types: full custom
Name: "modules\pdfstudio"; Description: "PDF Studio"; Types: full custom
Name: "modules\documentstudio"; Description: "Document Studio"; Types: full custom
Name: "modules\cutting"; Description: "Optimisation de découpe"; Types: full custom
Name: "modules\codelab"; Description: "Lou Còdi Code Lab"; Types: full custom
Name: "workspace"; Description: "Dossiers de travail LouCodi dans Téléchargements"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked

[Files]
Source: "{#ProjectDir}\dist\lou-codi-pdf-converter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core
Source: "{#ProjectDir}\src\lou_codi_pdf_converter\assets\lou-codi-document.ico"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "{#ProjectDir}\packaging\modules\enabled.marker"; DestDir: "{app}\selected-modules"; DestName: "pdf_studio.enabled"; Flags: ignoreversion; Components: modules\pdfstudio
Source: "{#ProjectDir}\packaging\modules\enabled.marker"; DestDir: "{app}\selected-modules"; DestName: "document_studio.enabled"; Flags: ignoreversion; Components: modules\documentstudio
Source: "{#ProjectDir}\packaging\modules\enabled.marker"; DestDir: "{app}\selected-modules"; DestName: "cutting_optimization.enabled"; Flags: ignoreversion; Components: modules\cutting
Source: "{#ProjectDir}\packaging\modules\enabled.marker"; DestDir: "{app}\selected-modules"; DestName: "code_lab.enabled"; Flags: ignoreversion; Components: modules\codelab

[InstallDelete]
Type: files; Name: "{app}\selected-modules\*.enabled"

[Dirs]
Name: "{%USERPROFILE}\Downloads\LouCodi\PDF vers Office"; Components: workspace and modules\pdfstudio
Name: "{%USERPROFILE}\Downloads\LouCodi\Documents vers PDF"; Components: workspace and modules\pdfstudio
Name: "{%USERPROFILE}\Downloads\LouCodi\Organiser les PDF"; Components: workspace and modules\pdfstudio
Name: "{%USERPROFILE}\Downloads\LouCodi\Habillage PDF"; Components: workspace and modules\pdfstudio
Name: "{%USERPROFILE}\Downloads\LouCodi\Document Studio"; Components: workspace and modules\documentstudio
Name: "{%USERPROFILE}\Downloads\LouCodi\Optimisation de découpe"; Components: workspace and modules\cutting
Name: "{%USERPROFILE}\Downloads\LouCodi\Code Lab"; Components: workspace and modules\codelab

[Icons]
Name: "{group}\Lou Còdi Workshop"; Filename: "{app}\lou-codi-pdf-converter.exe"; WorkingDir: "{app}"; AppUserModelID: "LouCodi.Workshop"
Name: "{autodesktop}\Lou Còdi Workshop"; Filename: "{app}\lou-codi-pdf-converter.exe"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "LouCodi.Workshop"

[Registry]
Root: HKA; Subkey: "Software\Classes\.code"; ValueType: string; ValueData: "LouCodi.Document"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.cod"; ValueType: string; ValueData: "LouCodi.Document"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.loucodi-document"; ValueType: string; ValueData: "LouCodi.Document"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\LouCodi.Document"; ValueType: string; ValueData: "Document Lou Còdi"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\LouCodi.Document\DefaultIcon"; ValueType: string; ValueData: "{app}\lou-codi-document.ico,0"
Root: HKA; Subkey: "Software\Classes\LouCodi.Document\shell\open\command"; ValueType: string; ValueData: """{app}\lou-codi-pdf-converter.exe"" ""%1"""

[Run]
Filename: "{app}\lou-codi-pdf-converter.exe"; Description: "Lancer Lou Còdi Workshop"; Flags: nowait postinstall skipifsilent

[Code]
function LibreOfficePresent: Boolean;
begin
  Result := FileExists(ExpandConstant('{pf}\LibreOffice\program\soffice.exe')) or
            FileExists(ExpandConstant('{pf32}\LibreOffice\program\soffice.exe'));
end;

procedure InitializeWizard;
var
  Notice: String;
begin
  Notice := 'Les traitements documentaires sont réalisés localement.' + #13#10 + #13#10;
  if LibreOfficePresent then
    Notice := Notice + 'LibreOffice a été détecté : les conversions Office fidèles seront disponibles.'
  else
    Notice := Notice + 'LibreOffice n''a pas été détecté. Lou Còdi utilisera son moteur local allégé pour les documents simples. Les anciens formats, PowerPoint et les mises en page complexes nécessitent LibreOffice, qui reste facultatif et indépendant.';
  MsgBox(Notice, mbInformation, MB_OK);
end;

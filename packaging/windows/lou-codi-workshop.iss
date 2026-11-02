#ifndef AppVersion
  #define AppVersion "2.0.0a21"
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
SetupIconFile={#ProjectDir}\src\lou_codi_pdf_converter\assets\lou-codi-workshop.ico
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes
UninstallDisplayName=Lou Còdi Workshop
UninstallDisplayIcon={app}\lou-codi-pdf-converter.exe
VersionInfoVersion=2.0.0.21
VersionInfoDescription=Installation de Lou Còdi Workshop

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Files]
Source: "{#ProjectDir}\dist\lou-codi-pdf-converter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectDir}\src\lou_codi_pdf_converter\assets\lou-codi-document.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectDir}\src\lou_codi_pdf_converter\assets\lou-codi-workshop.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectDir}\packaging\modules\enabled.marker"; DestDir: "{app}\selected-modules"; DestName: "pdf_studio.enabled"; Flags: ignoreversion
Source: "{#ProjectDir}\packaging\modules\enabled.marker"; DestDir: "{app}\selected-modules"; DestName: "document_studio.enabled"; Flags: ignoreversion
Source: "{#ProjectDir}\packaging\modules\enabled.marker"; DestDir: "{app}\selected-modules"; DestName: "cutting_optimization.enabled"; Flags: ignoreversion
Source: "{#ProjectDir}\packaging\modules\enabled.marker"; DestDir: "{app}\selected-modules"; DestName: "code_lab.enabled"; Flags: ignoreversion
Source: "{#ProjectDir}\packaging\modules\enabled.marker"; DestDir: "{app}\selected-modules"; DestName: "codi_space.enabled"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{app}\selected-modules\*.enabled"
Type: filesandordirs; Name: "{localappdata}\LouCodi\Workshop"

[Dirs]
Name: "{%USERPROFILE}\Downloads\LouCodi\PDF vers Office"
Name: "{%USERPROFILE}\Downloads\LouCodi\Documents vers PDF"
Name: "{%USERPROFILE}\Downloads\LouCodi\Organiser les PDF"
Name: "{%USERPROFILE}\Downloads\LouCodi\Habillage PDF"
Name: "{%USERPROFILE}\Downloads\LouCodi\Document Studio"
Name: "{%USERPROFILE}\Downloads\LouCodi\Optimisation de découpe"
Name: "{%USERPROFILE}\Downloads\LouCodi\Code Lab"
Name: "{%USERPROFILE}\Downloads\LouCodi\Lou Còdi Espace"

[Icons]
Name: "{group}\Lou Còdi Workshop"; Filename: "{app}\lou-codi-pdf-converter.exe"; WorkingDir: "{app}"; AppUserModelID: "LouCodi.Workshop"
Name: "{group}\Désinstaller Lou Còdi Workshop"; Filename: "{uninstallexe}"; IconFilename: "{uninstallexe}"
Name: "{autodesktop}\Lou Còdi Workshop"; Filename: "{app}\lou-codi-pdf-converter.exe"; WorkingDir: "{app}"; IconFilename: "{app}\lou-codi-workshop.ico"; AppUserModelID: "LouCodi.Workshop"

[Registry]
Root: HKA; Subkey: "Software\Classes\.code"; ValueType: string; ValueData: "LouCodi.Document"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.code\OpenWithProgids"; ValueType: string; ValueName: "LouCodi.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.cod"; ValueType: string; ValueData: "LouCodi.Document"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.cod\OpenWithProgids"; ValueType: string; ValueName: "LouCodi.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.loucodi-document"; ValueType: string; ValueData: "LouCodi.Document"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.loucodi-document\OpenWithProgids"; ValueType: string; ValueName: "LouCodi.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\LouCodi.Document"; ValueType: string; ValueData: "Document Lou Còdi"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\LouCodi.Document"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "Document Lou Còdi"
Root: HKA; Subkey: "Software\Classes\LouCodi.Document\DefaultIcon"; ValueType: string; ValueData: """{app}\lou-codi-document.ico"",0"
Root: HKA; Subkey: "Software\Classes\LouCodi.Document\shell\open"; ValueType: string; ValueData: "Ouvrir avec Lou Còdi Workshop"
Root: HKA; Subkey: "Software\Classes\LouCodi.Document\shell\open\command"; ValueType: string; ValueData: """{app}\lou-codi-pdf-converter.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\lou-codi-pdf-converter.exe\SupportedTypes"; ValueType: string; ValueName: ".code"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\lou-codi-pdf-converter.exe\SupportedTypes"; ValueType: string; ValueName: ".cod"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\lou-codi-pdf-converter.exe\SupportedTypes"; ValueType: string; ValueName: ".loucodi-document"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.loucodi-espace"; ValueType: string; ValueData: "LouCodi.Space"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\LouCodi.Space"; ValueType: string; ValueData: "Espace Lou Còdi"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\LouCodi.Space\DefaultIcon"; ValueType: string; ValueData: """{app}\lou-codi-document.ico"",0"
Root: HKA; Subkey: "Software\Classes\LouCodi.Space\shell\open\command"; ValueType: string; ValueData: """{app}\lou-codi-pdf-converter.exe"" ""%1"""

[Run]
Filename: "{sys}\ie4uinit.exe"; Parameters: "-ClearIconCache"; Flags: runhidden; StatusMsg: "Nettoyage du cache d’icônes Windows..."
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden; StatusMsg: "Actualisation des icônes de fichiers..."
Filename: "{app}\lou-codi-pdf-converter.exe"; Description: "Lancer Lou Còdi Workshop"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\LouCodi\Workshop"
Type: files; Name: "{userprograms}\Lou Còdi Workshop.lnk"
Type: files; Name: "{userdesktop}\Lou Còdi Workshop.lnk"

[Code]
var
  DependencyPage: TOutputMsgMemoWizardPage;

function LibreOfficePresent: Boolean;
begin
  Result := FileExists(ExpandConstant('{pf}\LibreOffice\program\soffice.exe')) or
            FileExists(ExpandConstant('{pf32}\LibreOffice\program\soffice.exe'));
end;

function LibreOfficeVersion: String;
var
  Version: String;
  ProgramPath: String;
begin
  ProgramPath := ExpandConstant('{pf}\LibreOffice\program\soffice.exe');
  if not FileExists(ProgramPath) then
    ProgramPath := ExpandConstant('{pf32}\LibreOffice\program\soffice.exe');
  if FileExists(ProgramPath) and GetVersionNumbersString(ProgramPath, Version) then
    Result := Version
  else
    Result := 'version inconnue';
end;

procedure InitializeWizard;
var
  Notice: String;
begin
  DependencyPage := CreateOutputMsgMemoPage(wpWelcome,
    'Vérification des composants',
    'Composants intégrés et logiciels facultatifs',
    'État des dépendances',
    'Python et les bibliothèques PDF sont intégrés au paquet. LibreOffice reste indépendant et facultatif.');
  Notice := 'Les traitements documentaires sont réalisés localement.' + #13#10 + #13#10;
  if LibreOfficePresent then
    Notice := Notice + 'LibreOffice détecté (' + LibreOfficeVersion + '). Les conversions Office fidèles seront disponibles.'
  else
    Notice := Notice + 'LibreOffice n''a pas été détecté. Lou Còdi utilisera son moteur local allégé pour les documents simples. Les anciens formats, PowerPoint et les mises en page complexes nécessitent LibreOffice, qui reste facultatif et indépendant.';
  DependencyPage.RichEditViewer.Lines.Text := Notice + #13#10 + #13#10 +
    'L''installateur met automatiquement à niveau une installation Lou Còdi existante et conserve les documents personnels.';
end;

procedure SHChangeNotify(wEventId: LongWord; uFlags: LongWord; dwItem1, dwItem2: Integer);
  external 'SHChangeNotify@shell32.dll stdcall';

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SHChangeNotify($08000000, 0, 0, 0);
end;

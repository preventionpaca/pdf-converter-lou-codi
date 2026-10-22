$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

$Source = Join-Path $PSScriptRoot "app"
$Target = Join-Path $env:LOCALAPPDATA "LouCodi\Workshop"

if (-not (Test-Path (Join-Path $Source "lou-codi-pdf-converter.exe"))) {
  [System.Windows.Forms.MessageBox]::Show(
    "Paquet incomplet : l'exécutable Lou Còdi Workshop est absent.",
    "Installation impossible", "OK", "Error"
  ) | Out-Null
  exit 1
}

$officeCandidates = @((Join-Path $env:ProgramFiles "LibreOffice\program\soffice.exe"))
if (${env:ProgramFiles(x86)}) {
  $officeCandidates += Join-Path ${env:ProgramFiles(x86)} "LibreOffice\program\soffice.exe"
}
$officeFound = $officeCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$officeStatus = if ($officeFound) {
  "LibreOffice détecté : conversion fidèle de Word, Excel, PowerPoint et OpenDocument."
} else {
  "LibreOffice non détecté : DOCX et XLSX simples utiliseront le moteur allégé. PowerPoint, OpenDocument, anciens formats et mises en page complexes nécessitent une installation séparée de LibreOffice."
}

$intro = @"
Lou Còdi Workshop traite les documents localement.

Le cœur de l'application, les bibliothèques PDF et le moteur Office allégé sont toujours installés.

$officeStatus

LibreOffice est indépendant : Lou Còdi ne l'installe pas et ne revendique aucun lien avec ce logiciel.

Oui : installation complète (recommandée)
Non : installation personnalisée
Annuler : quitter sans installer
"@
$mode = [System.Windows.Forms.MessageBox]::Show(
  $intro, "Installation de Lou Còdi Workshop", "YesNoCancel", "Information"
)
if ($mode -eq "Cancel") { exit 0 }

$installShortcut = $true
$createWorkspace = $true
$selectedModules = @("pdf_studio", "document_studio", "cutting_optimization", "code_lab")
if ($mode -eq "No") {
  $installShortcut = [System.Windows.Forms.MessageBox]::Show(
    "Créer un raccourci dans le menu Démarrer ?", "Option — Raccourci", "YesNo", "Question"
  ) -eq "Yes"
  $createWorkspace = [System.Windows.Forms.MessageBox]::Show(
    "Créer les dossiers LouCodi dans Téléchargements ?", "Option — Dossiers de travail", "YesNo", "Question"
  ) -eq "Yes"
  $selectedModules = @()
  @(
    @{ Id = "pdf_studio"; Label = "PDF Studio" },
    @{ Id = "document_studio"; Label = "Document Studio" },
    @{ Id = "cutting_optimization"; Label = "Optimisation de découpe" },
    @{ Id = "code_lab"; Label = "Lou Còdi Code Lab" }
  ) | ForEach-Object {
    $enabled = [System.Windows.Forms.MessageBox]::Show(
      "Installer $($_.Label) ?", "Choix des modules", "YesNo", "Question"
    ) -eq "Yes"
    if ($enabled) { $selectedModules += $_.Id }
  }
}

if (Test-Path $Target) { Remove-Item $Target -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item (Join-Path $Source "*") $Target -Recurse -Force
$moduleDirectory = Join-Path $Target "selected-modules"
New-Item -ItemType Directory -Force -Path $moduleDirectory | Out-Null
Get-ChildItem $moduleDirectory -Filter "*.enabled" -ErrorAction SilentlyContinue | Remove-Item -Force
$selectedModules | ForEach-Object {
  New-Item -ItemType File -Force -Path (Join-Path $moduleDirectory "$_.enabled") | Out-Null
}

$classes = "HKCU:\Software\Classes"
New-Item -Force -Path "$classes\.cod" -Value "LouCodi.Document" | Out-Null
New-Item -Force -Path "$classes\.loucodi-document" -Value "LouCodi.Document" | Out-Null
New-Item -Force -Path "$classes\LouCodi.Document" -Value "Document Lou Còdi" | Out-Null
New-Item -ItemType Directory -Force -Path "$classes\LouCodi.Document\DefaultIcon" | Out-Null
$installedDocumentIcon = Join-Path $Target "_internal\lou_codi_pdf_converter\assets\lou-codi-document.ico"
Set-Item "$classes\LouCodi.Document\DefaultIcon" -Value "$installedDocumentIcon,0"
New-Item -ItemType Directory -Force -Path "$classes\LouCodi.Document\shell\open\command" | Out-Null
$openCommand = ('"{0}" "%1"' -f (Join-Path $Target "lou-codi-pdf-converter.exe"))
Set-Item "$classes\LouCodi.Document\shell\open\command" -Value $openCommand

if ($createWorkspace) {
  try {
    $Downloads = (New-Object -ComObject Shell.Application).NameSpace("shell:Downloads").Self.Path
  } catch {
    $Downloads = Join-Path $HOME "Downloads"
  }
  $Workspace = Join-Path $Downloads "LouCodi"
  @(
    @{ Module = "pdf_studio"; Folders = @("PDF vers Office", "Documents vers PDF", "Organiser les PDF", "Habillage PDF") },
    @{ Module = "document_studio"; Folders = @("Document Studio") },
    @{ Module = "cutting_optimization"; Folders = @("Optimisation de découpe") },
    @{ Module = "code_lab"; Folders = @("Code Lab") }
  ) | Where-Object { $selectedModules -contains $_.Module } | ForEach-Object {
    $_.Folders | ForEach-Object {
      New-Item -ItemType Directory -Force -Path (Join-Path $Workspace $_) | Out-Null
    }
  }
}

$shortcutPath = Join-Path ([Environment]::GetFolderPath("Programs")) "Lou Còdi Workshop.lnk"
if ($installShortcut) {
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = Join-Path $Target "lou-codi-pdf-converter.exe"
  $shortcut.WorkingDirectory = $Target
  $shortcut.IconLocation = Join-Path $Target "lou-codi-pdf-converter.exe"
  $shortcut.Save()
} elseif (Test-Path $shortcutPath) {
  Remove-Item $shortcutPath -Force
}

$shortcutStatus = if ($installShortcut) {
  "Raccourci : créé dans le menu Démarrer."
} else {
  "Raccourci : non créé. Exécutable : $Target\lou-codi-pdf-converter.exe"
}
[System.Windows.Forms.MessageBox]::Show(
  "Installation terminée.`n`n$shortcutStatus`n`n$officeStatus",
  "Lou Còdi Workshop", "OK", "Information"
) | Out-Null

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

$Source = Join-Path $PSScriptRoot "app"
$SpeechSource = Join-Path $PSScriptRoot "options\speech-models"
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

$installSpeech = $true
$installShortcut = $true
$createWorkspace = $true
if ($mode -eq "No") {
  if (Test-Path $SpeechSource) {
    $installSpeech = [System.Windows.Forms.MessageBox]::Show(
      "Installer la dictée locale hors ligne ?`n`nEnviron 70 Mo supplémentaires. Aucun enregistrement n'est envoyé sur Internet. L'accès au microphone restera soumis aux autorisations de Windows.",
      "Composant facultatif — Dictée locale", "YesNo", "Question"
    ) -eq "Yes"
  } else {
    $installSpeech = $false
  }
  $installShortcut = [System.Windows.Forms.MessageBox]::Show(
    "Créer un raccourci dans le menu Démarrer ?", "Option — Raccourci", "YesNo", "Question"
  ) -eq "Yes"
  $createWorkspace = [System.Windows.Forms.MessageBox]::Show(
    "Créer les dossiers LouCodi dans Téléchargements ?", "Option — Dossiers de travail", "YesNo", "Question"
  ) -eq "Yes"
}

if (Test-Path $Target) { Remove-Item $Target -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item (Join-Path $Source "*") $Target -Recurse -Force

if ($installSpeech -and (Test-Path $SpeechSource)) {
  $speechTarget = Join-Path $Target "_internal\speech-models"
  New-Item -ItemType Directory -Force -Path $speechTarget | Out-Null
  Copy-Item (Join-Path $SpeechSource "*") $speechTarget -Recurse -Force
} elseif ($installSpeech) {
  [System.Windows.Forms.MessageBox]::Show(
    "Le pack de dictée n'est pas présent dans cette archive. L'application fonctionnera normalement sans dictée.",
    "Avertissement — Dictée locale", "OK", "Warning"
  ) | Out-Null
}

if ($createWorkspace) {
  try {
    $Downloads = (New-Object -ComObject Shell.Application).NameSpace("shell:Downloads").Self.Path
  } catch {
    $Downloads = Join-Path $HOME "Downloads"
  }
  $Workspace = Join-Path $Downloads "LouCodi"
  @(
    "PDF vers Office", "Documents vers PDF", "Organiser les PDF",
    "Habillage PDF", "Document Studio", "Optimisation de découpe"
  ) | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $Workspace $_) | Out-Null
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

$speechStatus = if ($installSpeech -and (Test-Path $SpeechSource)) {
  "Dictée locale : installée."
} else {
  "Dictée locale : non installée ; le bouton indiquera que le pack est absent."
}
$shortcutStatus = if ($installShortcut) {
  "Raccourci : créé dans le menu Démarrer."
} else {
  "Raccourci : non créé. Exécutable : $Target\lou-codi-pdf-converter.exe"
}
[System.Windows.Forms.MessageBox]::Show(
  "Installation terminée.`n`n$speechStatus`n$shortcutStatus`n`n$officeStatus",
  "Lou Còdi Workshop", "OK", "Information"
) | Out-Null

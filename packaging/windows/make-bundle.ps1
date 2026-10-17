$ErrorActionPreference = "Stop"
$Project = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Version = & python -c "import sys; sys.path.insert(0, r'$Project\src'); from lou_codi_pdf_converter import __version__; print(__version__)"
$Bundle = Join-Path $Project "dist\Lou-Codi-Workshop-$Version-windows-x86_64"
$Installers = Join-Path $Project "dist\installers"
if (Test-Path $Bundle) { Remove-Item $Bundle -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $Bundle "app"), $Installers | Out-Null
Copy-Item (Join-Path $Project "dist\lou-codi-pdf-converter\*") (Join-Path $Bundle "app") -Recurse -Force
$SpeechModels = Join-Path $Bundle "app\_internal\speech-models"
if (Test-Path $SpeechModels) {
  New-Item -ItemType Directory -Force -Path (Join-Path $Bundle "options") | Out-Null
  Move-Item $SpeechModels (Join-Path $Bundle "options\speech-models") -Force
}
Copy-Item (Join-Path $Project "packaging\windows\install.ps1") (Join-Path $Bundle "installer.ps1")
Compress-Archive -Path $Bundle -DestinationPath (Join-Path $Installers "Lou-Codi-Workshop-$Version-windows-x86_64.zip") -Force

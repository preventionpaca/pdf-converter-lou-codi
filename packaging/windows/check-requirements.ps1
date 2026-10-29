$ErrorActionPreference = "SilentlyContinue"

function Get-LibreOffice {
  $candidates = @()
  if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles "LibreOffice\program\soffice.exe" }
  if (${env:ProgramFiles(x86)}) { $candidates += Join-Path ${env:ProgramFiles(x86)} "LibreOffice\program\soffice.exe" }
  $registryPaths = @(
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
  )
  $entry = Get-ItemProperty $registryPaths | Where-Object { $_.DisplayName -like "LibreOffice*" } | Select-Object -First 1
  $binary = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  [PSCustomObject]@{ Found = [bool]($entry -or $binary); Version = $entry.DisplayVersion; Binary = $binary }
}

$office = Get-LibreOffice
$officeStatus = if ($office.Found) {
  $version = if ($office.Version) { $office.Version } else { "version inconnue" }
  $update = "état de mise à jour non disponible"
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    $upgrades = winget upgrade --id TheDocumentFoundation.LibreOffice --exact --accept-source-agreements 2>$null | Out-String
    if ($LASTEXITCODE -eq 0 -and $upgrades -match "LibreOffice") { $update = "mise à jour proposée par winget" }
    else { $update = "aucune mise à jour signalée par winget" }
  }
  "$version — $update"
} else { "non installé (facultatif)" }

$installed = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LouCodiWorkshop" -ErrorAction SilentlyContinue
[PSCustomObject]@{
  Windows = [Environment]::OSVersion.VersionString
  Architecture = $env:PROCESSOR_ARCHITECTURE
  LibreOffice = $officeStatus
  LouCodi = if ($installed.DisplayVersion) { $installed.DisplayVersion } else { "non installé" }
} | Format-List

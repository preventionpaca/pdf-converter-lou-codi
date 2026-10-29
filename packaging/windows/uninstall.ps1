$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

$Target = Join-Path $env:LOCALAPPDATA "LouCodi\Workshop"
$answer = [System.Windows.Forms.MessageBox]::Show(
  "Désinstaller Lou Còdi Workshop ?`n`nLes documents, espaces et réglages personnels seront conservés.",
  "Désinstallation de Lou Còdi Workshop", "YesNo", "Question"
)
if ($answer -ne "Yes") { exit 0 }

Get-Process "lou-codi-pdf-converter" -ErrorAction SilentlyContinue | Stop-Process -Force
$programs = [Environment]::GetFolderPath("Programs")
$desktop = [Environment]::GetFolderPath("Desktop")
Remove-Item (Join-Path $programs "Lou Còdi Workshop.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $desktop "Lou Còdi Workshop.lnk") -Force -ErrorAction SilentlyContinue
@(".code", ".cod", ".loucodi-document", ".loucodi-espace", "LouCodi.Document", "LouCodi.Space") | ForEach-Object {
  Remove-Item "HKCU:\Software\Classes\$_" -Recurse -Force -ErrorAction SilentlyContinue
}
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LouCodiWorkshop" -Recurse -Force -ErrorAction SilentlyContinue

$cleanup = Join-Path $env:TEMP "lou-codi-remove-$PID.cmd"
@"
@echo off
timeout /t 2 /nobreak >nul
rmdir /s /q "$Target"
del "%~f0"
"@ | Set-Content $cleanup -Encoding Ascii
Start-Process $cleanup -WindowStyle Hidden
[System.Windows.Forms.MessageBox]::Show(
  "Lou Còdi Workshop a été désinstallé. Vos documents personnels ont été conservés.",
  "Lou Còdi Workshop", "OK", "Information"
) | Out-Null

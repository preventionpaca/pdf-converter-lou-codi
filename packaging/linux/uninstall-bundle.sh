#!/usr/bin/env bash
set -eu

data_root="${XDG_DATA_HOME:-$HOME/.local/share}"
config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
application_target="$data_root/lou-codi-workshop"
purge=0
[ "${1:-}" = "--purge-user-data" ] && purge=1

if [ ! -d "$application_target" ]; then
  echo "Lou Còdi Workshop n’est pas installé dans $application_target."
  exit 0
fi

if [ -t 0 ]; then
  echo "DÉSINSTALLATION DE LOU CÒDI WORKSHOP"
  echo "Les documents et espaces personnels seront conservés."
  printf "Continuer ? [o/N] "
  read -r answer
  case "$answer" in o|O|oui|OUI|y|Y|yes|YES) ;; *) echo "Désinstallation annulée."; exit 0 ;; esac
fi

pkill -f "$application_target/app/lou-codi-pdf-converter" >/dev/null 2>&1 || true
rm -rf -- "$application_target"
rm -f -- "$data_root/applications/lou-codi-workshop.desktop"
rm -f -- "$data_root/icons/hicolor/256x256/apps/lou-codi-workshop.png"
for size in 16 24 32 48 64 128 256; do
  rm -f -- "$data_root/icons/hicolor/${size}x${size}/mimetypes/application-x-loucodi-document.png"
done
rm -f -- "$data_root/icons/hicolor/scalable/mimetypes/application-x-loucodi-document.svg"
rm -f -- "$data_root/mime/packages/lou-codi-document.xml"
if [ "$purge" -eq 1 ]; then
  rm -rf -- "$config_root/lou-codi-pdf-converter" "$config_root/lou-codi-workshop"
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$data_root/applications" >/dev/null 2>&1 || true
command -v update-mime-database >/dev/null 2>&1 && update-mime-database "$data_root/mime" >/dev/null 2>&1 || true
echo "Lou Còdi Workshop a été désinstallé. Les documents personnels ont été conservés."

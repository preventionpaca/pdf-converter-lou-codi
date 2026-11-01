#!/usr/bin/env bash
set -eu

data_root="${XDG_DATA_HOME:-$HOME/.local/share}"
config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
application_target="$data_root/lou-codi-workshop"
purge=0
assume_yes=0
for argument in "$@"; do
  [ "$argument" = "--purge-user-data" ] && purge=1
  [ "$argument" = "--yes" ] && assume_yes=1
done

if [ ! -d "$application_target" ]; then
  echo "Lou Còdi Workshop n’est pas installé dans $application_target."
  exit 0
fi

gui=0
if [ "$assume_yes" -eq 0 ] && command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  gui=1
  zenity --question --title="Désinstaller Lou Còdi Workshop" \
    --text="Désinstaller Lou Còdi Workshop ?\n\nVos documents, projets .cod, espaces et réglages personnels seront conservés." \
    --width=560 2>/dev/null || { echo "Désinstallation annulée."; exit 0; }
elif [ "$assume_yes" -eq 0 ] && [ -t 0 ]; then
  echo "DÉSINSTALLATION DE LOU CÒDI WORKSHOP"
  echo "Les documents et espaces personnels seront conservés."
  printf "Continuer ? [o/N] "
  read -r answer
  case "$answer" in o|O|oui|OUI|y|Y|yes|YES) ;; *) echo "Désinstallation annulée."; exit 0 ;; esac
fi

pkill -f "$application_target/app/lou-codi-pdf-converter" >/dev/null 2>&1 || true
rm -rf -- "$application_target"
rm -f -- "$data_root/applications/lou-codi-workshop.desktop"
rm -f -- "$data_root/applications/lou-codi-workshop-uninstall.desktop"
rm -f -- "$data_root/applications/lou-codi-pdf-converter.desktop"
rm -f -- "$data_root/icons/hicolor/256x256/apps/lou-codi-workshop.png"
for size in 16 24 32 48 64 128 256; do
  rm -f -- "$data_root/icons/hicolor/${size}x${size}/mimetypes/application-x-loucodi-document.png"
done
rm -f -- "$data_root/icons/hicolor/scalable/mimetypes/application-x-loucodi-document.svg"
rm -f -- "$data_root/icons/application-x-loucodi-document.png"
rm -f -- "$data_root/icons/application-x-loucodi-document.svg"
rm -f -- "$data_root/icons/application-x-loucodi-document-symbolic.svg"
rm -f -- "$data_root/mime/packages/lou-codi-document.xml"
rm -f -- "$data_root/thumbnailers/lou-codi-document.thumbnailer"
desktop_dir=""
command -v xdg-user-dir >/dev/null 2>&1 && desktop_dir=$(xdg-user-dir DESKTOP 2>/dev/null || true)
[ -n "$desktop_dir" ] && rm -f -- "$desktop_dir/Lou Còdi Workshop.desktop"
if [ "$purge" -eq 1 ]; then
  rm -rf -- "$config_root/lou-codi-pdf-converter" "$config_root/lou-codi-workshop"
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$data_root/applications" >/dev/null 2>&1 || true
command -v update-mime-database >/dev/null 2>&1 && update-mime-database "$data_root/mime" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$data_root/icons/hicolor" >/dev/null 2>&1 || true
echo "Lou Còdi Workshop a été désinstallé. Les documents personnels ont été conservés."
if [ "$gui" -eq 1 ]; then
  zenity --info --title="Lou Còdi Workshop" \
    --text="Lou Còdi Workshop a été désinstallé.\n\nVos documents et réglages personnels ont été conservés." \
    --width=520 2>/dev/null || true
fi

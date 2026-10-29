#!/usr/bin/env bash
set -eu

machine=0
[ "${1:-}" = "--machine" ] && machine=1

value() { command -v "$1" 2>/dev/null || true; }
line() {
  if [ "$machine" -eq 1 ]; then printf '%s=%s\n' "$1" "$2"; else printf '%-24s %s\n' "$1" "$2"; fi
}

arch=$(uname -m)
glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}' || true)
[ -n "$glibc" ] || glibc="inconnue"
line "Architecture" "$arch"
line "glibc" "$glibc"

office=$(value libreoffice)
[ -n "$office" ] || office=$(value soffice)
if [ -n "$office" ]; then
  office_version=$($office --version 2>/dev/null | head -n 1 || true)
  [ -n "$office_version" ] || office_version="version inconnue"
  office_update="état de mise à jour non disponible"
  if command -v dpkg-query >/dev/null 2>&1 && command -v apt-cache >/dev/null 2>&1; then
    installed=$(dpkg-query -W -f='${Version}' libreoffice-core 2>/dev/null || true)
    candidate=$(apt-cache policy libreoffice-core 2>/dev/null | awk '/Candidate:/ {print $2; exit}')
    if [ -n "$installed" ] && [ -n "$candidate" ] && [ "$candidate" != "(none)" ]; then
      if dpkg --compare-versions "$installed" lt "$candidate"; then
        office_update="mise à jour proposée : $candidate"
      else
        office_update="à jour selon les dépôts configurés"
      fi
    fi
  elif command -v flatpak >/dev/null 2>&1 && flatpak info org.libreoffice.LibreOffice >/dev/null 2>&1; then
    if flatpak remote-ls --updates 2>/dev/null | grep -q '^org\.libreoffice\.LibreOffice'; then
      office_update="mise à jour Flatpak proposée"
    else
      office_update="à jour selon Flathub"
    fi
  fi
  line "LibreOffice" "$office_version — $office_update"
else
  line "LibreOffice" "non installé (facultatif)"
fi

if command -v xdg-open >/dev/null 2>&1; then
  line "Ouverture navigateur" "disponible"
else
  line "Ouverture navigateur" "xdg-utils absent (facultatif)"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  line "Intégration bureau" "disponible"
else
  line "Intégration bureau" "outils desktop-file-utils absents (facultatif)"
fi

installed_version_file="${XDG_DATA_HOME:-$HOME/.local/share}/lou-codi-workshop/app/VERSION"
if [ -f "$installed_version_file" ]; then
  line "Lou Còdi installé" "$(head -n 1 "$installed_version_file")"
else
  line "Lou Còdi installé" "aucune installation autonome détectée"
fi

#!/usr/bin/env bash
set -eu

bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
application_source="$bundle_dir/app"
data_root="${XDG_DATA_HOME:-$HOME/.local/share}"
application_target="$data_root/lou-codi-workshop/app"
applications_dir="$data_root/applications"
icons_dir="$data_root/icons/hicolor/256x256/apps"
speech_source="$bundle_dir/options/speech-models"
install_speech=0
install_launcher=1
create_workspace=1

if [ ! -x "$application_source/lou-codi-pdf-converter" ]; then
  echo "Paquet incomplet : l’exécutable Lou Còdi Workshop est absent." >&2
  exit 1
fi

echo
echo "INSTALLATION DE LOU CÒDI WORKSHOP"
echo "----------------------------------"
echo "Le cœur de l’application, ses bibliothèques PDF et le moteur Office allégé"
echo "sont toujours installés. Aucun document n’est envoyé sur Internet."
echo
echo "Lou Còdi Workshop fonctionne sans LibreOffice."
echo "- Sans LibreOffice : conversion allégée des DOCX et XLSX simples."
echo "- Avec LibreOffice : conversion fidèle et prise en charge de PowerPoint,"
echo "  OpenDocument et des anciens formats Office."
echo "LibreOffice est un logiciel indépendant et n’est pas fourni par Lou Còdi."
if command -v libreoffice >/dev/null 2>&1 || command -v soffice >/dev/null 2>&1; then
  echo "État : LibreOffice détecté, conversion fidèle disponible."
else
  echo "État : LibreOffice non détecté, le moteur allégé sera utilisé."
fi
echo
if [ -t 0 ]; then
  echo "1 - Installation complète (recommandée)"
  echo "    Application + dictée locale + raccourci + dossiers de travail."
  echo "2 - Installation personnalisée"
  echo "    Choisir la dictée, le raccourci et les dossiers de travail."
  echo "3 - Annuler"
  printf "Votre choix [1] : "
  read -r mode
  case "${mode:-1}" in
    1) install_speech=1 ;;
    2)
      if [ -d "$speech_source" ]; then
        printf "Installer la dictée locale hors ligne (environ 70 Mo) ? [O/n] "
        read -r answer
        case "$answer" in n|N|non|NON) install_speech=0 ;; *) install_speech=1 ;; esac
      fi
      printf "Créer le raccourci dans le menu des applications ? [O/n] "
      read -r answer
      case "$answer" in n|N|non|NON) install_launcher=0 ;; esac
      printf "Créer les dossiers LouCodi dans Téléchargements ? [O/n] "
      read -r answer
      case "$answer" in n|N|non|NON) create_workspace=0 ;; esac
      ;;
    3) echo "Installation annulée."; exit 0 ;;
    *) echo "Choix incorrect : installation annulée."; exit 1 ;;
  esac
else
  install_speech=1
fi

install -d "$application_target" "$applications_dir" "$icons_dir"
cp -a "$application_source/." "$application_target/"
if [ "$install_speech" -eq 1 ] && [ -d "$speech_source" ]; then
  install -d "$application_target/_internal/speech-models"
  cp -a "$speech_source/." "$application_target/_internal/speech-models/"
elif [ "$install_speech" -eq 1 ]; then
  echo "Avertissement : le pack de dictée n’est pas présent dans cette archive."
fi

if [ "$create_workspace" -eq 1 ]; then
  downloads_dir="${XDG_DOWNLOAD_DIR:-$HOME/Téléchargements}"
  if command -v xdg-user-dir >/dev/null 2>&1; then
    detected_downloads=$(xdg-user-dir DOWNLOAD 2>/dev/null || true)
    [ -n "$detected_downloads" ] && downloads_dir="$detected_downloads"
  fi
  for module in "PDF vers Office" "Documents vers PDF" "Organiser les PDF" \
    "Habillage PDF" "Document Studio" "Optimisation de découpe"; do
    install -d "$downloads_dir/LouCodi/$module"
  done
fi

if [ "$install_launcher" -eq 1 ]; then
  install -m 0644 "$bundle_dir/lou-codi-workshop.png" "$icons_dir/lou-codi-workshop.png"

# Migrate installations made under the former PDF Converter desktop identity.
# Keeping both launchers makes Linux associate the running window with a generic
# gear icon instead of the pinned Lou Còdi Workshop icon.
if [ -f "$applications_dir/lou-codi-pdf-converter.desktop" ]; then
  unlink "$applications_dir/lou-codi-pdf-converter.desktop"
fi

desktop_file="$applications_dir/lou-codi-workshop.desktop"
{
  echo '[Desktop Entry]'
  echo 'Name=Lou Còdi Workshop'
  echo 'Comment=Des outils pratiques, en local, pour créer et fabriquer'
  printf 'Exec=%s/lou-codi-pdf-converter\n' "$application_target"
  echo 'Icon=lou-codi-workshop'
  echo 'Terminal=false'
  echo 'Type=Application'
  echo 'Categories=Office;Graphics;Utility;'
  echo 'Keywords=PDF;DOCX;dessin;découpe;atelier;conversion;'
  echo 'StartupWMClass=Loucodiworkshop'
} > "$desktop_file"
chmod 0644 "$desktop_file"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$applications_dir"
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$data_root/icons/hicolor" >/dev/null 2>&1 || true
fi
fi

echo
echo "Installation terminée."
if [ "$install_speech" -eq 1 ] && [ -d "$speech_source" ]; then
  echo "- Dictée locale : installée (le microphone reste soumis aux autorisations du système)."
else
  echo "- Dictée locale : non installée. Le bouton indiquera que le pack est absent."
fi
if [ "$install_launcher" -eq 1 ]; then
  echo "- Raccourci : disponible dans le menu des applications."
else
  echo "- Raccourci : non créé. Exécutable : $application_target/lou-codi-pdf-converter"
fi

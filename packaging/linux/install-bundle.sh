#!/usr/bin/env bash
set -eu

bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
application_source="$bundle_dir/app"
data_root="${XDG_DATA_HOME:-$HOME/.local/share}"
application_target="$data_root/lou-codi-workshop/app"
applications_dir="$data_root/applications"
icons_dir="$data_root/icons/hicolor/256x256/apps"
mime_icons_dir="$data_root/icons/hicolor/256x256/mimetypes"
mime_packages_dir="$data_root/mime/packages"
install_launcher=1
create_workspace=1
selected_modules="pdf_studio document_studio cutting_optimization code_lab codi_space"
bundle_version=$(head -n 1 "$bundle_dir/VERSION" 2>/dev/null || printf 'version inconnue')
installed_version=$(head -n 1 "$application_target/VERSION" 2>/dev/null || true)

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
echo "Version du paquet : $bundle_version"
if [ -n "$installed_version" ]; then
  echo "Version déjà installée : $installed_version (elle sera mise à niveau en conservant les données)."
else
  echo "Aucune installation autonome précédente détectée."
fi
echo
"$bundle_dir/check-requirements.sh"
if command -v libreoffice >/dev/null 2>&1 || command -v soffice >/dev/null 2>&1; then
  echo "État : LibreOffice détecté, conversion fidèle disponible."
else
  echo "État : LibreOffice non détecté, le moteur allégé sera utilisé."
fi
echo
gui=0
if command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  gui=1
  mode=$(zenity --list --radiolist --title="Installation de Lou Còdi Workshop" \
    --text="Choisissez le type d’installation. La version $bundle_version sera installée." \
    --column="" --column="Type" --column="Contenu" \
    TRUE "Complète (recommandée)" "Application, tous les modules, raccourci et dossiers" \
    FALSE "Personnalisée" "Choisir les modules et les options" \
    --width=760 --height=360 2>/dev/null || true)
  [ -n "$mode" ] || { echo "Installation annulée."; exit 0; }
  if [ "$mode" = "Personnalisée" ]; then
    selected_modules=$(zenity --list --checklist --title="Modules Lou Còdi" \
      --text="Cochez les modules à installer." --separator=" " \
      --column="Installer" --column="Identifiant" --column="Module" \
      TRUE pdf_studio "PDF Studio" TRUE document_studio "Document Studio" \
      TRUE cutting_optimization "Optimisation de découpe" TRUE code_lab "Lou Còdi Code Lab" \
      TRUE codi_space "Lou Còdi Espace" --hide-column=2 --width=720 --height=430 2>/dev/null || true)
    options=$(zenity --list --checklist --title="Options d’installation" --separator=" " \
      --column="Activer" --column="Option" \
      TRUE shortcut TRUE workspace --hide-column=2 --width=620 --height=300 2>/dev/null || true)
    case " $options " in *" shortcut "*) ;; *) install_launcher=0 ;; esac
    case " $options " in *" workspace "*) ;; *) create_workspace=0 ;; esac
  fi
elif [ -t 0 ]; then
  echo "1 - Installation complète (recommandée)"
  echo "    Application + raccourci + dossiers de travail."
  echo "2 - Installation personnalisée"
  echo "    Choisir les modules, le raccourci et les dossiers de travail."
  echo "3 - Annuler"
  printf "Votre choix [1] : "
  read -r mode
  case "${mode:-1}" in
    1) ;;
    2)
      selected_modules=""
      for module_spec in "pdf_studio:PDF Studio" "document_studio:Document Studio" \
        "cutting_optimization:Optimisation de découpe" "code_lab:Lou Còdi Code Lab" \
        "codi_space:Lou Còdi Espace"; do
        module_id=${module_spec%%:*}
        module_name=${module_spec#*:}
        printf "Installer %s ? [O/n] " "$module_name"
        read -r answer
        case "$answer" in n|N|non|NON) ;; *) selected_modules="$selected_modules $module_id" ;; esac
      done
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
fi

install -d "$application_target" "$applications_dir" "$icons_dir" "$mime_icons_dir" "$mime_packages_dir"
cp -a "$application_source/." "$application_target/"
install -m 0644 "$bundle_dir/VERSION" "$application_target/VERSION"
install -m 0755 "$bundle_dir/uninstaller.sh" "$application_target/uninstall.sh"
install -m 0755 "$bundle_dir/check-requirements.sh" "$application_target/check-requirements.sh"
install -d "$application_target/selected-modules"
for module in pdf_studio document_studio cutting_optimization code_lab codi_space; do
  marker="$application_target/selected-modules/$module.enabled"
  if [ -f "$marker" ]; then
    unlink "$marker"
  fi
done
for module in $selected_modules; do
  install -m 0644 "$bundle_dir/enabled.marker" "$application_target/selected-modules/$module.enabled"
done
if [ "$create_workspace" -eq 1 ]; then
  downloads_dir="${XDG_DOWNLOAD_DIR:-$HOME/Téléchargements}"
  if command -v xdg-user-dir >/dev/null 2>&1; then
    detected_downloads=$(xdg-user-dir DOWNLOAD 2>/dev/null || true)
    [ -n "$detected_downloads" ] && downloads_dir="$detected_downloads"
  fi
  case " $selected_modules " in *" pdf_studio "*) for module in "PDF vers Office" "Documents vers PDF" "Organiser les PDF" "Habillage PDF"; do install -d "$downloads_dir/LouCodi/$module"; done ;; esac
  case " $selected_modules " in *" document_studio "*) install -d "$downloads_dir/LouCodi/Document Studio" ;; esac
  case " $selected_modules " in *" cutting_optimization "*) install -d "$downloads_dir/LouCodi/Optimisation de découpe" ;; esac
  case " $selected_modules " in *" code_lab "*) install -d "$downloads_dir/LouCodi/Code Lab" ;; esac
  case " $selected_modules " in *" codi_space "*) install -d "$downloads_dir/LouCodi/Lou Còdi Espace" ;; esac
fi

if [ "$install_launcher" -eq 1 ]; then
  install -m 0644 "$bundle_dir/lou-codi-workshop.png" "$icons_dir/lou-codi-workshop.png"
  for size in 16 24 32 48 64 128 256; do
    destination="$data_root/icons/hicolor/${size}x${size}/mimetypes"
    install -d "$destination"
    install -m 0644 "$bundle_dir/lou-codi-document-$size.png" \
      "$destination/application-x-loucodi-document.png"
  done
  install -d "$data_root/icons/hicolor/scalable/mimetypes"
  install -m 0644 "$bundle_dir/lou-codi-document.svg" \
    "$data_root/icons/hicolor/scalable/mimetypes/application-x-loucodi-document.svg"

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
  printf 'Exec=%s/lou-codi-pdf-converter %%f\n' "$application_target"
  echo 'Icon=lou-codi-workshop'
  echo 'Terminal=false'
  echo 'Type=Application'
  echo 'Categories=Office;Graphics;Utility;'
  echo 'Keywords=PDF;DOCX;dessin;découpe;atelier;conversion;'
  echo 'MimeType=application/x-loucodi-document;application/x-loucodi-space;'
  echo 'StartupWMClass=Loucodiworkshop'
} > "$desktop_file"
chmod 0644 "$desktop_file"

cat > "$mime_packages_dir/lou-codi-document.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-loucodi-document">
    <comment>Document Lou Còdi</comment>
    <icon name="application-x-loucodi-document"/>
    <glob pattern="*.code"/>
    <glob pattern="*.cod"/>
    <glob pattern="*.loucodi-document"/>
  </mime-type>
  <mime-type type="application/x-loucodi-space">
    <comment>Espace Lou Còdi</comment>
    <glob pattern="*.loucodi-espace"/>
  </mime-type>
</mime-info>
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$applications_dir"
fi
if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database "$data_root/mime"
fi
if command -v xdg-mime >/dev/null 2>&1; then
  xdg-mime default lou-codi-workshop.desktop application/x-loucodi-document || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$data_root/icons/hicolor" >/dev/null 2>&1 || true
fi
fi

echo
echo "Installation terminée."
echo "- Désinstallation : $application_target/uninstall.sh"
if [ "$install_launcher" -eq 1 ]; then
  echo "- Raccourci : disponible dans le menu des applications."
else
  echo "- Raccourci : non créé. Exécutable : $application_target/lou-codi-pdf-converter"
fi
if [ "$gui" -eq 1 ]; then
  zenity --info --title="Lou Còdi Workshop" \
    --text="Installation terminée.\n\nVersion : $bundle_version\nDésinstallation : $application_target/uninstall.sh" \
    --width=560 2>/dev/null || true
fi

#!/usr/bin/env bash
set -eu

bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
application_source="$bundle_dir/app"
data_root="${XDG_DATA_HOME:-$HOME/.local/share}"
application_target="$data_root/lou-codi-workshop/app"
legacy_user_target="$data_root/lou-codi-pdf-converter"
applications_dir="$data_root/applications"
icons_dir="$data_root/icons/hicolor/256x256/apps"
mime_icons_dir="$data_root/icons/hicolor/256x256/mimetypes"
mime_packages_dir="$data_root/mime/packages"
thumbnailers_dir="$data_root/thumbnailers"
install_launcher=1
create_workspace=1
remove_legacy_user_install=1
selected_modules="pdf_studio document_studio cutting_optimization code_lab codi_space"
bundle_version=$(head -n 1 "$bundle_dir/VERSION" 2>/dev/null || printf 'version inconnue')
installed_version=$(head -n 1 "$application_target/VERSION" 2>/dev/null || true)
legacy_brand="lou""camin"
legacy_system_install=""
[ -d "/opt/$legacy_brand-pdf-converter" ] && legacy_system_install="/opt/$legacy_brand-pdf-converter"

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
if [ -d "$legacy_user_target" ]; then
  echo "Ancienne installation utilisateur détectée : $legacy_user_target"
fi
if [ -n "$legacy_system_install" ]; then
  echo "Ancienne installation système détectée : $legacy_system_install"
  echo "Elle sera signalée à la fin, car sa suppression nécessite les droits administrateur."
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
      TRUE shortcut TRUE workspace TRUE cleanup --hide-column=2 --width=620 --height=340 2>/dev/null || true)
    case " $options " in *" shortcut "*) ;; *) install_launcher=0 ;; esac
    case " $options " in *" workspace "*) ;; *) create_workspace=0 ;; esac
    case " $options " in *" cleanup "*) ;; *) remove_legacy_user_install=0 ;; esac
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
      if [ -d "$legacy_user_target" ]; then
        printf "Retirer l’ancienne installation utilisateur détectée ? [O/n] "
        read -r answer
        case "$answer" in n|N|non|NON) remove_legacy_user_install=0 ;; esac
      fi
      ;;
    3) echo "Installation annulée."; exit 0 ;;
    *) echo "Choix incorrect : installation annulée."; exit 1 ;;
  esac
fi

install -d "$(dirname "$application_target")" "$applications_dir" "$icons_dir" "$mime_icons_dir" "$mime_packages_dir" "$thumbnailers_dir"
# Replace the program files instead of merging them. User settings and documents
# live outside this directory and are therefore preserved.
rm -rf -- "$application_target"
install -d "$application_target"
cp -a "$application_source/." "$application_target/"
install -m 0644 "$bundle_dir/VERSION" "$application_target/VERSION"
install -m 0755 "$bundle_dir/uninstaller.sh" "$application_target/uninstall.sh"
install -m 0755 "$bundle_dir/check-requirements.sh" "$application_target/check-requirements.sh"
if [ "$remove_legacy_user_install" -eq 1 ] && [ -d "$legacy_user_target" ]; then
  rm -rf -- "$legacy_user_target"
fi
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
  # Ne jamais créer ni remplacer ~/.local/share/icons/hicolor/index.theme.
  # Un thème hicolor utilisateur incomplet masque le thème système actif et
  # transforme alors les icônes des autres applications en engrenages.
  # Les icônes Lou Còdi sont déposées dans les répertoires normalisés et les
  # variantes MIME disposent également de fallbacks non thémés.
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
  # Unthemed fallbacks are looked up directly and remain available even when
  # another application has left the user's shared hicolor cache invalid.
  install -m 0644 "$bundle_dir/lou-codi-document.png" \
    "$data_root/icons/application-x-loucodi-document.png"
  install -m 0644 "$bundle_dir/lou-codi-document.svg" \
    "$data_root/icons/application-x-loucodi-document.svg"
  install -m 0644 "$bundle_dir/lou-codi-document.svg" \
    "$data_root/icons/application-x-loucodi-document-symbolic.svg"
  install -m 0644 "$bundle_dir/lou-codi-document.png" \
    "$application_target/lou-codi-document-thumbnail.png"

  thumbnailer_script="$application_target/lou-codi-document-thumbnailer"
  cat > "$thumbnailer_script" <<EOF
#!/bin/sh
# Nautilus asks thumbnailers for an output PNG. The Lou Còdi file contents do
# not need to be opened: the branded COD tile itself is the intended preview.
cp "$application_target/lou-codi-document-thumbnail.png" "\$2"
EOF
  chmod 0755 "$thumbnailer_script"
  cat > "$thumbnailers_dir/lou-codi-document.thumbnailer" <<EOF
[Thumbnailer Entry]
TryExec=$thumbnailer_script
Exec=$thumbnailer_script %i %o %s
MimeType=application/x-loucodi-document;
EOF

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

uninstall_desktop_file="$applications_dir/lou-codi-workshop-uninstall.desktop"
{
  echo '[Desktop Entry]'
  echo 'Name=Désinstaller Lou Còdi Workshop'
  echo 'Comment=Retirer Lou Còdi Workshop en conservant les documents personnels'
  printf 'Exec=%s/uninstall.sh\n' "$application_target"
  echo 'Icon=edit-delete'
  echo 'Terminal=false'
  echo 'Type=Application'
  echo 'Categories=Settings;Utility;'
  echo 'Keywords=Lou Còdi;désinstaller;supprimer;uninstall;'
  echo 'NoDisplay=false'
} > "$uninstall_desktop_file"
chmod 0644 "$uninstall_desktop_file"

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
echo "- Menu des applications : Désinstaller Lou Còdi Workshop"
if [ "$install_launcher" -eq 1 ]; then
  echo "- Raccourci : disponible dans le menu des applications."
else
  echo "- Raccourci : non créé. Exécutable : $application_target/lou-codi-pdf-converter"
fi
if [ -n "$legacy_system_install" ]; then
  echo
  echo "Une ancienne installation système reste présente : $legacy_system_install"
  echo "Pour la retirer après avoir fermé Lou Còdi :"
  echo "  sudo rm -rf -- /opt/$legacy_brand-pdf-converter"
  echo "  sudo rm -f -- /usr/share/applications/$legacy_brand-pdf-converter.desktop"
  echo "  sudo update-desktop-database /usr/share/applications"
fi
if [ "$gui" -eq 1 ]; then
  zenity --info --title="Lou Còdi Workshop" \
    --text="Installation terminée.\n\nVersion : $bundle_version\nDésinstallation : $application_target/uninstall.sh" \
    --width=560 2>/dev/null || true
fi

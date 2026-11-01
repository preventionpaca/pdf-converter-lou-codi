#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
python_command=${PYTHON:-python3}
app_version=$(PYTHONPATH="$project_dir/src" "$python_command" -c 'from lou_codi_pdf_converter import __version__; print(__version__)')
"$python_command" "$project_dir/packaging/generate_document_icons.py"
deb_version=${app_version/a/~a}
package_root="$project_dir/dist/deb-root"
installer_dir="$project_dir/dist/installers"
package="$installer_dir/Lou-Codi-Workshop-$app_version-linux-amd64.deb"

rm -rf -- "$package_root"
mkdir -p \
  "$package_root/DEBIAN" \
  "$package_root/opt/lou-codi-workshop" \
  "$package_root/usr/bin" \
  "$package_root/usr/share/applications" \
  "$package_root/usr/share/icons/hicolor/scalable/mimetypes" \
  "$package_root/usr/lib/lou-codi-workshop" \
  "$package_root/usr/share/pixmaps" \
  "$package_root/usr/share/thumbnailers" \
  "$package_root/usr/share/mime/packages" \
  "$installer_dir"

cp -a "$project_dir/dist/lou-codi-pdf-converter/." "$package_root/opt/lou-codi-workshop/"
for size in 16 24 32 48 64 128 256 512; do
  mkdir -p "$package_root/usr/share/icons/hicolor/${size}x${size}/apps"
  cp "$project_dir/src/lou_codi_pdf_converter/assets/lou-codi-workshop-$size.png" \
    "$package_root/usr/share/icons/hicolor/${size}x${size}/apps/lou-codi-workshop.png"
done
for size in 16 24 32 48 64 128 256; do
  mkdir -p "$package_root/usr/share/icons/hicolor/${size}x${size}/mimetypes"
  cp "$project_dir/src/lou_codi_pdf_converter/assets/lou-codi-document-$size.png" \
    "$package_root/usr/share/icons/hicolor/${size}x${size}/mimetypes/application-x-loucodi-document.png"
done
cp "$project_dir/src/lou_codi_pdf_converter/assets/lou-codi-document.svg" \
  "$package_root/usr/share/icons/hicolor/scalable/mimetypes/application-x-loucodi-document.svg"
cp "$project_dir/src/lou_codi_pdf_converter/assets/lou-codi-document.svg" \
  "$package_root/usr/share/icons/hicolor/scalable/mimetypes/application-x-loucodi-document-symbolic.svg"
# Some GNOME/Nautilus combinations do not resolve MIME icons inherited from
# hicolor in compact list views. /usr/share/pixmaps is the freedesktop legacy
# fallback searched independently of the active icon theme.
cp "$project_dir/src/lou_codi_pdf_converter/assets/lou-codi-document.png" \
  "$package_root/usr/share/pixmaps/application-x-loucodi-document.png"
cp "$project_dir/src/lou_codi_pdf_converter/assets/lou-codi-document.png" \
  "$package_root/usr/share/pixmaps/application-x-loucodi-document-symbolic.png"

cat > "$package_root/usr/share/thumbnailers/lou-codi-document.thumbnailer" <<'EOF'
[Thumbnailer Entry]
TryExec=/opt/lou-codi-workshop/lou-codi-document-thumbnailer
Exec=/opt/lou-codi-workshop/lou-codi-document-thumbnailer %i %o %s
MimeType=application/x-loucodi-document;
EOF
cat > "$package_root/opt/lou-codi-workshop/lou-codi-document-thumbnailer" <<'EOF'
#!/usr/bin/env sh
set -eu
cp /opt/lou-codi-workshop/_internal/lou_codi_pdf_converter/assets/lou-codi-document.png "$2"
EOF
chmod 0755 "$package_root/opt/lou-codi-workshop/lou-codi-document-thumbnailer"

cat > "$package_root/usr/bin/lou-codi-workshop" <<'EOF'
#!/usr/bin/env sh
config_root=${XDG_CONFIG_HOME:-"$HOME/.config"}/lou-codi-workshop
desktop_marker="$config_root/desktop-shortcut-checked"
icon_marker="$config_root/document-icons-a18-checked"
cleanup_marker="$config_root/legacy-installations-a18-cleaned"
if [ ! -e "$cleanup_marker" ]; then
  legacy_brand="lou""camin"
  rm -rf -- "${XDG_DATA_HOME:-$HOME/.local/share}/lou-codi-workshop" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/lou-codi-pdf-converter" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/$legacy_brand-pdf-converter"
  rm -f -- "${XDG_DATA_HOME:-$HOME/.local/share}/applications/lou-codi-pdf-converter.desktop" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/applications/$legacy_brand-pdf-converter.desktop"
  mkdir -p "$config_root" 2>/dev/null || true
  touch "$cleanup_marker" 2>/dev/null || true
fi
if [ ! -e "$desktop_marker" ]; then
  desktop_dir=""
  if command -v xdg-user-dir >/dev/null 2>&1; then
    desktop_dir=$(xdg-user-dir DESKTOP 2>/dev/null || true)
  fi
  if [ -n "$desktop_dir" ] && [ -d "$desktop_dir" ] && [ -w "$desktop_dir" ]; then
    cp /usr/share/applications/lou-codi-workshop.desktop \
      "$desktop_dir/Lou Còdi Workshop.desktop" 2>/dev/null || true
    chmod +x "$desktop_dir/Lou Còdi Workshop.desktop" 2>/dev/null || true
    if command -v gio >/dev/null 2>&1; then
      gio set "$desktop_dir/Lou Còdi Workshop.desktop" metadata::trusted true \
        >/dev/null 2>&1 || true
    fi
  fi
  mkdir -p "$config_root" 2>/dev/null || true
  touch "$desktop_marker" 2>/dev/null || true
fi
if [ ! -e "$icon_marker" ] && command -v gio >/dev/null 2>&1; then
  /usr/bin/lou-codi-workshop-refresh-icons >/dev/null 2>&1 || true
  mkdir -p "$config_root" 2>/dev/null || true
  touch "$icon_marker" 2>/dev/null || true
fi
exec /opt/lou-codi-workshop/lou-codi-pdf-converter "$@"
EOF
chmod 0755 "$package_root/usr/bin/lou-codi-workshop"

cat > "$package_root/usr/bin/lou-codi-workshop-refresh-icons" <<'EOF'
#!/usr/bin/env sh
set -eu
icon=/usr/share/pixmaps/application-x-loucodi-document.png
[ -f "$icon" ] || exit 0
icon_uri="file://$icon"

apply_icon() {
  [ -f "$1" ] || return 0
  gio set "$1" metadata::custom-icon "$icon_uri" >/dev/null 2>&1 || true
}

if [ "$#" -gt 0 ]; then
  for document in "$@"; do
    apply_icon "$document"
  done
  exit 0
fi

downloads=${XDG_DOWNLOAD_DIR:-"$HOME/Téléchargements"}
if command -v xdg-user-dir >/dev/null 2>&1; then
  detected=$(xdg-user-dir DOWNLOAD 2>/dev/null || true)
  [ -n "$detected" ] && downloads="$detected"
fi
if [ -d "$downloads" ]; then
  find "$downloads" -maxdepth 5 -type f \
    \( -iname '*.cod' -o -iname '*.code' -o -iname '*.loucodi-document' \) \
    -exec gio set {} metadata::custom-icon "$icon_uri" \; 2>/dev/null || true
fi
EOF
chmod 0755 "$package_root/usr/bin/lou-codi-workshop-refresh-icons"

cat > "$package_root/usr/share/applications/lou-codi-workshop.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Lou Còdi Workshop
GenericName=Atelier de documents PDF et de dessin
Comment=Des outils pratiques, en local, pour créer et fabriquer
Exec=lou-codi-workshop %f
Icon=lou-codi-workshop
Terminal=false
Categories=Office;
Keywords=Lou Còdi;Lou Codi;Loucodi;Lou Kodi;BlueKodi;PDF;Document Studio;dessin;atelier;
MimeType=application/x-loucodi-document;application/x-loucodi-space;
StartupNotify=true
StartupWMClass=Loucodiworkshop
EOF

cat > "$package_root/usr/lib/lou-codi-workshop/uninstall-all" <<'EOF'
#!/usr/bin/env sh
set -eu
# Remove only obsolete program locations and launchers. User documents under
# Downloads/LouCodi are deliberately never touched.
legacy_brand="lou""camin"
rm -rf -- /opt/lou-codi-pdf-converter "/opt/$legacy_brand-pdf-converter"
rm -f -- /usr/share/applications/lou-codi-pdf-converter.desktop \
  "/usr/share/applications/$legacy_brand-pdf-converter.desktop"
exec apt-get remove -y lou-codi-workshop
EOF
chmod 0755 "$package_root/usr/lib/lou-codi-workshop/uninstall-all"

cat > "$package_root/usr/bin/lou-codi-workshop-uninstall" <<'EOF'
#!/usr/bin/env sh
set -eu

message='Désinstaller Lou Còdi Workshop ?\n\nVos documents et projets personnels seront conservés.'
data_root=${XDG_DATA_HOME:-"$HOME/.local/share"}
cleanup_user_install() {
  rm -rf -- "$data_root/lou-codi-workshop" "$data_root/lou-codi-pdf-converter"
  rm -f -- "$data_root/applications/lou-codi-workshop.desktop" \
    "$data_root/applications/lou-codi-workshop-uninstall.desktop" \
    "$data_root/applications/lou-codi-pdf-converter.desktop"
}
if command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  zenity --question --title='Désinstaller Lou Còdi Workshop' \
    --text="$message" --width=560 2>/dev/null || exit 0
  cleanup_user_install
  if command -v pkexec >/dev/null 2>&1; then
    pkexec /usr/lib/lou-codi-workshop/uninstall-all
  else
    zenity --error --title='Désinstallation impossible' \
      --text='Le composant système pkexec est absent. Ouvrez un terminal et exécutez :\n\nsudo apt remove lou-codi-workshop' \
      --width=600 2>/dev/null || true
    exit 1
  fi
else
  printf '%s\n' 'DÉSINSTALLATION DE LOU CÒDI WORKSHOP' \
    'Vos documents et projets personnels seront conservés.'
  printf 'Continuer ? [o/N] '
  read -r answer
  case "$answer" in o|O|oui|OUI|y|Y|yes|YES) ;; *) exit 0 ;; esac
  cleanup_user_install
  exec sudo /usr/lib/lou-codi-workshop/uninstall-all
fi
EOF
chmod 0755 "$package_root/usr/bin/lou-codi-workshop-uninstall"

cat > "$package_root/usr/share/applications/lou-codi-workshop-uninstall.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Désinstaller Lou Còdi Workshop
Comment=Retirer l’application en conservant les documents personnels
Exec=lou-codi-workshop-uninstall
Icon=edit-delete
Terminal=false
Categories=Settings;
Keywords=Lou Còdi;Lou Codi;Loucodi;Lou Kodi;BlueKodi;désinstaller;supprimer;uninstall;
NoDisplay=false
EOF

cat > "$package_root/usr/share/mime/packages/lou-codi-document.xml" <<'EOF'
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

installed_size=$(du -sk "$package_root/opt/lou-codi-workshop" | cut -f1)
cat > "$package_root/DEBIAN/control" <<EOF
Package: lou-codi-workshop
Version: $deb_version
Section: graphics
Priority: optional
Architecture: amd64
Depends: libc6
Suggests: libreoffice, xdg-utils, desktop-file-utils, shared-mime-info
Installed-Size: $installed_size
Maintainer: Lou Còdi <contact@lou-codi.fr>
Homepage: https://github.com/preventionpaca/pdf-converter-lou-codi
Description: Outils locaux pour les PDF, documents et travaux d'atelier
 Lou Còdi Workshop rassemble PDF Studio, Document Studio et les outils
 d'optimisation de découpe. Les traitements documentaires restent locaux.
 LibreOffice est facultatif et n'est pas installé par ce paquet.
EOF

cat > "$package_root/DEBIAN/postinst" <<'EOF'
#!/usr/bin/env sh
set -e
if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database /usr/share/mime >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if command -v xdg-desktop-menu >/dev/null 2>&1; then
  xdg-desktop-menu forceupdate --mode system >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$package_root/DEBIAN/postinst"

cat > "$package_root/DEBIAN/preinst" <<'EOF'
#!/usr/bin/env sh
set -e
legacy_brand="lou""camin"
rm -rf -- /opt/lou-codi-pdf-converter "/opt/$legacy_brand-pdf-converter"
rm -f -- /usr/share/applications/lou-codi-pdf-converter.desktop \
  "/usr/share/applications/$legacy_brand-pdf-converter.desktop"
exit 0
EOF
chmod 0755 "$package_root/DEBIAN/preinst"

cat > "$package_root/DEBIAN/prerm" <<'EOF'
#!/usr/bin/env sh
set -e
pkill -f /opt/lou-codi-workshop/lou-codi-pdf-converter >/dev/null 2>&1 || true
exit 0
EOF
chmod 0755 "$package_root/DEBIAN/prerm"

cat > "$package_root/DEBIAN/postrm" <<'EOF'
#!/usr/bin/env sh
set -e
if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database /usr/share/mime >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$package_root/DEBIAN/postrm"

dpkg-deb --root-owner-group --build "$package_root" "$package"
echo "$package"

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
  "$package_root/usr/share/icons/hicolor/256x256/apps" \
  "$package_root/usr/share/mime/packages" \
  "$installer_dir"

cp -a "$project_dir/dist/lou-codi-pdf-converter/." "$package_root/opt/lou-codi-workshop/"
cp "$project_dir/src/lou_codi_pdf_converter/assets/croix-lou-codi.png" \
  "$package_root/usr/share/icons/hicolor/256x256/apps/lou-codi-workshop.png"
mkdir -p "$package_root/usr/share/icons/hicolor/256x256/mimetypes"
cp "$project_dir/src/lou_codi_pdf_converter/assets/lou-codi-document.png" \
  "$package_root/usr/share/icons/hicolor/256x256/mimetypes/application-x-loucodi-document.png"

cat > "$package_root/usr/bin/lou-codi-workshop" <<'EOF'
#!/usr/bin/env sh
exec /opt/lou-codi-workshop/lou-codi-pdf-converter "$@"
EOF
chmod 0755 "$package_root/usr/bin/lou-codi-workshop"

cat > "$package_root/usr/share/applications/lou-codi-workshop.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Lou Còdi Workshop
Comment=Des outils pratiques, en local, pour créer et fabriquer
Exec=lou-codi-workshop %f
Icon=lou-codi-workshop
Terminal=false
Categories=Office;Graphics;Utility;
MimeType=application/x-loucodi-document;
StartupNotify=true
StartupWMClass=Loucodiworkshop
EOF

cat > "$package_root/usr/share/mime/packages/lou-codi-document.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-loucodi-document">
    <comment>Document Lou Còdi</comment>
    <glob pattern="*.cod"/>
    <glob pattern="*.loucodi-document"/>
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
Installed-Size: $installed_size
Maintainer: Lou Còdi <contact@lou-codi.fr>
Depends: libxcb-cursor0
Homepage: https://github.com/preventionpaca/pdf-converter-lou-codi
Description: Outils locaux pour les PDF, documents et travaux d'atelier
 Lou Còdi Workshop rassemble PDF Studio, Document Studio et les outils
 d'optimisation de découpe. Les traitements documentaires restent locaux.
 LibreOffice est facultatif et n'est pas installé par ce paquet.
EOF

cat > "$package_root/DEBIAN/postinst" <<'EOF'
#!/usr/bin/env sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database /usr/share/mime >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$package_root/DEBIAN/postinst"

cat > "$package_root/DEBIAN/prerm" <<'EOF'
#!/usr/bin/env sh
set -e
pkill -f /opt/lou-codi-workshop/lou-codi-pdf-converter >/dev/null 2>&1 || true
exit 0
EOF
chmod 0755 "$package_root/DEBIAN/prerm"

dpkg-deb --root-owner-group --build "$package_root" "$package"
echo "$package"

#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"

install -d "$applications_dir" "$icons_dir"
# Remove the former launcher identity so Linux does not create a second generic
# taskbar entry for the same process after an upgrade.
if [ -f "$applications_dir/lou-codi-pdf-converter.desktop" ]; then
  unlink "$applications_dir/lou-codi-pdf-converter.desktop"
fi
install -m 0644 \
  "$project_dir/packaging/linux/lou-codi-pdf-converter.desktop" \
  "$applications_dir/lou-codi-workshop.desktop"

if command -v convert >/dev/null 2>&1; then
  convert \
    "$project_dir/src/lou_codi_pdf_converter/assets/croix-lou-codi.png" \
    -resize 256x256 \
    "$icons_dir/lou-codi-workshop.png"
elif command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -loglevel error -y \
    -i "$project_dir/src/lou_codi_pdf_converter/assets/croix-lou-codi.png" \
    -vf scale=256:256 \
    "$icons_dir/lou-codi-workshop.png"
else
  install -m 0644 \
    "$project_dir/src/lou_codi_pdf_converter/assets/croix-lou-codi.png" \
    "$icons_dir/lou-codi-workshop.png"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$applications_dir"
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Lou Còdi Workshop est installé dans le menu des applications."

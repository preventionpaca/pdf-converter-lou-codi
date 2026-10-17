#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
python_command=${PYTHON:-python3}
version=$(PYTHONPATH="$project_dir/src" "$python_command" -c 'from lou_codi_pdf_converter import __version__; print(__version__)')
bundle="$project_dir/dist/Lou-Codi-Workshop-$version-linux-x86_64"
archive="$project_dir/dist/installers/Lou-Codi-Workshop-$version-linux-x86_64.tar.gz"

if [ -d "$bundle" ]; then
  rm -rf -- "$bundle"
fi
mkdir -p "$bundle/app" "$project_dir/dist/installers"
cp -a "$project_dir/dist/lou-codi-pdf-converter/." "$bundle/app/"
if [ -d "$bundle/app/_internal/speech-models" ]; then
  mkdir -p "$bundle/options"
  mv "$bundle/app/_internal/speech-models" "$bundle/options/speech-models"
fi
cp "$project_dir/packaging/linux/install-bundle.sh" "$bundle/installer.sh"
cp "$project_dir/src/lou_codi_pdf_converter/assets/croix-lou-codi.png" "$bundle/lou-codi-workshop.png"
chmod +x "$bundle/installer.sh"
tar -C "$project_dir/dist" -czf "$archive" "$(basename "$bundle")"
echo "$archive"

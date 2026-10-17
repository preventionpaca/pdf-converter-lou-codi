#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
python_command=${PYTHON:-python3}
version=$(PYTHONPATH="$project_dir/src" "$python_command" -c 'from lou_codi_pdf_converter import __version__; print(__version__)')
staging="$project_dir/dist/dmg"
output="$project_dir/dist/installers/Lou-Codi-Workshop-$version-macos.dmg"
mkdir -p "$staging" "$project_dir/dist/installers"
cp -a "$project_dir/dist/Lou Còdi Workshop.app" "$staging/"
cp "$project_dir/packaging/macos/LISEZ-MOI.txt" "$staging/"
ln -s /Applications "$staging/Applications"
hdiutil create -volname "Lou Còdi Workshop" -srcfolder "$staging" -ov -format UDZO "$output"
echo "$output"

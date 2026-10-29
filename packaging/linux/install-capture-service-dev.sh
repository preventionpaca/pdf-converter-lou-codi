#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
python_bin="$project_dir/.venv/bin/python"
unit_source="$project_dir/packaging/linux/lou-codi-capture.service"
unit_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
unit_target="$unit_dir/lou-codi-capture.service"

if [ ! -x "$python_bin" ]; then
  echo "Environnement Python introuvable : $python_bin" >&2
  exit 1
fi

mkdir -p "$unit_dir"
sed "s|@PYTHON@|$python_bin|g" "$unit_source" > "$unit_target.tmp"
chmod 600 "$unit_target.tmp"
mv "$unit_target.tmp" "$unit_target"
systemctl --user daemon-reload
systemctl --user enable lou-codi-capture.service
systemctl --user restart lou-codi-capture.service || true

echo "Service Lou Còdi Capture installé."
echo "État : systemctl --user status lou-codi-capture.service"

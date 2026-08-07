#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only
#
# Regenerate python-deps.json from the runtime's Python version.
#
# All three dependencies are importable as-is: markdown and pygments publish a
# universal py3-none-any wheel, and PyYAML publishes manylinux wheels. Hence
# --prefer-wheels for pyyaml, which would otherwise build its optional libyaml
# C extension from the sdist; --runtime makes pip resolve against the runtime's
# interpreter rather than the host's, which matters because PyYAML's wheels are
# per-Python-version (cp313 for runtime 49) and the host's Python will differ.
set -euo pipefail

RUNTIME_VERSION=49
HERE="$(cd "$(dirname "$0")" && pwd)"

command -v flatpak-pip-generator >/dev/null || {
  echo "Install flatpak-builder-tools first:" >&2
  echo "  https://github.com/flatpak/flatpak-builder-tools/tree/master/pip" >&2
  exit 1
}

flatpak install -y flathub "org.gnome.Sdk//${RUNTIME_VERSION}"

flatpak-pip-generator \
  --runtime="org.gnome.Sdk//${RUNTIME_VERSION}" \
  --prefer-wheels=pyyaml \
  --cleanup=all \
  --output="${HERE}/python-deps" \
  markdown pygments pyyaml

echo "Wrote ${HERE}/python-deps.json"

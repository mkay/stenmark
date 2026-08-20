#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="stenmark"
VERSION=$(grep -oP "^version:\s*'\K[^']+" meson.build || echo "0.8.0")
DEB_STAGING="$(pwd)/deb-staging"
CONFIG_FILE="/tmp/nfpm-stenmark.yaml"

cleanup() {
    rm -rf "$DEB_STAGING" "$CONFIG_FILE" builddir
}
trap cleanup EXIT

echo "==> Building .deb package for $PROJECT_NAME v$VERSION"

# 1. Ensure required build tools exist
for cmd in meson ninja nfpm; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: Missing required command '$cmd'. Install meson, ninja-build, and nfpm first."
        exit 1
    fi
done

# 2. Stage the application installation tree
rm -rf "$DEB_STAGING" builddir
meson setup builddir --prefix=/usr
meson compile -C builddir
DESTDIR="$DEB_STAGING" meson install -C builddir --no-rebuild

# 3. Generate contents list for nFPM
CONTENTS=""
while IFS= read -r file; do
    dst="${file#"$DEB_STAGING"}"
    CONTENTS+="  - src: $file
    dst: $dst
"
done < <(find "$DEB_STAGING" -type f)

# 4. Write nFPM configuration
cat > "$CONFIG_FILE" <<NFPM
name: $PROJECT_NAME
arch: amd64
version: $VERSION
maintainer: local
description: GTK4 Markdown note editor
license: GPL-3.0-only
depends:
  - python3
  - gir1.2-gtk-4.0
  - gir1.2-adw-1
  - gir1.2-webkit-6.0
  - python3-gi
  - python3-markdown
contents:
$CONTENTS
NFPM

# 5. Build .deb package
nfpm package -p deb -f "$CONFIG_FILE"

echo "==> Successfully built package:"
ls -l "${PROJECT_NAME}"_*.deb
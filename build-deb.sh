#!/usr/bin/env bash
set -euo pipefail

# Builds a .deb from the current checkout, without any of the release
# machinery — no tagging, no pushing, no uploads. Useful for packaging a
# branch, or a main that is ahead of the latest release.

cd "$(dirname "$(readlink -f "$0")")"

# Metadata comes from the files that already define it, so a .deb built here
# describes itself the same way a released one does.
PROJECT_NAME=$(grep -oP "^project\(\s*'\K[^']+" meson.build || true)
VERSION=$(grep -oP "^\s*version:\s*'\K[^']+" meson.build || true)
PKGDESC=$(grep -oP "^pkgdesc=['\"]\K[^'\"]+" PKGBUILD || true)
PKGLICENSE=$(grep -oP "^license=\('\K[^']+" PKGBUILD || true)
MAINTAINER=$(grep -oP "^# Maintainer:\s*\K.+" PKGBUILD || true)

# A wrong version in a package is worse than no package — never guess.
if [[ -z "$PROJECT_NAME" || -z "$VERSION" ]]; then
    echo "ERROR: Could not read project name and version from meson.build"
    exit 1
fi

# Debian architecture name, which is not what uname reports.
if command -v dpkg &>/dev/null; then
    ARCH=$(dpkg --print-architecture)
else
    case "$(uname -m)" in
        x86_64)  ARCH=amd64 ;;
        aarch64) ARCH=arm64 ;;
        armv7l)  ARCH=armhf ;;
        i?86)    ARCH=i386 ;;
        *)
            echo "ERROR: Unknown architecture '$(uname -m)'. Install dpkg or set ARCH by hand."
            exit 1
            ;;
    esac
fi

DEB_STAGING="$(pwd)/deb-staging"
CONFIG_FILE=$(mktemp -t "nfpm-$PROJECT_NAME-XXXXXX.yaml")
OUTPUT="${PROJECT_NAME}_${VERSION}_${ARCH}.deb"

cleanup() {
    # Preserve the script's real exit status — the tests below must not set it.
    # builddir is deliberately left alone: it is the checkout's own build tree,
    # not something this script owns.
    local status=$?
    [[ -d "$DEB_STAGING" ]] && rm -rf "$DEB_STAGING"
    [[ -f "$CONFIG_FILE" ]] && rm -f "$CONFIG_FILE"
    return $status
}
trap cleanup EXIT

echo "==> Building .deb package for $PROJECT_NAME v$VERSION ($ARCH)"

# 1. Ensure required build tools exist
for cmd in meson ninja nfpm; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: Missing required command '$cmd'. Install meson, ninja-build, and nfpm first."
        exit 1
    fi
done

# 2. Stage the application installation tree
rm -rf "$DEB_STAGING"
if [[ -d builddir ]]; then
    meson setup builddir --prefix=/usr --wipe
else
    meson setup builddir --prefix=/usr
fi
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
arch: $ARCH
version: $VERSION
maintainer: $MAINTAINER
description: $PKGDESC
license: $PKGLICENSE
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
nfpm package -p deb -f "$CONFIG_FILE" -t "$OUTPUT"

echo "==> Successfully built package:"
ls -l "$OUTPUT"

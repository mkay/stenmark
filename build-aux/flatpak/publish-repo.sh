#!/bin/bash
# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only
#
# Build Stenmark's Flatpak and publish it to the static OSTree repo that users
# add as a remote. Run from a clean checkout at the tag you are releasing: the
# manifest's source is `type: dir`, so whatever is in the working tree is what
# ships, and a stray edit would be published as if it were the release.
#
# The published repo is a plain directory of content-addressed files served over
# HTTP — no OSTree software runs on the host. GitHub Pages is therefore enough.
#
# Not wired into release.sh: publishing is a separate decision from tagging, and
# a failure here should never leave a half-finished release behind.

set -euo pipefail

APP_ID="de.singular.stenmark"
MANIFEST="build-aux/flatpak/de.singular.stenmark.yaml"

# Throwaway build state; the repo below is the only durable output.
BUILD_DIR="${STENMARK_FLATPAK_BUILD:-$HOME/.cache/stenmark-flatpak/build}"
REPO="${STENMARK_FLATPAK_REPO:-$HOME/.cache/stenmark-flatpak/repo}"

# Working checkout of the GitHub Pages repo that serves the files.
PAGES="${STENMARK_PAGES_CHECKOUT:-$HOME/Staging/stenmark-flatpak}"
PAGES_URL="${STENMARK_PAGES_URL:-https://mkay.github.io/stenmark-flatpak/}"

# Signing key. Stenmark has its own, separate from Edith's: a compromise stays
# contained, and each .flatpakrepo embeds the key its repo was signed with.
GPG_KEY="${STENMARK_GPG_KEY:-2BE7C6CC719C6131304457452F4B6E1C5580BF18}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "$MANIFEST" ]] || die "run this from the repository root ($MANIFEST not found)"
[[ -n "$GPG_KEY" ]] || die "set STENMARK_GPG_KEY to the signing key's fingerprint"
gpg --list-secret-keys "$GPG_KEY" >/dev/null 2>&1 || die "no secret key for $GPG_KEY"

# The manifest ships the working tree, so a dirty tree ships uncommitted work.
if ! git diff --quiet || ! git diff --cached --quiet; then
    die "working tree is dirty — commit or stash before publishing"
fi

VERSION=$(git describe --tags --exact-match 2>/dev/null || true)
if [[ -z "$VERSION" ]]; then
    echo "WARNING: HEAD is not tagged; publishing an untagged build" >&2
    VERSION=$(git rev-parse --short HEAD)
fi
echo "==> Publishing $APP_ID at $VERSION"

# 1. Build unsigned. org.flatpak.Builder is itself a Flatpak and its sandbox
#    ships no pinentry, so a --gpg-sign here fails with "GPG Agent: No pinentry"
#    however warm the host's passphrase cache is. Signing happens on the host in
#    step 3, where the agent can actually reach a pinentry.
echo "==> Building"
flatpak run org.flatpak.Builder --user --force-clean \
    --repo="$REPO" \
    "$BUILD_DIR" "$MANIFEST"

# 2. Debug symbols roughly double the repo for something no user of a binary
#    remote will ever consume. Dropped before the summary is regenerated so the
#    ref never appears to clients; prune then reclaims the objects.
if ostree refs --repo="$REPO" | grep -q "^runtime/$APP_ID.Debug/"; then
    echo "==> Dropping the Debug ref"
    ostree refs --repo="$REPO" --delete "runtime/$APP_ID.Debug/x86_64/master"
fi

# 3. Sign every remaining commit, on the host. Done after the Debug ref is gone
#    so nothing is signed that is about to be pruned.
echo "==> Signing commits"
for ref in $(ostree refs --repo="$REPO"); do
    ostree gpg-sign --repo="$REPO" "$ref" "$GPG_KEY" >/dev/null
    echo "    signed $ref"
done

# 4. Static deltas turn an update into one small download instead of hundreds of
#    object fetches. --prune drops anything no ref reaches any more, which is
#    what stops the repo growing without bound across releases. This also signs
#    the summary, which is what a client checks first.
echo "==> Updating repo metadata"
flatpak build-update-repo \
    --generate-static-deltas \
    --prune \
    --gpg-sign="$GPG_KEY" \
    "$REPO"

# 5. Publish. Replaced wholesale rather than merged: a pruned object has to
#    disappear from the served copy too, and at this size a full copy costs less
#    than depending on rsync, which is not installed everywhere. Only repo/ is
#    touched — the README, .nojekyll and the landing page live beside it and
#    survive.
[[ -d "$PAGES/.git" ]] || die "$PAGES is not a git checkout — clone the Pages repo there first"
echo "==> Syncing into $PAGES"
rm -rf "$PAGES/repo"
cp -a "$REPO" "$PAGES/repo"

# 6. The file users actually click. Regenerated every time so the embedded key
#    can never drift from the key the repo was signed with. The summary is read
#    from the metainfo rather than repeated here, so the two cannot disagree.
SUMMARY=$(sed -n 's:.*<summary>\(.*\)</summary>.*:\1:p' data/de.singular.stenmark.metainfo.xml.in | head -1)
[[ -n "$SUMMARY" ]] || die "could not read <summary> from the metainfo"
echo "==> Writing stenmark.flatpakrepo"
cat > "$PAGES/stenmark.flatpakrepo" <<EOF
[Flatpak Repo]
Title=Stenmark
Url=${PAGES_URL}repo/
Homepage=https://github.com/mkay/stenmark
Comment=$SUMMARY
Description=A GTK4 Markdown reader, organizer and editor.
Icon=${PAGES_URL}icon.svg
GPGKey=$(gpg --export "$GPG_KEY" | base64 -w0)
EOF

# GitHub Pages runs Jekyll by default, which ignores directories beginning with
# an underscore and would silently drop parts of the repo.
touch "$PAGES/.nojekyll"

echo "==> Committing"
git -C "$PAGES" add -A
if git -C "$PAGES" diff --cached --quiet; then
    echo "==> Nothing changed, not committing"
else
    git -C "$PAGES" commit -q -m "Publish $VERSION"
    echo "==> Run: git -C $PAGES push"
fi

echo
echo "Published $VERSION. Users install with:"
echo "  flatpak remote-add --user stenmark ${PAGES_URL}stenmark.flatpakrepo"
echo "  flatpak install stenmark $APP_ID"

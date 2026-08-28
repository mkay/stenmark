#!/bin/bash
set -euo pipefail

VERSION="${1:-}"
TITLE="${2:-}"

if [[ -z "$VERSION" ]]; then
    echo "Usage: ./release.sh <version> [title]"
    echo "Example: ./release.sh 1.2.3"
    echo "Example: ./release.sh 1.2.3 \"Some Catchy Name\""
    exit 1
fi

# Strip leading 'v' if provided — version numbers in files are bare,
# git tag gets the v prefix
VERSION="${VERSION#v}"
TAG="v$VERSION"
TITLE="${TITLE:-$TAG}"

# Auto-detect project name from meson.build
PROJECT_NAME=$(grep -oP "^project\(\s*'\K[^']+" meson.build)
if [[ -z "$PROJECT_NAME" ]]; then
    echo "ERROR: Could not detect project name from meson.build"
    exit 1
fi

# Cleanup handler for temp directories
AUR_DIR=""
cleanup() {
    # Preserve the script's real exit status — the test below must not set it
    local status=$?
    [[ -n "$AUR_DIR" && -d "$AUR_DIR" ]] && rm -rf "$AUR_DIR"
    return $status
}
trap cleanup EXIT

echo "==> Releasing $PROJECT_NAME $TAG"

# 0. The release notes must actually describe this release. The what's-new
# dialog shows whatsnew.md verbatim under the new version number, so shipping
# the previous release's bullets tells every updating user something false.
# Checked before anything is bumped, tagged or pushed, so a failure here costs
# nothing but a re-run.
WHATSNEW="$PROJECT_NAME/data/whatsnew.md"
PREV_TAG=$(git tag --sort=-version:refname | head -1)

if [[ ! -f "$WHATSNEW" ]]; then
    echo "ERROR: $WHATSNEW is missing — the release notes dialog reads it."
    exit 1
elif [[ -n "${SKIP_WHATSNEW_CHECK:-}" ]]; then
    echo "==> SKIP_WHATSNEW_CHECK set, not checking $WHATSNEW"
elif [[ -z "$PREV_TAG" ]]; then
    echo "==> First release, not checking $WHATSNEW"
else
    # release.sh only commits meson.build, PKGBUILD and __init__.py, so an
    # uncommitted edit here would be left out of the tag it was written for.
    if ! git diff --quiet -- "$WHATSNEW" || ! git diff --cached --quiet -- "$WHATSNEW"; then
        echo "ERROR: $WHATSNEW has uncommitted changes."
        echo "       release.sh won't include them in $TAG. Commit them first."
        exit 1
    fi
    if [[ -z "$(git log --oneline "$PREV_TAG..HEAD" -- "$WHATSNEW")" ]]; then
        echo "ERROR: $WHATSNEW has not changed since $PREV_TAG."
        echo "       The what's-new dialog would show $PREV_TAG's notes under $TAG."
        echo "       Rewrite it, or re-run with SKIP_WHATSNEW_CHECK=1."
        exit 1
    fi
    echo "==> Release notes for $TAG:"
    awk '/<!--/{c=1} /-->/{c=0;next} !c' "$WHATSNEW" \
        | sed -n 's/^[[:space:]]*[-*•][[:space:]]*/    • /p'
fi

# 0b. AppStream is where GNOME Software, KDE Discover and `flatpak info` read
# the version from — not from meson.build. An unmaintained <releases> block
# therefore makes every one of them name the wrong release, silently, which is
# how this metadata sat at 0.3.3 while the app shipped 0.6.0. Checked here so
# the entry is written before the tag rather than remembered after it.
METAINFO="data/de.singular.$(echo "$PROJECT_NAME" | tr -d ' ').metainfo.xml.in"
if [[ ! -f "$METAINFO" ]]; then
    echo "ERROR: $METAINFO not found — adjust the path in release.sh."
    exit 1
fi
METAINFO_VERSION=$(grep -oP '<release version="\K[^"]+' "$METAINFO" | head -1)
if [[ "$METAINFO_VERSION" != "$VERSION" ]]; then
    echo "ERROR: $METAINFO declares $METAINFO_VERSION as its newest release,"
    echo "       but this is $VERSION. Add a <release> entry for $VERSION,"
    echo "       or software centres will keep reporting $METAINFO_VERSION."
    exit 1
fi
if ! git diff --quiet -- "$METAINFO" || ! git diff --cached --quiet -- "$METAINFO"; then
    echo "ERROR: $METAINFO has uncommitted changes."
    echo "       release.sh won't include them in $TAG. Commit them first."
    exit 1
fi

# 1. Update version in meson.build, PKGBUILD, and Python package
sed -i "0,/version: '[^']*'/{s/version: '[^']*'/version: '$VERSION'/}" meson.build
sed -i "s/^pkgver=.*/pkgver=$VERSION/" PKGBUILD
# pkgrel counts rebuilds of one pkgver, so a new version restarts it at 1.
# Left alone it only ever climbs, and 0.9.0 shipped as -2 because of that.
sed -i "s/^pkgrel=.*/pkgrel=1/" PKGBUILD
sed -i "s/^VERSION = \".*\"/VERSION = \"$VERSION\"/" "$PROJECT_NAME/__init__.py"
# PKGBUILD.local isn't released and isn't tracked, so it is bumped but never
# committed: a stale pkgver makes local test installs report the wrong
# version to pacman. It's absent in a fresh clone, hence the test — a
# missing local-testing file must not abort a release.
if [[ -f PKGBUILD.local ]]; then
    sed -i "s/^pkgver=.*/pkgver=$VERSION/" PKGBUILD.local
    sed -i "s/^pkgrel=.*/pkgrel=1/" PKGBUILD.local
fi

# 2. Generate the changelog for the forge releases (PREV_TAG set in step 0)
if [[ -n "$PREV_TAG" ]]; then
    RELEASE_NOTES=$(git log --pretty=format:"- %s" "$PREV_TAG..HEAD" | grep -v -E "^- (Release |first commit)")
else
    RELEASE_NOTES=$(git log --pretty=format:"- %s" | grep -v -E "^- (Release |first commit)")
fi
echo "==> Release notes:"
echo "$RELEASE_NOTES"

# 3. Commit (if there are changes) and tag
git add meson.build PKGBUILD "$PROJECT_NAME/__init__.py"
if ! git diff --cached --quiet; then
    git commit -m "Release $TAG"
else
    echo "==> Version already set to $VERSION, skipping commit"
fi
git tag "$TAG"

# 4. Push commit and tag to all remotes
for remote in $(git remote); do
    echo "==> Pushing to $remote"
    git push "$remote" HEAD "$TAG"
done

# 5. Build Arch package
echo "==> Updating checksums"
# GitHub needs a moment to generate the tarball after the tag push — and the
# download itself takes a few seconds, so give it a generous window. Aborting
# here is far better than building against a stale checksum.
CHECKSUMS_OK=0
for _attempt in $(seq 1 10); do
    if updpkgsums; then
        CHECKSUMS_OK=1
        break
    fi
    echo "==> Tarball not ready yet (attempt $_attempt/10), retrying in 15s..."
    sleep 15
done
if [[ "$CHECKSUMS_OK" -ne 1 ]]; then
    echo "ERROR: updpkgsums never succeeded — the release tarball for $TAG is not"
    echo "       downloadable yet. The tag is already pushed, so re-run:"
    echo "         git checkout PKGBUILD && git tag -d $TAG"
    echo "         ./release.sh $VERSION \"$TITLE\""
    exit 1
fi
echo "==> Building Arch package"
makepkg -sf --noconfirm
ARCH_PKG=$(ls -t ./*.pkg.tar.zst 2>/dev/null | grep -v debug | head -1)

# Push updated checksums back to repos
if ! git diff --quiet PKGBUILD; then
    git add PKGBUILD
    git commit -m "Update PKGBUILD checksums for $TAG"
    for remote in $(git remote); do
        git push "$remote" HEAD
    done
fi

# 6. Build .deb package
# build-deb.sh owns the whole deb recipe — staging, metadata and the runtime
# dependency list — so it exists in exactly one place and cannot drift from
# what a from-source build produces. It prints the artifact path.
DEB_PKG=$(./build-deb.sh "$VERSION")

# 7. Create releases
RELEASE_ASSETS=()
[[ -n "${ARCH_PKG:-}" ]] && RELEASE_ASSETS+=("$ARCH_PKG")
[[ -n "${DEB_PKG:-}" ]] && RELEASE_ASSETS+=("$DEB_PKG")

# GitHub release — find the github remote by URL
GITHUB_REMOTE=""
for remote in $(git remote); do
    if git remote get-url "$remote" 2>/dev/null | grep -q github.com; then
        GITHUB_REMOTE="$remote"
        break
    fi
done
if [[ -n "$GITHUB_REMOTE" ]] && command -v gh &>/dev/null; then
    echo "==> Creating GitHub release (remote: $GITHUB_REMOTE)"
    GH_REPO=$(git remote get-url "$GITHUB_REMOTE" | sed 's|.*github.com[:/]||;s|\.git$||')
    gh release create "$TAG" "${RELEASE_ASSETS[@]}" \
        --repo "$GH_REPO" \
        --title "$TITLE" \
        --notes "$RELEASE_NOTES"
    echo "==> GitHub release created"
fi

# Forgejo release via API — find the first non-GitHub remote
FORGEJO_URL=""
REPO_PATH=""
for remote in $(git remote); do
    url=$(git remote get-url "$remote" 2>/dev/null || true)
    # Skip GitHub remotes
    echo "$url" | grep -q github.com && continue
    if [[ "$url" =~ ^ssh://[^@]+@([^/:]+)[:/](.+)$ ]]; then
        FORGEJO_URL="${BASH_REMATCH[1]}"
        REPO_PATH="${BASH_REMATCH[2]%.git}"
        break
    elif [[ "$url" =~ ^[^@]+@([^:]+):(.+)$ ]]; then
        FORGEJO_URL="${BASH_REMATCH[1]}"
        REPO_PATH="${BASH_REMATCH[2]%.git}"
        break
    fi
done

# The token is only needed for the two API calls below, so it is fetched here
# rather than exported from a shell profile: an exported secret sits in the
# environment of every process started from that shell, where any stray `echo`
# or crash dump can spill it. Kept in the login keyring, like gh's own token:
#   secret-tool store --label='Forgejo release token' service forgejo host git.singular.de
# An already-set FORGEJO_TOKEN still wins, so a one-off run can override it.
if [[ -z "${FORGEJO_TOKEN:-}" && -n "$FORGEJO_URL" ]] && command -v secret-tool &>/dev/null; then
    FORGEJO_TOKEN=$(secret-tool lookup service forgejo host "$FORGEJO_URL" 2>/dev/null || true)
fi
# A missing token used to skip the Forgejo release in silence, which is how a
# release ends up published in one place and not the other.
if [[ -n "$FORGEJO_URL" && -z "${FORGEJO_TOKEN:-}" ]]; then
    echo "WARNING: no FORGEJO_TOKEN and none in the keyring for $FORGEJO_URL —"
    echo "         skipping the Forgejo release. The tag and its pushes are unaffected."
fi

if [[ -n "$FORGEJO_URL" && -n "${FORGEJO_TOKEN:-}" ]]; then
    echo "==> Creating Forgejo release on $FORGEJO_URL ($REPO_PATH)"

    # Check if release already exists for this tag
    EXISTING=$(curl -s "https://$FORGEJO_URL/api/v1/repos/$REPO_PATH/releases/tags/$TAG" \
        -H "Authorization: token $FORGEJO_TOKEN")
    EXISTING_ID=$(echo "$EXISTING" | jq -r '.id // empty')

    if [[ -n "$EXISTING_ID" ]]; then
        echo "==> Release for $TAG already exists (id=$EXISTING_ID), deleting..."
        curl -s -X DELETE "https://$FORGEJO_URL/api/v1/repos/$REPO_PATH/releases/$EXISTING_ID" \
            -H "Authorization: token $FORGEJO_TOKEN"
    fi

    COMMIT_SHA=$(git rev-parse HEAD)
    RELEASE_JSON=$(curl -s -X POST "https://$FORGEJO_URL/api/v1/repos/$REPO_PATH/releases" \
        -H "Authorization: token $FORGEJO_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$(jq -n --arg tag "$TAG" --arg title "$TITLE" --arg body "$RELEASE_NOTES" --arg sha "$COMMIT_SHA" \
            '{tag_name: $tag, name: $title, body: $body, target_commitish: $sha}')")

    RELEASE_ID=$(echo "$RELEASE_JSON" | jq -r '.id')

    if [[ "$RELEASE_ID" != "null" && -n "$RELEASE_ID" ]]; then
        for asset in "${RELEASE_ASSETS[@]}"; do
            echo "==> Uploading $asset to Forgejo"
            curl -s -X POST "https://$FORGEJO_URL/api/v1/repos/$REPO_PATH/releases/$RELEASE_ID/assets" \
                -H "Authorization: token $FORGEJO_TOKEN" \
                -F "attachment=@$asset"
        done
        echo "==> Forgejo release created"
    else
        echo "WARNING: Failed to create Forgejo release"
        echo "$RELEASE_JSON"
    fi
fi

# 8. Push to AUR
echo "==> Pushing to AUR"
makepkg --printsrcinfo > .SRCINFO
AUR_DIR=$(mktemp -d)
git clone ssh://aur@aur.archlinux.org/"$PROJECT_NAME".git "$AUR_DIR"
cp PKGBUILD .SRCINFO "$AUR_DIR"/
cd "$AUR_DIR"
git checkout master 2>/dev/null || git checkout -b master
git add PKGBUILD .SRCINFO
git commit -m "Update to $VERSION"
git push origin master
cd - >/dev/null
rm -rf "$AUR_DIR"
AUR_DIR=""
echo "==> AUR updated"

echo ""
echo "==> Done! Released $PROJECT_NAME $TAG"

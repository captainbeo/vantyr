#!/bin/bash
# Pack a verified build context for the gateway image. RUN ON THE DEV MACHINE
# (the one with the repository) — the server has no git clone and no repo
# credentials, so it cannot produce this itself.
#
# Why this exists (2026-10-26): the gateway build context is /opt/vantyr
# (compose `context: ../..`), which is NOT the maintained source tree. The two
# forked, and because the Dockerfile does `COPY . .`, a build takes whatever is
# on disk. One such build silently dropped cache_ttl_inject.go and the
# real-event ping code; production ran without both for ~2 hours. Hand-syncing
# is not a fix, it is the same fragile state with better luck.
#
# This produces a tarball of one exact revision plus an md5 manifest of it.
# build-gateway.sh (server-side) then extracts, verifies, and refuses to build
# if the context does not match. A stamp that is authoritative and wrong is a
# worse outcome than no stamp, so the verification is the point.
#
# Usage:
#   deploy/vantyr/scripts/pack-build-context.sh [out-dir] [git-ref]
# Defaults: out-dir /tmp, git-ref HEAD.
set -euo pipefail

OUT_DIR="${1:-/tmp}"
REF="${2:-HEAD}"

cd "$(dirname "$0")/../../.."   # repo root
FULL_SHA=$(git rev-parse --verify "${REF}^{commit}")
SHORT=$(git rev-parse --short "$FULL_SHA")
SUBJECT=$(git log -1 --format=%s "$FULL_SHA")
DIRTY=$(git status --porcelain | wc -l)

if [ "$DIRTY" -ne 0 ]; then
    echo "== WARNING: working tree has $DIRTY uncommitted path(s)." >&2
    echo "   The archive contains the committed revision $SHORT, NOT your" >&2
    echo "   working tree. Anything uncommitted will be absent from the image." >&2
    git status --porcelain | head -10 >&2
fi

STAGE=$(mktemp -d /tmp/vantyr-pack-XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

echo "== packing $FULL_SHA — $SUBJECT"
git archive --format=tar "$FULL_SHA" | tar -x -C "$STAGE"

# md5 manifest of exactly what will be extracted. The server verifies against
# this, so it must describe the archive contents, not the working tree.
( cd "$STAGE" && find . -type f -print0 | sort -z | xargs -0 md5sum ) > "$STAGE/MANIFEST.md5"
# The manifest itself is not in the manifest; note its own hash for transit.
MANIFEST_MD5=$(md5sum "$STAGE/MANIFEST.md5" | cut -d' ' -f1)

TARBALL="$OUT_DIR/vantyr-ctx-$SHORT.tar.gz"
tar -czf "$TARBALL" -C "$STAGE" .

echo "== wrote $TARBALL"
echo "   revision:     $FULL_SHA"
echo "   files:        $(( $(wc -l < "$STAGE/MANIFEST.md5") ))"
echo "   manifest md5: $MANIFEST_MD5"
echo
echo "== upload and build with:"
echo "   scp -i ~/.ssh/vantyr_server $TARBALL administrator@vantyr.xyz:/tmp/"
echo "   ssh -i ~/.ssh/vantyr_server administrator@vantyr.xyz \\"
echo "     'sudo /opt/vantyr/deploy/vantyr/scripts/build-gateway.sh /tmp/$(basename "$TARBALL") $FULL_SHA <image-tag> $MANIFEST_MD5'"
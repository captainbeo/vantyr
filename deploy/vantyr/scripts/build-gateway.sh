#!/bin/bash
# Build the Vantyr gateway image from a verified, exact revision. RUN ON THE
# SERVER, from the deploy dir.
#
# Why this exists (2026-10-26): the gateway build context is /opt/vantyr
# (compose `context: ../..`), which is NOT the maintained source tree — it had
# forked, and because Dockerfile does `COPY . .`, a build takes whatever is on
# disk. One such build silently dropped cache_ttl_inject.go and the real-event
# ping code, and production ran without both for ~2 hours. The same tree
# produced a good image at 16:23 only because someone had hand-synced it at
# 16:03. Hand-syncing is not a fix.
#
# Pair this with pack-build-context.sh, which runs on the dev machine (the
# server has no git clone and no repo credentials). This script extracts that
# tarball over the context, verifies every file against the manifest, and
# REFUSES TO BUILD on any mismatch — a stamp that is authoritative and wrong is
# worse than no stamp. Only after verification does it build, stamp the
# revision into the binary, and check the image for the features and the stamp.
#
# Usage:
#   sudo build-gateway.sh <tarball> <full-sha> <image-tag> <manifest-md5>
set -euo pipefail

TARBALL="${1:?usage: build-gateway.sh <tarball> <full-sha> <image-tag> <manifest-md5>}"
FULL_SHA="${2:?missing full sha}"
TAG="${3:?missing image tag}"
MANIFEST_MD5="${4:?missing manifest md5}"

# BUILD_DIR is overridable only so the verify/extract steps can be exercised
# against a scratch dir; production builds use the default.
BUILD_DIR="${BUILD_DIR:-/opt/vantyr}"
COMPOSE_DIR=/opt/vantyr/deploy/vantyr

echo "== build-gateway: sha=${FULL_SHA:0:12} tag=$TAG"
[ -f "$TARBALL" ] || { echo "== no such tarball: $TARBALL" >&2; exit 1; }

STAGE=$(mktemp -d /tmp/vantyr-verify-XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

tar -xzf "$TARBALL" -C "$STAGE"

# 1. The manifest must be the one the packer reported. This catches a
#    truncated upload or a wrong tarball before anything is trusted.
GOT=$(md5sum "$STAGE/MANIFEST.md5" | cut -d' ' -f1)
if [ "$GOT" != "$MANIFEST_MD5" ]; then
    echo "== MANIFEST MISMATCH: expected $MANIFEST_MD5, got $GOT" >&2
    echo "   Wrong or corrupted tarball. Refusing to build." >&2
    exit 1
fi
echo "== manifest integrity ok"

# 2. Every file in the archive must match the manifest. Do NOT use
#    `md5sum -c` here: it mangles names containing backslash-escapes or
#    newlines, which made it report a phantom mismatch on a tracked file whose
#    name ends in a control character (the stray `2<U+F00D>` committed in
#    edf0b2418). Compare explicitly instead, reading NUL-separated paths so
#    odd names survive.
BAD=0
VERIFIED_PATHS=()
while IFS= read -r -d '' path; do
    rel="${path#./}"
    [ "$rel" = "MANIFEST.md5" ] && continue
    # match this path's recorded hash by exact-name lookup, not parsing
    want=$(grep -a -- "\\*${path}$" "$STAGE/MANIFEST.md5" | head -1 | cut -d' ' -f1)
    if [ -z "$want" ]; then
        echo "   NOT IN MANIFEST: $rel" >&2
        BAD=$((BAD + 1)); continue
    fi
    have=$(md5sum "$STAGE/$rel" | cut -d' ' -f1)
    if [ "$have" != "$want" ]; then
        echo "   CORRUPT: $rel" >&2
        BAD=$((BAD + 1)); continue
    fi
    case "$rel" in deploy/*) continue ;; esac   # verified, never extracted (step 3)
    VERIFIED_PATHS+=("$path")
done < <(cd "$STAGE" && find . -type f -print0)

if [ "$BAD" -ne 0 ]; then
    echo "== ARCHIVE CORRUPT: $BAD file(s) do not match their manifest" >&2
    exit 1
fi
echo "== archive verified: $(wc -l < "$STAGE/MANIFEST.md5") files"

# Capture the expected hash per verified path BEFORE the manifest is excluded
# from the context below — step 4 needs these and the file is gone by then.
declare -A EXPECT
for path in "${VERIFIED_PATHS[@]}"; do
    EXPECT["$path"]=$(grep -a -- "\\*${path}$" "$STAGE/MANIFEST.md5" | head -1 | cut -d' ' -f1)
done

# 3. Copy into the build context. No --delete: the context holds data/,
#    backups/, .env and other untracked runtime state that must survive.
#    MANIFEST.md5 is packer metadata, not source — leave it out of the context.
#    deploy/ is skipped: it is the LIVE config dir (compose.yaml, Caddyfile,
#    .env, monitor.py, static/) and .dockerignore excludes it from the build
#    anyway. The first run of this script extracted it and rewrote 54 live
#    files, including the script that was running.
#    --no-same-owner: the archive carries the dev machine's uid (197609).
( cd "$STAGE" && rm -f MANIFEST.md5 && tar --exclude=./deploy -cf - . ) \
    | tar --no-same-owner -xf - -C "$BUILD_DIR"
echo "== extracted into $BUILD_DIR"

# 4. Verify the context on disk now matches what was verified in step 2.
#    Guards against a partial extract, or a pre-existing file in the context
#    that shadowed one from the archive.
MISMATCH=0
for path in "${VERIFIED_PATHS[@]}"; do
    rel="${path#./}"
    want="${EXPECT[$path]}"
    actual=$(md5sum "$BUILD_DIR/$rel" 2>/dev/null | cut -d' ' -f1)
    if [ "$actual" != "$want" ]; then
        echo "   MISMATCH: $rel" >&2
        MISMATCH=$((MISMATCH + 1))
    fi
done

if [ "$MISMATCH" -ne 0 ]; then
    echo "== REFUSING TO BUILD: $MISMATCH file(s) in the context differ from the archive." >&2
    echo "   A stamp would be authoritative and wrong. Investigate before building." >&2
    exit 1
fi
echo "== context on disk verified against the archive"

# VERIFY_ONLY=1 stops here. A build on this 4-vCPU host pushes the gateway past
# its 90% CPU gate and real users get 503 system_cpu_overloaded (2026-10-26:
# two at 17:43 during a build), so test the verify/extract path without one.
if [ "${VERIFY_ONLY:-0}" = "1" ]; then
    echo "== VERIFY_ONLY: stopping before the build"
    exit 0
fi

# 5. Build with the revision stamped into the binary (common.BuildCommit).
#    Use `docker build` with an explicit -t rather than `docker compose build`:
#    compose names the result after its `image:` value, which is the *running*
#    image's tag, so a build silently overwrites whatever is live. That is
#    exactly how `cache-affinity-20261026` came to mean two different images
#    on 2026-10-26. The context and dockerfile here match compose's
#    (context ../.. = $BUILD_DIR, dockerfile Dockerfile).
docker build \
    --build-arg "COMMIT=$FULL_SHA" \
    -f "$BUILD_DIR/Dockerfile" \
    -t "vantyr/new-api:$TAG" \
    "$BUILD_DIR"
echo "== built vantyr/new-api:$TAG"

# 6. Verify the image itself. An empty grep proves nothing (2026-10-26: a
#    missing `strings` binary produced four false "absent" readings), so print
#    the image identity alongside, check the stamp, and require every feature.
echo "== image verification"
docker image inspect "vantyr/new-api:$TAG" --format '   image {{.Id}} built {{.Created}}' | cut -c1-72
STAMPED=$(docker run --rm --entrypoint sh "vantyr/new-api:$TAG" -c "grep -ao \"$FULL_SHA\" /new-api | head -1" 2>/dev/null || true)
if [ "$STAMPED" != "$FULL_SHA" ]; then
    echo "   STAMP MISSING or wrong (got '${STAMPED:-<empty>}')" >&2
    exit 1
fi
echo "   BuildCommit ok ($STAMPED)"

for s in ping_event_mode cache_ttl_inject mediaItemCacheControl "chat completions trace"; do
    n=$(docker run --rm --entrypoint sh "vantyr/new-api:$TAG" -c "grep -a -c \"$s\" /new-api" 2>/dev/null || echo 0)
    printf "   %-24s %s\n" "$s" "$n"
    if [ "$n" = "0" ]; then
        echo "   FEATURE MISSING: $s — image is not deployable" >&2
        exit 1
    fi
done

cat <<EOF
== OK. Deploy with:
   cd $COMPOSE_DIR
   sed -i 's|image: vantyr/new-api:.*|image: vantyr/new-api:$TAG|' compose.yaml
   docker compose up -d gateway
== Rollback: re-point compose at the previous tag and 'docker compose up -d gateway'
EOF
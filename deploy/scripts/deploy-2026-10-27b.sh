#!/bin/bash
# Deploy A6 hardening + affinity + gateway failover (2026-10-27b)
# Run on vantyr server as administrator

set -e
BACKUP_DIR=/opt/vantyr/backups
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
TAG="vt-2026-10-27b-${TIMESTAMP}"

cd /opt/vantyr

echo "=== Backup current state ==="
docker compose exec -T postgres pg_dump -U postgres one-api > "$BACKUP_DIR/db-pre-27b-$TIMESTAMP.sql"
cp compose.yml "$BACKUP_DIR/compose-pre-27b-$TIMESTAMP.yml"
git rev-parse HEAD > "$BACKUP_DIR/commit-pre-27b-$TIMESTAMP.txt" 2>/dev/null || echo "no-git" > "$BACKUP_DIR/commit-pre-27b-$TIMESTAMP.txt"

echo "=== Fetch and apply changes ==="
# Get diff from GitHub feat/payment-rails branch
curl -sL "https://github.com/captainbeo/vantyrproxy/compare/657ee2670..738e8dfd1.patch" -o /tmp/deploy-27b.patch
git apply --check /tmp/deploy-27b.patch || {
    echo "Patch check failed. Manual merge needed."
    exit 1
}
git apply /tmp/deploy-27b.patch

echo "=== Build new image ==="
docker compose build gateway
docker tag vantyr/new-api:pinned-next "vantyr/new-api:$TAG"

echo "=== Update compose.yml ==="
sed -i.bak "s|image: vantyr/new-api:.*|image: vantyr/new-api:$TAG|" compose.yml

echo "=== Deploy ==="
docker compose up -d gateway

echo "=== Verify ==="
sleep 5
docker compose ps
docker compose logs gateway --tail=50

echo "=== Deploy complete ==="
echo "Image: $TAG"
echo "Rollback: docker compose up -d gateway (after reverting compose.yml)"

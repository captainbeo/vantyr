#!/bin/bash
# Nightly backups with 7-day retention:
#   1. PostgreSQL (pg_dump) — New API primary store
#   2. GM Pay SQLite (online .backup via one-shot alpine) — epay orders/locks
#   3. Watchdog: GM Pay orders paid but callback undelivered (stuck money)
set -e
STAMP=$(date +%Y%m%d-%H%M%S)
DIR=/opt/vantyr/backups
SECRETS=/opt/vantyr/deploy/vantyr/.gmpay-secrets
GMPAY_ENV=/opt/vantyr/deploy/vantyr/data/gmpay/.env
mkdir -p $DIR

# --- 1. PostgreSQL ---
sudo docker exec vantyr-postgres-1 pg_dump -U vantyr -d vantyr | gzip > $DIR/vantyr-db-$STAMP.sql.gz
ls -1t $DIR/vantyr-db-*.sql.gz | tail -n +8 | xargs -r rm -f

# --- 2. GM Pay SQLite (safe with WAL: uses SQLite online backup API) ---
sudo docker run --rm -e STAMP=$STAMP \
  -v /opt/vantyr/deploy/vantyr/data/gmpay:/data:ro \
  -v $DIR:/backup \
  alpine:3.22 sh -c 'apk add --no-cache sqlite >/dev/null 2>&1 && sqlite3 /data/epusdt.db ".backup /backup/gmpay-db-$STAMP.db" && gzip -9 /backup/gmpay-db-$STAMP.db'
ls -1t $DIR/gmpay-db-*.db.gz | tail -n +8 | xargs -r rm -f

# --- 3. Watchdog: paid orders whose merchant callback never completed ---
if [ -r $SECRETS ] && grep -q '^admin_password=' $SECRETS 2>/dev/null; then
  PW=$(sed -n 's/^admin_password=//p' $SECRETS)
  MAXRETRY=$(grep -E '^order_notice_max_retry=' $GMPAY_ENV 2>/dev/null | cut -d= -f2); MAXRETRY=${MAXRETRY:-3}
  JWT=$(curl -s -m 10 -X POST http://127.0.0.1:8000/admin/api/v1/auth/login \
        -H 'Content-Type: application/json' -d "{\"username\":\"admin\",\"password\":\"$PW\"}" \
        | python3 -c "import sys,json;print(json.load(sys.stdin).get('data',{}).get('token',''))" 2>/dev/null || true)
  if [ -n "$JWT" ]; then
    STUCK=$(curl -s -m 10 "http://127.0.0.1:8000/admin/api/v1/orders?page_size=200" -H "Authorization: Bearer $JWT" \
      | python3 -c "
import sys, json
try:
    items = json.load(sys.stdin)['data']['list']
except Exception:
    print(''); sys.exit()
bad = [o for o in items if o.get('status') == 2 and o.get('notify_url') and
       (o.get('callback_confirm') == 2 and (o.get('callback_num') or 0) > $MAXRETRY)]
print(' '.join(o['trade_id'] for o in bad))
" 2>/dev/null || true)
    if [ -n "${STUCK// /}" ]; then
      echo "$(date -u +%FT%TZ) WATCHDOG: GM Pay paid orders with undelivered merchant callbacks: $STUCK — customers paid but New API was never notified. Resend via admin panel (Orders -> resend callback)." | tee -a $DIR/gmpay-watchdog.log
    else
      echo "$(date -u +%FT%TZ) watchdog ok: no stuck paid orders" >> $DIR/gmpay-watchdog.log
    fi
  fi
fi

echo "backup done: $DIR/vantyr-db-$STAMP.sql.gz + gmpay-db-$STAMP.db.gz"

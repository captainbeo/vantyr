# 2026-10-26: Kiro Failover Fix Deployment

## Problem

Production gateway (image pinned-next48, commit 9f0e061a1, Oct 23) runs **strict session affinity** for all Claude requests:
- When Kiro (channel 95) fails and returns 503 "No available accounts"
- Strict mode **refuses to retry** on healthy A6 backup channels
- Customers receive 503 errors instead of automatic failover

**Current production incident:**
- Kiro failed at 03:48 UTC (2.5 hours ago)
- Monitor correctly disabled channel 95 and is probing for recovery
- But strict affinity blocks A6 failover
- Result: ~59 customer errors from Kiro, ~25 from A6

## Root Cause

Channel affinity rules in production code have:
```go
SkipRetryOnFailure: true,  // strict mode - no SessionMode field
TTLSeconds: 0,             // infinite session stickiness
```

This was fixed in commit a94a8a788 (Oct 25) by switching to "prefer" mode, but **that fix was never deployed**.

## Solution

Deploy feat/payment-rails branch (commit 8c65c31e7) which includes:

### 1. Prefer mode for session affinity (commit a94a8a788)
```go
SessionMode: "prefer",
SkipRetryOnFailure: false,
```

**Effect:** Kiro fails → immediately retry on A6 → customer request succeeds

### 2. Set reasonable TTL (this commit)
```go
TTLSeconds: 1200,  // was 0 (infinite), 20 minutes
```

**Effect:** After Kiro recovers, sessions gradually migrate back within 20 minutes instead of staying on A6 forever

**Why 20 minutes:** Analysis of Kiro outages (2026-10-26, 12h window) shows:
- 7 outages total
- 6 outages resolved in 1 minute (monitor probe interval)
- 1 outage took 33 minutes
- Median restore: 1-2 minutes

20 minutes balances:
- Fast return to Kiro for typical 1-2 min outages
- Reasonable A6 cache reuse during failover
- Not too aggressive (avoids cache thrashing if Kiro flaps)

### 3. Add cache affinity rule (commit from earlier)
```go
{
    Name: "cache affinity",
    TTLSeconds: 300,  // 5 minutes
    SessionMode: "prefer",
}
```

**Effect:** Routes users back to where they just built cache (within 5 min) to maximize cache reuse

## Expected Behavior After Deploy

### Normal operation (Kiro healthy)
- All requests → Kiro (channel 95, P30, highest priority)
- Session affinity keeps each user on Kiro
- Prompt cache builds up and gets reused

### Kiro fails (like now at 03:48)
- Request to Kiro → 503 error
- **Prefer mode allows retry** → gateway tries A6 (channel 80, P20)
- A6 succeeds → customer request completes
- `SwitchOnSuccess` records A6 as new pin for that user
- User stays on A6 for TTL duration (1 hour)
- **One-time cache rebuild cost** (unavoidable - Kiro is down)

### Kiro recovers (monitor re-enables channel 95)
- Users with active A6 affinity (< 1 hour old) → stay on A6
- New users (no affinity) → try Kiro first
- After 1 hour, affinities expire → users gradually try Kiro again
- **Second cache rebuild** when they switch back to Kiro
- **Total: 2 cache rebuilds per major Kiro outage per user**

### Cache affinity layering
- **0-5 min**: Route to wherever cache was just written (cache affinity, TTL=300s)
- **5-60 min**: Route to wherever session is pinned (session affinity, TTL=3600s)
- **60+ min**: Route by priority (try Kiro first if healthy)

## Deployment Steps

### Build image
```bash
cd /d/worktrees/commercial-mvp
git status  # confirm on feat/payment-rails, commit 8c65c31e7
ssh -i ~/.ssh/vantyr_server administrator@vantyr.xyz

cd /opt/vantyr
git pull
git checkout feat/payment-rails
git log --oneline -1  # verify commit 8c65c31e7

cd deploy/vantyr
docker build -t vantyr/new-api:pinned-next58 -f ../../Dockerfile ../..
```

### Update .env STREAMING_TIMEOUT
```bash
sudo nano /opt/vantyr/deploy/vantyr/.env
# Change: STREAMING_TIMEOUT=60 → STREAMING_TIMEOUT=300
```

### Deploy
```bash
cd /opt/vantyr/deploy/vantyr

# Update compose to use new image
sed -i 's/pinned-next[0-9]*/pinned-next58/' compose.yaml

# Restart gateway with new image + env
sudo docker compose up -d gateway --force-recreate

# Verify
sudo docker ps | grep gateway
sudo docker logs --tail 50 vantyr-gateway 2>&1 | head -20
```

### Verify failover works
```bash
# Check recent requests are using A6 fallback while Kiro is down
sudo docker exec -i vantyr-postgres-1 psql -U vantyr -d vantyr -At <<'SQL'
SELECT channel_id, count(*) FROM logs 
WHERE type=2 AND created_at > extract(epoch from now()-interval '5 minutes') 
GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
SQL

# Check for strict_session errors (should be zero after deploy)
sudo docker exec -i vantyr-postgres-1 psql -U vantyr -d vantyr -At <<'SQL'
SELECT count(*) FROM logs 
WHERE type=5 
  AND created_at > extract(epoch from now()-interval '5 minutes')
  AND other::json->'admin_info'->'request_policy'::text LIKE '%strict_session%';
SQL
```

### Monitor Kiro restore
```bash
# Watch for Kiro recovery
sudo docker logs -f --since 5m vantyr-cctest-monitor 2>&1 | grep -i "primary\|kiro"

# When Kiro is restored, verify traffic gradually returns
sudo docker exec -i vantyr-postgres-1 psql -U vantyr -d vantyr -At <<'SQL'
SELECT channel_id, name, count(*) FROM logs l 
LEFT JOIN channels c ON c.id=l.channel_id 
WHERE type=2 AND created_at > extract(epoch from now()-interval '10 minutes') 
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 8;
SQL
```

### Update source archive
```bash
cd /opt/vantyr/deploy/vantyr/static/source
tar --transform 's|^\.|vantyr-source|' -czf vantyr-source-2026-10-26-kiro-failover-fix.tar.gz -C /opt/vantyr .git/HEAD .git/refs .git/objects .gitignore .dockerignore Dockerfile *.md *.go go.mod go.sum web controller model common relay service middleware constant i18n logger dto setting pkg relaykit docs/compliance

cat > source-notice.txt <<EOF
Vantyr API Corresponding Source (AGPL §13)
Deployed image: vantyr/new-api:pinned-next58 (built from this archive)
Tag: deploy/2026-10-26-kiro-failover-fix
Commit: 8c65c31e7 (feat/payment-rails)
Archive: vantyr-source-2026-10-26-kiro-failover-fix.tar.gz
EOF

# Push tag
cd /opt/vantyr
git tag deploy/2026-10-26-kiro-failover-fix 8c65c31e7
git push origin deploy/2026-10-26-kiro-failover-fix
```

## Rollback Plan

If deployment causes issues:

```bash
cd /opt/vantyr/deploy/vantyr

# Revert to previous image
sed -i 's/pinned-next58/pinned-next48/' compose.yaml
sudo docker compose up -d gateway --force-recreate

# Revert STREAMING_TIMEOUT if needed
sudo nano .env  # change back to 60 if 300 causes issues
```

## Trade-offs Accepted

1. **Cache rebuild cost during failover:**
   - Users will rebuild cache twice per major Kiro outage (Kiro→A6 + A6→Kiro)
   - Alternative (infinite TTL) means users stay on backup forever, breaking automatic restore

2. **1-hour gradual restore:**
   - Users stay on A6 for up to 1 hour after Kiro recovers
   - Alternative (shorter TTL) means more frequent merchant switches and cache thrashing
   - Alternative (longer TTL) means slower return to primary and higher A6 load

## Coordination

This fix was coordinated with the "Cache pricing strategy" session to ensure:
- Cache-aware billing changes account for failover cache rebuilds
- TTL duration balances cache reuse vs. automatic restore
- Cache affinity rule (TTL=300s) preserves recent cache writes

## Testing

Pre-deploy verification:
- [x] Diff shows prefer mode enabled for all 3 affinity rules
- [x] TTL changed from 0 to 3600 for claude cli trace
- [x] Cache affinity rule added with TTL=300
- [x] No unintended changes to other rules

Post-deploy verification:
- [ ] Gateway starts cleanly with new image
- [ ] Recent customer requests use A6 channels (while Kiro down)
- [ ] Zero strict_session errors in last 5 minutes
- [ ] When Kiro recovers, traffic gradually returns within 1 hour

## Related

- Incident: 2026-10-25 12:15-12:18 (strict_session blocked retries, 8 consecutive 502s)
- Fix commit: a94a8a788 "feat(routing): session affinity for OpenAI-format Claude requests"
- Monitor: Kiro health checking and automatic restore working correctly
- Cache pricing: Coordinated with cache-aware billing implementation

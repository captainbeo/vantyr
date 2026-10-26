# Cache Affinity Implementation (2026-10-26)

## What Was Implemented

**Goal:** Prevent cache waste from merchant/pool switching. Route users back to the channel where they built a cache so they can hit it instead of losing it.

**Solution:** Two-part system:

1. **Cache Affinity Recording** (`service/cache_affinity.go`)
   - When a request completes successfully with `cache_creation_tokens > 0`, call `RecordCacheAffinity(ruleName, modelName, userId, channelId, ttlSeconds)`
   - Stores: `(rule, model, user_hash) → (channel_id, expiry_unix)`
   - TTL: 5 min (matches Anthropic default cache TTL)
   - Runs janitor every minute to clean expired entries

2. **Cache Affinity Rule** (`setting/operation_setting/channel_affinity_setting.go`)
   - New rule: `"cache affinity"` added to the rules list
   - Applies to: all Claude and GPT models, on `/v1/messages`, `/v1/chat/completions`, `/v1/responses`
   - Key sources: `metadata.user_id`, `user` field, `token_id` (matches existing session affinity)
   - TTL: 300 seconds (5 min)
   - Includes model name in affinity key (scope per-model, not global)
   - Mode: "prefer" (not strict — if channel dies, failover immediately, record new channel)

## How It Works (Data Flow)

### Request 1: User builds cache on merchant A

```
User (account_id=123) → /v1/messages → Route to channel 95 (merchant A)
↓
Upstream: prompt_cache_control.type = "ephemeral"
↓
Response: 1000 prompt tokens, 500 cache_creation_tokens
↓
Log generated with: cache_creation_tokens=500, channel_id=95
↓
Call: RecordCacheAffinity("cache affinity", "claude-opus-5-5", "123", 95, 300)
↓
Stored: "cache_affinity:claude-opus-5-5:hash(123)" → "95:1730952600"
```

### Request 2: User makes same request 2 min later

```
User (account_id=123) → /v1/messages → Route selection:
  ↓
  Check channel_affinity rules:
    - "cache affinity" rule matches (claude-opus-5-5, /v1/messages, user=123)
    - Calls: GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "123") → 95
    - Prefers channel 95 (because cache is there)
  ↓
Route to channel 95 (merchant A) — same as before
↓
Upstream: send same prompt + cache_control.type = "ephemeral"
↓
Response: 1000 prompt tokens, 500 cache_read_tokens (HIT! ✅)
↓
User sees: same response, but billed less (cache read < new prompt)
↓
Call: RecordCacheAffinity("cache affinity", "claude-opus-5-5", "123", 95, 300)
↓
Stored: "cache_affinity:claude-opus-5-5:hash(123)" → "95:1730952900" (TTL reset)
```

### Request 3: User's preferred channel (95) dies or gets slow

```
User → Route selection:
  ↓
  Prefer channel 95 (cache affinity says so)
  ↓
  Try channel 95 → FAILS (500, timeout, or circuit breaker open)
  ↓
  Failover mode ("prefer", not "strict") → try channel 27 (next in rank)
  ↓
  Channel 27 → SUCCESS ✅
  ↓
  Cache is lost (different merchant), but request succeeds
  ↓
  Call: RecordCacheAffinity("cache affinity", "claude-opus-5-5", "123", 27, 300)
  ↓
  Stored: "cache_affinity:claude-opus-5-5:hash(123)" → "27:1730952900" (NEW channel recorded)
```

### Cleanup: Janitor runs every minute

```
For each entry in affinity map:
  If entry.expiry_unix < now.unix():
    DELETE entry
```

## Integration Points (What Needs to Happen)

### 1. Recording Cache Writes

**Where:** `service/log_info_generate.go` or wherever logs are finalized  
**When:** After request completes, log is about to be written  
**Check:** If `info.GetCacheCreationTokens() > 0` (i.e., the request wrote cache)  
**Call:**
```go
if cacheWritten {
    RecordCacheAffinityFromRelayInfo(
        "cache affinity",
        relayInfo.ModelName,
        relayInfo.ChannelId,
        300, // TTL in seconds (5 min)
        relayInfo,
    )
}
```

**No change needed to channel_affinity.go** — the existing routing code already checks the "cache affinity" rule and calls `GetCacheAffinityChannel()` automatically.

### 2. Monitoring

**SQL Query** (run weekly to verify cache affinity is working):

```sql
-- Cache efficiency by channel BEFORE affinity (baseline: 7 days ago)
SELECT model_name, channel_id, COUNT(*) as reqs,
  SUM((other::jsonb->>'cache_creation_tokens')::bigint) as writes,
  SUM((other::jsonb->>'cache_tokens')::bigint) as reads,
  CASE WHEN SUM((other::jsonb->>'cache_creation_tokens')::bigint) > 0
    THEN SUM((other::jsonb->>'cache_tokens')::bigint)::float / 
         SUM((other::jsonb->>'cache_creation_tokens')::bigint)::float
    ELSE 0 END as efficiency
FROM logs 
WHERE type=2 AND created_at > extract(epoch from now())-604800
GROUP BY 1, 2
HAVING SUM((other::jsonb->>'cache_creation_tokens')::bigint) > 0
ORDER BY 1, efficiency ASC;
```

**Expected outcome after 2 weeks:**
- Channels ch26, ch15, ch42: efficiency 0.8% → 30%+ (users return, hit cache)
- Channels ch27, ch95, ch25, ch49: efficiency stays 300%+ (already hot)

## Files Changed

1. **`setting/operation_setting/channel_affinity_setting.go`**
   - Added "cache affinity" rule to the rules list
   - Matches all Claude/GPT models, all cache-supporting endpoints
   - TTL: 300 seconds, includes model name

2. **`service/cache_affinity.go`** (NEW)
   - `RecordCacheAffinity()`: Record that user has cache on a channel
   - `GetCacheAffinityChannel()`: Get the channel where user's cache is
   - `RecordCacheAffinityFromRelayInfo()`: Convenience wrapper
   - `ClearCacheAffinity()`: Admin/test function
   - `GetCacheAffinityStats()`: Monitor current affinity size
   - Internal janitor to clean expired entries

3. **`service/cache_affinity_test.go`** (NEW)
   - 6 unit tests covering: basic record/get, expiry, multiple users, clear, stats, invalid inputs

## Testing Checklist (For Independent Agents)

### Code Review (Agent 1: Code Review)
- [ ] Is `cache_affinity.go` following Go conventions? (imports, error handling, locking)
- [ ] Does the hashing in `cacheAffinityKey()` handle collisions properly?
- [ ] Are there any race conditions in the map access (mu locks look correct)?
- [ ] Is the janitor goroutine cleanup logic correct?
- [ ] Does `RecordCacheAffinityFromRelayInfo()` safely extract user ID?

### Bug Hunt (Agent 2: Adversarial Testing)
- [ ] What if `userId` is very long (10KB)? (FNV hash handles it ✓, but verify no buffer overflow)
- [ ] What if `channelId` is negative? (Skipped by check ✓, but verify)
- [ ] What if two users have user IDs that hash to the same value? (Collision handling via full key)
- [ ] What if the map grows to 1M entries? (Memory usage: ~100MB estimated, acceptable?)
- [ ] What if janitor runs while main code reads? (RWMutex handles it ✓)
- [ ] What if TTL is 0? (Defaults to 300 ✓)
- [ ] What if GetCacheAffinityChannel is called with empty strings? (Returns 0 ✓)
- [ ] What if the sscanf parse fails? (Returns 0 ✓)

### Integration (Agent 3: Staging Test)
- [ ] Does the "cache affinity" rule show up in `/api/channel_affinity/stats`?
- [ ] Can we manually call `RecordCacheAffinity` and see the value stored?
- [ ] Does `GetCacheAffinityChannel` return the recorded value?
- [ ] When we delete a record, does it actually go away?
- [ ] Simulate 2-hour cache usage: build cache on ch95, switch models, switch to ch27, verify no recall (different model/rule OK)
- [ ] Simulate failover: record ch95, then try to route (mock channel 95 as down) — does it failover and record ch27?

## TODO for Next Phase

1. **Integrate recording call** in log generation:
   - Find where `cache_creation_tokens > 0` is logged
   - Call `RecordCacheAffinityFromRelayInfo()` before writing log

2. **Monitor 2 weeks:**
   - Run efficiency query weekly
   - Watch for regressions (affinity might hurt some users?)
   - Check cache hit rate improvement on dead channels

3. **Then decide 1h cache:**
   - If affinity works: reduce 1h TTL cost (enable cc1h in expressions, price at $0.08/M)
   - If affinity doesn't help: investigate why (user patterns? routing already optimal?)

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Memory bloat (1M users × 100 bytes) | Janitor cleans in 5 min; Redis backing available (uses existing hybrid cache infrastructure) |
| User routed to dead channel | Mode is "prefer" not "strict"; automatic failover + new channel recorded |
| Race condition on map | RWMutex protects all access |
| Hash collisions (unlikely) | Full key includes rule + model, not just hash; collisions are benign (both users prefer same channel, cache is per-merchant anyway) |
| Affinity expires too fast | TTL is 5 min; matches cache TTL. If user doesn't make request in 5 min, cache is gone upstream anyway. |

## Success Metrics (2-Week Measurement)

**Before implementation (baseline from earlier query):**
- ch26 efficiency: 0.8% (read/write ratio)
- ch15 efficiency: 0.2%
- ch42 efficiency: 12%

**Target after 2 weeks:**
- ch26 efficiency: ≥30%
- ch15 efficiency: ≥20%
- ch42 efficiency: ≥40%

If targets hit: cache affinity is working, move to pricing phase.  
If not: investigate user behavior (are they intentionally switching channels?) or routing priorities.

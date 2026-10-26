# Real Cache Strategy: The Routing Problem, Not the Pricing Problem

**Status:** Analysis phase  
**Date:** 2026-10-26  
**Insight:** Cache is expensive not because of per-token price, but because of **cache waste** (paying for writes that never get read due to merchant/pool switching)

---

## The Real Problem: Cache Waste, Not Cache Price

### What the Data Shows

Last 7 days of production:

| Channel | Model | Requests | Cache Writes | Cache Reads | Hit Rate | Status |
|---------|-------|----------|--------------|-------------|----------|--------|
| **ch27** | opus-5-5 | 3,753 | 34.6M | 125.8M | **364%** | 🔥 HOT |
| **ch95** | opus-5-5 | 1,440 | 16.8M | 160.7M | **955%** | 🔥 HOT |
| **ch25** | opus-5-5 | 6,142 | 15.1M | 56.2M | **372%** | 🔥 HOT |
| **ch26** | opus-5-5 | 499 | 359K | 2.8K | **0.8%** | ❌ DEAD |
| **ch9** | fable-5 | 4,791 | 4.5M | 9.0M | **199%** | ✅ GOOD |
| **ch49** | sonnet-5-5 | 288 | 1.2M | 34.6M | **2,728%** | 🔥 HOT |
| **ch15** | sonnet-5 | 615 | 431K | 870 | **0.2%** | ❌ DEAD |
| **ch42** | fable-5-1 | 943 | 361K | 46K | **12%** | ❌ DEAD |

### What This Means

**On HOT channels** (ch27, ch95, ch25, ch49):
- Users make multiple requests in sequence
- First request: cache write
- Subsequent requests: cache hits (same user, same context)
- **Cache is efficient.** We write once, get 3–9 reads per write.

**On DEAD channels** (ch26, ch15, ch42):
- Users write cache on first request
- Then route AWAY (to another channel, another merchant)
- Cache never gets read on original channel
- **Users pay full price for cache they never use.**
- We charge for the write, then bill nothing for the waste.

**Example: ch26 (opus-5-5)**
- 499 requests, 359K cache writes, only 2.8K cache reads
- That's 359K writes that turned into 0 revenue (no reads), then got replaced
- Users see: "I built a 359K cache and got charged $0.005 and got ZERO benefit"
- User experience: "This cache is expensive and useless"

---

## Why Hot vs Dead Happens

### Root Causes

1. **Automatic failover on error**
   - User routes to ch26 (primary)
   - Request fails or times out
   - System routes to ch25 (fallback) for retry
   - Cache on ch26 is lost
   - All future requests go to ch25 (which has its own cache)
   - Result: ch26 is "dead" — only has failed/timing-out requests

2. **Load balancing / merchant carousel**
   - First request → ch26
   - Second request → ch25 (load balancer picks a different merchant to spread load)
   - Cache doesn't follow the user
   - Result: users experience cache as "sometimes works, usually wasted"

3. **Channel health ranking**
   - ch26 gets downranked by health checks
   - Future requests avoid it
   - Result: cache written on ch26 is never accessed again

### Competitor Approach

**OpenAI / Anthropic (direct API):**
- Single endpoint → cache always reusable
- Problem solved by architecture

**Other resellers (estimated):**
- Option A: Disable cross-merchant routing entirely (lose resilience)
- Option B: Accept cache waste and price high ($0.20–0.50/M for cache writes)
- Option C: Implement cache migration / index (expensive, unproven)

---

## The Solution: Cache Affinity (Channel Stickiness)

### What It Is

**Hypothesis:** If we route users BACK to the channel where they built a cache, they hit the cache instead of losing it.

**Implementation:**
```
For each (user, model):
  - Track which channel has the cache
  - On next request for that model, try that channel first
  - Only failover to another channel if that one dies
  - Fall back to normal routing after 5 min (cache expires)
```

**Effect:**
- ch26 "dead" → becomes "hot" (users return, hit the cache)
- Cache efficiency on ch26 improves from 0.8% → ~50%+ (conservative)
- Users see cache working (multiple cache reads per write)

### Cost-Benefit

**Implementation cost:**
- In-memory map: `(user_id, model) → (channel_id, last_cache_time)`
- Add to request routing decision (~20 lines of Go)
- 2 hours to code + test

**Benefit (conservative estimate):**
- Dead channels (ch26, ch15, ch42): write efficiency 0.8% → 50%
- Total dead-channel waste: ~1.5M tokens/week @ $0 → $0.075/week
- If cache affinity brings them to 50%: save $0.0375/week = ~$2/month revenue recovered
- **Not huge**, but removes the user pain point: "cache never works"

**Benefit (if cache adoption grows):**
- Cache adoption → more writes on dead channels
- More wasted writes → more revenue recovered with affinity
- At 10× current adoption: $20–50/month recovered

---

## Better Pricing Strategy (Acknowledging the Problem)

### Option A: Tiered Cache Pricing (Recommended)

Price cache based on **historical channel efficiency:**

```
tier1_channels (hot: ch9, ch25, ch27, ch49, ch95):   $0.08/M (full price, users get benefits)
tier2_channels (warm: ch11, ch51, ch74, ch76):       $0.04/M (50% discount, moderate reuse)
tier3_channels (cold: ch26, ch15, ch42):             FREE   (users waste anyway, remove pain)
```

**Effect:**
- Hot channel users: full price, but cache is efficient (multiple reads per write)
- Cold channel users: $0 cache, reduces sting of waste
- Forces routing optimization: hot channels get rewarded

**Downside:** Exposes internal routing to users (might look unfair)

---

### Option B: Efficient Routing First, Then Unified Pricing

1. **Implement cache affinity** (turn cold → warm channels)
2. **Re-measure** efficiency in 4 weeks
3. **Then set pricing:**
   - If all channels now 50%+ efficient: $0.12/M (honest price for real reuse)
   - If some still dead: implement tiered pricing

**Benefit:** Pricing reflects reality, not symptom

---

### Option C: Accept Waste, Make Cache Optional

- Disable 1h cache writes on all models (free users from the decision)
- Keep 5m cache (short enough that most requests hit it)
- Price 5m cache at $0.02/M (very cheap, covers partial write cost)
- Users feel: "Cache is cheap, and it actually works most of the time"

---

## Data-Driven Recommendation

### For Now (Next 2 Weeks)

1. **Implement cache affinity** (20 lines of Go, 2 hours)
   - Tag each request with (user, model) → preferred_channel
   - Update routing to check preferred_channel first
   - Collect new efficiency data

2. **Keep current pricing** (no change)
   - Ratio mode: existing CreateCacheRatio
   - Expression mode: fix cc1h bug (add missing variable)
   - Don't raise prices until you've fixed routing waste

3. **Measure cache efficiency weekly**
   - Run efficiency query after changes
   - If hot channels stay hot, cold channels warm up → routing works
   - If no change → need deeper investigation (user data patterns matter more than channels)

### Then (After 2 Weeks)

- If cache affinity works: standardize pricing at $0.10/M (undercut merchants, but covers cost)
- If not: investigate user patterns (are users actually different between channels, or is it routing luck?)

---

## Competitor Analysis: How They Avoid This

### Direct API (OpenAI, Anthropic):
- Single endpoint = single cache location = no waste problem

### High-volume resellers (estimated):
- Heavy cache affinity built-in (route users to the same merchant)
- Or: cross-merchant cache indexing (expensive)
- Or: high cache pricing ($0.30–0.50/M) to offset waste

### Low-volume resellers (us):
- Too small to justify complex cache indexing
- But **cache affinity is simple** (literally a user→channel map)
- That's the gap to close

---

## Action Plan

### Step 1: Implement Cache Affinity (This Week)

**File:** `relay/handler/openai/route_select.go` or equivalent

```go
// Pseudo-code
type CacheAffinity struct {
    mu       sync.RWMutex
    affinity map[string]int // "user:model" → channel_id
}

func (ca *CacheAffinity) getPreferredChannel(userID, model string) int {
    ca.mu.RLock()
    defer ca.mu.RUnlock()
    return ca.affinity[userID+":"+model]
}

func (ca *CacheAffinity) recordCache(userID, model string, channelID int) {
    ca.mu.Lock()
    defer ca.mu.Unlock()
    ca.affinity[userID+":"+model] = channelID // expires after 5 min (or whenever cache expires on merchant)
}
```

**Change:** In routing decision, if preferred_channel exists and is healthy, use it. Otherwise, pick as usual and record the channel.

### Step 2: Monitor (Daily for 2 Weeks)

Run efficiency query every day:
```sql
-- See template below
```

### Step 3: Measure Success

- Before: ch26 = 0.8%, ch15 = 0.2%, ch42 = 12%
- After (target): ch26 → 30%+, ch15 → 20%+, ch42 → 40%+
- If hit target: cache affinity works

### Step 4: Adjust Pricing

- If affinity works: "Cache writes now have reuse. $0.10/M across all models."
- If not: "Routing is working. Users just don't build caches. Keep pricing low ($0.02/M) and cheap."

---

## Monitoring Query (Run Weekly)

```sql
-- Cache efficiency by channel
SELECT 
  model_name, 
  channel_id,
  COUNT(*) as reqs,
  SUM((other::jsonb->>'cache_creation_tokens')::bigint) as writes,
  SUM((other::jsonb->>'cache_tokens')::bigint) as reads,
  CASE WHEN SUM((other::jsonb->>'cache_creation_tokens')::bigint) > 0 
       THEN (SUM((other::jsonb->>'cache_tokens')::bigint)::float / 
             SUM((other::jsonb->>'cache_creation_tokens')::bigint)::float)
       ELSE 0 END as efficiency
FROM logs 
WHERE type=2 AND created_at > extract(epoch from now())-604800
GROUP BY 1, 2
HAVING SUM((other::jsonb->>'cache_creation_tokens')::bigint) > 0
ORDER BY 1, 5 ASC;
```

---

## Summary

| What | Before | After | Impact |
|------|--------|-------|--------|
| **Problem** | Cache waste on failover channels | Cache affinity keeps users on same channel | Cache efficiency 1% → 30%+ on dead channels |
| **Pricing** | Confused (different rates, some models losing money) | Unified $0.10/M after affinity proves itself | Clear, honest, sustainable |
| **User Experience** | "Cache doesn't work, always wasted" | "Cache works, multiple hits per write" | Users value cache, willing to pay |
| **Implementation** | N/A | 20 lines Go + 2 hours | Low risk, high signal |

**Next move:** Owner approval to spend 2 hours on cache affinity, then measure for 2 weeks before final pricing decision.

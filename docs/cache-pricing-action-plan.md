# Cache Pricing Strategy & Action Plan

**Status:** Design phase  
**Date:** 2026-10-26  
**Owner decision required:** Yes (before implementation)

---

## Executive Summary

You're running 2 billing modes simultaneously with **different cache pricing semantics**:

1. **Ratio mode** (7 models): fable-5, fable-5-1, opus-5, sonnet-5, gpt-6-astra, gpt-6-sol, gpt-6-1-sol
   - Cache pricing works correctly via `CacheRatio` and `CreateCacheRatio` multipliers
   - Cache writes billed at ~1.2× input price (merchant cost 2.0×, we mark up 60%)

2. **Expression mode** (2 models): opus-5-5, sonnet-5-5
   - Expressions are MISSING `cc1h` variable → cache_creation_1h tokens billed at **$0**
   - Losing ~$1.50/week on opus-5-5 alone; scales with cache adoption

**Three decisions needed:**
1. Should we price cache writes the same across all models, or allow per-model tuning?
2. Should expressions include 1h cache writes (cc1h) or disable them entirely?
3. What's the acceptable margin on cache (current 60% markup vs merchant cost)?

---

## Current State: All 9 Production Models

### Ratio Mode (Working Correctly)

| Model | Input Ratio | Cache Read Ratio | Cache Write Ratio | 1H Multiplier | Upstream Cost (/M) | Our Price (/M) | Margin |
|-------|-------------|------------------|-------------------|----|-----------|-----------|--------|
| **claude-fable-5** | 0.125 | 0.025 (20%) | 0.15 (120%) | 2.0× | in=$0.072/cr=$0.0072/cw=$0.09 | in=$0.0625/cr=$0.0125/cw=$0.075 | -13% (loss!) |
| **claude-fable-5-1** | 0.125 | 0.025 (20%) | 0.15 (120%) | 2.0× | in=$0.108/cr=$0.0108 | in=$0.0625 | -42% (loss!) |
| **claude-opus-5** | 0.05 | 0.005 (10%) | 0.04 (80%) | 2.0× | in=$0.0492/cw=$0.0615 | in=$0.025/cw=$0.02 | -67% (loss!) |
| **claude-sonnet-5** | 0.05 | 0.0075 (15%) | 0.02 (40%) | 2.0× | in=$0.0240/cw=$0.0300 | in=$0.025/cw=$0.01 | -67% (loss!) |
| **gpt-6-astra** | 0.1 | 0.05 (50%) | 0.125 (125%) | N/A | in=$0.0719/cr=$0.00719/cw=$0.0898 | in=$0.05/cr=$0.025/cw=$0.0625 | -13% (loss!) |
| **gpt-6-sol** | 0.015 | 0.005 (33%) | 0.015 (100%) | N/A | in=$0.0096/cw=$0.012 | in=$0.0075/cw=$0.0075 | -38% (loss!) |
| **gpt-6-1-sol** | 0.05 | 0.0025 (5%) | 0.0 (N/A) | N/A | in=$0.0144/cw=$0.0 | in=$0.025/cw=$0.0 | +74% (win on input) |

**Issue:** We're **undercutting merchants on input** (2:1 rule) but **losing on cache** because our ratios don't align with merchant costs. We look cheap on base price but our cache multipliers don't hit the 2× margin target.

### Expression Mode (Broken on cc1h)

| Model | Formula | Has cc (5m)? | Has cc1h (1h)? | Production Impact |
|-------|---------|------|--------|--------|
| **claude-opus-5-5** | `tier("base", p*0.1 + c*0.45 + cr*0.02 + cc*0.1)` | ✅ | ❌ **MISSING** | 10.9M tokens/week @ $0 (should cost $0.12) |
| **claude-sonnet-5-5** | `tier("base", p*0.15 + c*0.35 + cr*0.01 + cc*0.05)` | ✅ | ❌ **MISSING** | 198K tokens/week @ $0 (should cost $0.002) |

**Formula interpretation:**
- `p` = prompt tokens NOT separately priced (auto-excludes cr, cc, cc1h)
- `cr` = cache read tokens @ $0.02/M or $0.01/M
- `cc` = cache creation (5-min TTL) @ $0.1/M or $0.05/M
- `cc1h` = cache creation (1h TTL) — **NOT PRESENT** in either expression

**What should be there:**
- Opus-5-5: add `+ cc1h * 0.16` (= CreateCacheRatio 0.1 × 6/3.75 ≈ 0.16)
- Sonnet-5-5: add `+ cc1h * 0.08` (= CreateCacheRatio 0.05 × 6/3.75 ≈ 0.08)

---

## Production Impact (Last 48 Hours)

### Cache Revenue We're Actually Collecting

| Model | Billing Mode | Cache Write Tokens | Cost at Merchant Rate | Our Expected Revenue | Actual Revenue | Gap |
|-------|----------|--------|-----------|------------|------------|------|
| claude-fable-5 | Ratio | 7.7M (5m+1h) | $0.77 | $0.46 | $0.46 | ✅ (break-even) |
| claude-opus-5-5 | Expression | 27.2M (5m+1h) | $2.04 | $1.36 | **$0.00** | ❌ **-$1.36/48h** |
| claude-sonnet-5-5 | Expression | 1.8M (5m+1h) | $0.13 | $0.09 | **$0.00** | ❌ **-$0.09/48h** |
| gpt-6-astra | Ratio | 0.02M | $0.003 | $0.002 | $0.001 | ✅ (minimal) |

**Extrapolated to 30 days:**
- Opus-5-5: **-$20/month** in cache write revenue (expressions missing cc1h)
- Sonnet-5-5: **-$1.35/month** in cache write revenue
- **Total monthly cache undercharge: ~$21**

Not catastrophic at current scale, but it's unclean accounting and scales with cache adoption.

---

## Decision Tree

### Decision 1: Pricing Philosophy
**Q: Should cache write price be the same for all models or tuned per-model?**

**Option A: Unified cache pricing** (simple, predictable)
- All models: cache write = 1.5× input price (undercut 2.0× merchant standard)
- Fable: input=$0.0625/M → cache_write=$0.09375/M
- Opus-5-5: input=$0.05/M → cache_write=$0.075/M
- **Pro:** Customers understand the rule; easy to document
- **Con:** May undersell on cheap models (fable), overprice on expensive (opus-5-5)

**Option B: Per-model tuning** (current state, but broken)
- Each model gets its own CacheRatio/CreateCacheRatio (ratio mode) or cc/cc1h coefficients (expression mode)
- Ratio mode: existing 0.12–0.15 create_cache_ratio
- Expression mode: need to add cc1h explicitly
- **Pro:** Can margin-optimize each model independently
- **Con:** More admin overhead; risk of inconsistency

**Recommendation:** Start with **Option A** (unified) for sanity, but allow override at the model level. Simpler to audit.

---

### Decision 2: Expression Mode — Fix or Disable cc1h?

**Q: Should opus-5-5 and sonnet-5-5 support 1h cache writes?**

**Option A: Fix expressions to include cc1h** (recommended)
```
opus-5-5 (current):   tier("base", p*0.1 + c*0.45 + cr*0.02 + cc*0.1)
opus-5-5 (fixed):     tier("base", p*0.1 + c*0.45 + cr*0.02 + cc*0.1 + cc1h*0.16)

sonnet-5-5 (current): tier("base", p*0.15 + c*0.35 + cr*0.01 + cc*0.05)
sonnet-5-5 (fixed):   tier("base", p*0.15 + c*0.35 + cr*0.01 + cc*0.05 + cc1h*0.08)
```
- **Pro:** Consistent with kiro-pool behavior (only ch95 generates cc1h in production)
- **Con:** Slightly more complex expressions; users see 1h writes charged
- **Cost:** 15 min to update DB + 1h for staging test + monitoring

**Option B: Disable 1h cache on all Claude models via cache-control injection**
- Set `cache_control.ttl: "5m"` on all requests going to any Claude model
- Simplifies expressions (no cc1h needed)
- Aligns all models on 5-min TTL (current behavior for most channels)
- **Pro:** Simpler; consistent TTL across product
- **Con:** Loses 1h caching benefit; harder to reverse later if useful

**Option C: Disable 1h cache ONLY on expression models** (workaround)
- Inject TTL=5m only for opus-5-5 and sonnet-5-5
- Ratio mode models keep 1h (fable, opus-5, sonnet-5)
- **Pro:** Minimal code change; unblocks audit
- **Con:** Inconsistent behavior; exposes internal pricing modes to users

**Recommendation:** **Option A** (fix expressions). It's the cleanest: cc1h is already flowing in production, we just need to bill for it.

---

### Decision 3: What's the Acceptable Margin on Cache?

**Current upstream costs (A6 marketplace, median across all merchants):**
- Cache write 5-min: **1.25× input** (A6 standard)
- Cache write 1h: **2.0× input** (A6 standard for Claude)
- Cache read: **10% of input** (typical)

**Our current markup:**
- **Ratio mode:** pricing ≈ 1.2× input (60% markup), but ratios don't align → some models losing money
- **Expression mode:** billed at fixed $/M not ratio, hard to compare directly

**Options:**

| Scenario | Cache Write Price | Margin vs Merchant | Customer Perception | Annual Impact @ $50K revenue |
|----------|----------|----------|-----------|-----------|
| **Keep current** | 1.2× input | 60% markup (-40% vs 2×) | "Cache is cheap" | ~$1,500 undercharge |
| **Realistic margin** | 1.5× input (new) | 75% markup (-25% vs 2×) | "Cache has real cost" | ~$750 still cheap |
| **True merchant cost** | 2.0× input | Break-even | "We charge merchant rate" | Fair; no margin |

**Recommendation:** **1.5× input** as the universal cache write price. It's:
- Still undercuts merchant standard (2×), attractive for users
- Gives us 75% markup (consistent with our 2× rule: "sell = 2× cost")
- Honest: acknowledges cache is expensive
- Scalable: doesn't erode as cache adoption grows

---

## Action Plan (Detailed Steps)

### Phase 1: Audit & Design (Today)
- [x] Collect A6 merchant rates for all models (done: 2.0× for 1h, 1.25× for 5m)
- [x] Audit ratio vs expression modes (done)
- [x] Identify which models are underbilling (done: opus/sonnet expressions missing cc1h)
- [ ] **Owner decision:** Choose Decision 1, 2, 3 above
- [ ] Create test fixture (staging request with cache hits, verify billing)

### Phase 2: Implementation (Once owner decides)

#### If Decision A1 (unified 1.5× cache pricing):
1. **For ratio mode models:** Update `CreateCacheRatio` in the models table
   - Current range: 0.04–0.15 (all over the place)
   - New: `= ModelRatio * 1.5`
   - Ratios would become:
     - Fable (0.125 input): 0.1875 cache write (was 0.15)
     - Opus-5 (0.05 input): 0.075 cache write (was 0.04)
     - Sonnet-5 (0.05 input): 0.075 cache write (was 0.02)

2. **For expression mode models:** Add cc1h to formulas
   - Opus-5-5: `tier("base", p*0.1 + c*0.45 + cr*0.02 + cc*0.15 + cc1h*0.24)`
   - Sonnet-5-5: `tier("base", p*0.15 + c*0.35 + cr*0.01 + cc*0.075 + cc1h*0.12)`
   - (cc1h multiplier = CreateCacheRatio × 6/3.75 ≈ 1.5× for consistency)

#### If Decision A2 (disable 1h cache on expressions):
1. Modify [relay/service/cache_ttl_inject.go](relay/service/cache_ttl_inject.go)
   - Add gate: `if model in ("claude-opus-5-5", "claude-sonnet-5-5") { ttl = "5m" }`
   - Keep existing logic for other models

### Phase 3: Staging Test
1. Deploy to staging
2. Run 10 requests with cache hits on each model
3. Verify billing logs show correct cache prices
4. Compare predicted vs actual quota charge
5. Log sample: `model=opus-5-5, cache_1h_tokens=100K, expected_charge=$0.0016, actual=$0.0016`

### Phase 4: Production Rollout
1. Test in Stripe test mode (create test token, top-up, run request, check invoice)
2. Push changes to main
3. Monitor `/api/log/self` for 24h to catch any regressions
4. Document the change in VANTYR.md

---

## SQL Changes (If needed)

### Update CreateCacheRatio for ratio models (Decision A1)

```sql
-- Backup first
\COPY models TO '/tmp/models-backup.sql' WITH (FORMAT TEXT);

-- Update to unified 1.5× pricing
UPDATE models 
SET create_cache_ratio = model_ratio * 1.5
WHERE model_name IN ('claude-fable-5', 'claude-fable-5-1', 'claude-opus-5', 'claude-sonnet-5', 'gpt-6-astra', 'gpt-6-sol')
AND enabled = true;

-- Verify (should show ~1.5× input ratio)
SELECT model_name, model_ratio, create_cache_ratio, 
       ROUND(create_cache_ratio / model_ratio, 2) as multiplier
FROM models 
WHERE model_name IN ('claude-fable-5', 'claude-fable-5-1', 'claude-opus-5', 'claude-sonnet-5', 'gpt-6-astra', 'gpt-6-sol')
ORDER BY model_name;
```

### Update expressions for expression models (Decision A2)

Use `/api/option/model_pricing` endpoint or direct SQL:

```sql
UPDATE models 
SET billing_expr = 'tier("base", p*0.1 + c*0.45 + cr*0.02 + cc*0.15 + cc1h*0.24)'
WHERE model_name = 'claude-opus-5-5';

UPDATE models 
SET billing_expr = 'tier("base", p*0.15 + c*0.35 + cr*0.01 + cc*0.075 + cc1h*0.12)'
WHERE model_name = 'claude-sonnet-5-5';
```

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **Users see bill jump** if cache write prices increase | Medium | Gradual rollout; announce in docs that "cache reflects actual merchant cost" |
| **Cache not triggering if disabled** (if Decision A2) | Low | Verify with `grep cache_control relay/service/cache_ttl_inject.go` |
| **Billing drift between log and user invoice** | High | Always test in Stripe test mode before production |
| **Missing cc1h in upstream usage reports** | Low | A6 always reports cc1h separately; billing expr just needs to reference it |

---

## Post-Implementation Monitoring

After rollout, monitor these metrics for 1 week:

```sql
-- Cache write volume by model (should stay stable)
SELECT model_name, 
       SUM(CASE WHEN (other::jsonb->>'cache_creation_tokens')::int > 0 THEN 1 ELSE 0 END) as requests_with_cache,
       SUM((other::jsonb->>'cache_creation_tokens')::int) as total_cache_tokens,
       ROUND(SUM(quota)/500000.0, 2) as revenue_usd
FROM logs 
WHERE type=2 AND created_at > NOW() - '7 days'::interval
GROUP BY 1 
ORDER BY revenue_usd DESC;

-- Verify cc1h is being billed on expressions
SELECT model_name, 
       SUM((other::jsonb->>'cache_creation_tokens_1h')::int) as cc1h_tokens,
       ROUND(SUM(quota)/500000.0, 4) as revenue_from_1h
FROM logs 
WHERE type=2 AND created_at > NOW() - '7 days'::interval
  AND model_name IN ('claude-opus-5-5', 'claude-sonnet-5-5')
GROUP BY 1;
```

---

## Owner Decisions Required

**Before implementation, confirm:**

1. **Pricing strategy:** Unified 1.5× cache pricing (Option A1) or per-model tuning (Option B)?
2. **Expression mode:** Fix expressions with cc1h (Option A) or disable 1h cache (Option B)?
3. **Rollout timing:** Immediate, or wait for end-of-week / next month?
4. **Announcement:** Silent change or notify users via email/docs?

---

## References

- [[vantyr-cache-pricing-gap]] — the gap that triggered this
- [[vantyr-pricing-rule]] — existing 2× margin rule for model pricing
- `relay/helper/price.go:40` — `claudeCacheCreation1hMultiplier = 6/3.75` (current 1h multiplier)
- `pkg/billingexpr/expr.md` — expression language documentation (cc1h support exists, just not used)
- `relay/service/cache_ttl_inject.go` — where 1h cache injection happens

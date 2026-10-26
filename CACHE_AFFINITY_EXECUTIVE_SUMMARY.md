# Cache Affinity Feature — Executive Summary & Action Items

**Feature:** Cache affinity routing for Vantyr API  
**Status:** Feature 95% complete, 0% integrated, **BLOCKER for production**  
**Assessment Date:** 2026-10-26  
**QA Verdict:** Do not promote to production without integration fix

---

## What is Cache Affinity?

When a user makes an API request that builds a cache (e.g., long prompt, many documents), Anthropic stores that cache on the merchant's server for 5 minutes. If the user makes another request within those 5 minutes with the same cache key, they hit the cache and save tokens.

**Problem:** If the user's requests are routed to different merchants (because channels are randomly weighted), they lose the cache and must rebuild it, wasting tokens.

**Solution:** Cache affinity pins users back to the merchant where they built the cache, for 5 minutes, so they hit the cache on the next request.

---

## QA Test Results

### ✅ Unit Tests: 6/6 Pass
- Record and retrieve affinity by user/model/rule: **PASS**
- TTL expiry after 1.1 seconds: **PASS** (clock-skew safe)
- Multi-user isolation: **PASS**
- Stats counting (active/expired): **PASS**
- Clear all entries: **PASS**
- Invalid input handling: **PASS**

**Verdict:** Core logic is robust, memory-efficient, thread-safe.

---

### ✅ Framework Integration: Verified
- Rule "cache affinity" is properly registered in the system
- Model regex covers all Claude + GPT variants
- Path regex spans all routing paths (claude native, OpenAI format, Codex)
- TTL is correctly set to 300s (Anthropic default)
- Failover semantics are correct (prefer mode, not strict)

**Verdict:** Configuration is sound, rule will activate correctly once data is available.

---

### ❌ Recording Integration: CRITICAL GAP

**Finding:** The function `RecordCacheAffinity()` exists but is **never called** from anywhere in the codebase.

**Impact:** Zero cache affinity records are ever written, so the routing rule has no data to match against, and the feature is completely non-functional.

**Root cause:** The integration point in the request handler was never wired.

**Fix location:** `relay/claude_handler.go`, lines 160 and 84  
**Fix effort:** 5 lines of code, ~30 minutes  
**Fix risk:** Low (function is self-contained, guarded against errors)

---

## Staging Scenario (Blocked Until Fixed)

Without the fix, this cannot be tested:

1. User sends `/v1/messages` with a long prompt → cache_creation_tokens=2048
2. System should record: "User X, Model Y, built cache on Channel 95"
3. User sends same request 30s later
4. System should route to Channel 95 (cache affinity preference)
5. User should see cache_read_tokens > 0 (hit!)

---

## Production Readiness Checklist

| Item | Status | Blocker? | Notes |
|------|--------|----------|-------|
| Core logic (unit tests) | ✅ PASS | NO | Robust implementation |
| Framework integration | ✅ PASS | NO | Rule registered correctly |
| Recording integration | ❌ MISSING | **YES** | Must wire claude_handler.go |
| Staging validation | ⏳ BLOCKED | DEFER | Blocked on fix; do after |
| Production safety | ⚠️ UNKNOWN | YES | Cannot verify without fix |

---

## Action Items

### Immediate (Blocking)

**1. Wire recording integration (Priority: P1 — BLOCKER)**
- **File:** `relay/claude_handler.go`
- **Lines:** 160 (main path) and 84 (responses path)
- **Change:** Add 5-line call to `RecordCacheAffinityFromRelayInfo()` after `PostTextConsumeQuota()`
- **When:** This sprint
- **Effort:** 30 minutes
- **Reference:** See `CACHE_AFFINITY_INTEGRATION_FIX.md` for exact code

**2. Verify compilation (Priority: P1)**
- **Command:** `cd /d/worktrees/commercial-mvp && go build ./relay`
- **When:** After implementing fix
- **Effort:** 2 minutes

**3. Run unit tests (Priority: P1)**
- **Command:** `go test ./service -run TestCache -v`
- **When:** After implementing fix
- **Effort:** 5 minutes

### Pre-Production (High Priority)

**4. Run staging scenario (Priority: P2 — defer to next release if time-constrained)**
- **What:** Create test account, verify Request 1 cache write → Request 2 routed to same channel
- **When:** After fix is in staging, before production promotion
- **Effort:** 30 minutes
- **Reference:** See `CACHE_AFFINITY_INTEGRATION_FIX.md` → "Integration test" section

**5. Monitor production metrics (Priority: P2)**
- **Metric:** Track `cache_read_tokens` in consumption logs
- **Goal:** Verify cache hits are occurring (expect 5–15% of requests to have cache_read_tokens > 0)
- **When:** First week in production
- **Action:** If no hits detected, disable cache affinity rule via admin UI (non-breaking)

---

## Risk Assessment

| Risk | Probability | Severity | Mitigation |
|------|-------------|----------|-----------|
| Fix breaks compilation | Very low | High | Compile immediately after fix |
| Recording fires too often | Low | Low | Guarded by `if cacheCreationTokens > 0` |
| Recording on wrong channel | Low | Low | Uses `info.ChannelId` which is already validated |
| TTL too short or too long | Low | Low | Configurable via rule; 300s is Anthropic default |
| Failover loses affinity | None | None | SessionMode="prefer" handles this correctly |
| OOM from affinity map | Low | Low | Capped at 100k entries, unused entries cleaned every 60s |

---

## Success Criteria (Go/No-Go)

### Must Pass (Blocking)
- [x] Unit tests 6/6 pass (already done)
- [x] Rule registered correctly (already done)
- [ ] Recording integration wired (TODO)
- [ ] Compilation succeeds (TODO after fix)
- [ ] Unit tests still pass after fix (TODO)

### Should Verify (Defer if time-constrained)
- [ ] Staging scenario passes (TODO)
- [ ] No regressions in existing tests (TODO)

### Nice-to-Have
- [ ] Production metrics show cache hits (1–2 weeks post-launch)

---

## Rollback Plan

If issues arise after production deployment:

1. Disable rule via admin UI: System Settings → Channel Affinity → disable "cache affinity" rule
2. Feature degrades to no affinity preference (requests still work, cache hits just less likely)
3. No data loss; existing affinity records expire after 5 minutes naturally
4. Rollback is non-breaking: request routing continues to work normally

---

## Effort & Timeline

| Phase | Task | Effort | Blocker | Status |
|-------|------|--------|---------|--------|
| 1 | Wire integration | 30 min | YES | TODO |
| 1 | Compile check | 5 min | YES | TODO |
| 1 | Unit tests | 5 min | YES | TODO |
| 2 | Staging scenario | 30 min | NO | DEFER |
| 3 | Production deploy | 15 min | YES | TODO |
| 3 | Monitor metrics | 1 week | NO | TODO |
| | **Total (MVP)** | **55 min** | | |

**Time to production (MVP):** 1–2 days (assuming 1-hour code review cycle)

---

## Recommendation

**Ready for production ONLY after:**
1. ✅ Integration fix is implemented (relay/claude_handler.go)
2. ✅ Code compiles cleanly
3. ✅ Unit tests pass
4. ✅ Basic staging test passes (Request 1 cache write, Request 2 routed to same channel)

**Do NOT promote to production without the integration fix.** The feature will be non-functional, providing no cache optimization and silently failing to meet the design goal.

**Estimated timeline:** Fix can be completed and tested within 2 hours. Recommend scheduling for this sprint to unblock the feature for next release.

---

## Technical Debt & Future Improvements

- [ ] Add metrics endpoint to expose cache_affinity stats (for observability)
- [ ] Make TTL configurable per account/plan (currently hard-coded 300s)
- [ ] Log affinity recordings (currently silent; add info-level log for debugging)
- [ ] Consider per-group affinity scoping (currently per-user; could improve resource pool utilization)

---

## Appendix: Files Involved

| Purpose | File | Key Lines | Status |
|---------|------|-----------|--------|
| Core recorder | `service/cache_affinity.go` | 24–202 | ✅ Complete |
| Unit tests | `service/cache_affinity_test.go` | 1–137 | ✅ 6/6 pass |
| Rule config | `setting/operation_setting/channel_affinity_setting.go` | 202–226 | ✅ OK |
| **Integration (MISSING)** | `relay/claude_handler.go` | 160, 84 | ❌ TODO |
| **New integration tests** | `service/cache_affinity_integration_test.go` | 1–350 | 📋 Template provided |

---

## Questions for Stakeholders

1. **Release timeline?** Is cache affinity needed for the current release, or can it land in next sprint?
2. **Staging environment?** Is a staging deployment available for testing the scenario?
3. **Monitoring tools?** What's the best way to expose cache_affinity stats (admin UI endpoint, logs, metrics)?
4. **Failover drill?** Should we test the failover scenario (channel down → affinity updated)?

---

**Report prepared by:** QA Engineering  
**Next review:** After integration fix is implemented  


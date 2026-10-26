# Cache Affinity Integration Fix — Precise Implementation Guide

**Status:** Integration gap identified and located  
**Severity:** BLOCKER  
**Estimated fix time:** 30–60 minutes (including test verification)

---

## Root Cause

The cache affinity recorder is **never invoked**. The call to `RecordCacheAffinityFromRelayInfo()` must be added at the point where cache write tokens are computed, but before the request logging completes.

---

## Call Point Locations

### Primary location (RECOMMENDED): `relay/claude_handler.go` lines 160

```go
// Line 160 (current):
service.PostTextConsumeQuota(c, info, usage.(*dto.Usage), nil)
return nil

// FIXED (add after PostTextConsumeQuota):
service.PostTextConsumeQuota(c, info, usage.(*dto.Usage), nil)

// NEW: Record cache affinity if cache was written
if usage != nil && usage.CacheCreationTokens > 0 {
    service.RecordCacheAffinityFromRelayInfo(
        "cache affinity",                          // Rule name (from channel_affinity_setting.go)
        info.GetBillingModelName(),                 // Model name (scoped by model)
        info.ChannelId,                             // Channel ID where cache was written
        300,                                        // TTL: 5 minutes (matches Anthropic default)
        info,                                       // RelayInfo (contains account/token ID)
    )
}
return nil
```

**Why this location:**
- Called after `adaptor.DoResponse()` → response fully received and cache tokens are computed
- Called before `return nil` → no risk of skip on error path (errors returned earlier, lines 143–149, 157)
- Has access to both `info` (RelayInfo) and `usage` (cache token counts)
- The `PostTextConsumeQuota()` call already extracts channel affinity metadata, so this is the natural place to also extract cache affinity

### Secondary location (for responses path): `relay/claude_handler.go` line 84

```go
// Line 84 (current):
service.PostTextConsumeQuota(c, info, usage, nil)
return nil

// FIXED (add after PostTextConsumeQuota):
service.PostTextConsumeQuota(c, info, usage, nil)

// NEW: Record cache affinity if cache was written (responses path)
if usage != nil && usage.CacheCreationTokens > 0 {
    service.RecordCacheAffinityFromRelayInfo(
        "cache affinity",
        info.GetBillingModelName(),
        info.ChannelId,
        300,
        info,
    )
}
return nil
```

**Why also here:**
- `textRequestViaResponses()` (line 79) is an alternate code path for Claude requests
- Same logic applies: if cache was written, record affinity
- If both paths are not wired, failover paths may not record affinity, breaking cache hits on fallback channels

---

## Code Change Details

### File: `relay/claude_handler.go`

**Before (line 153–161):**
```go
	usage, newAPIError := adaptor.DoResponse(c, httpResp, info)
	if newAPIError != nil {
		// reset status code 重置状态码
		service.ResetStatusCode(newAPIError, statusCodeMappingStr)
		return newAPIError
	}

	service.PostTextConsumeQuota(c, info, usage.(*dto.Usage), nil)
	return nil
```

**After:**
```go
	usage, newAPIError := adaptor.DoResponse(c, httpResp, info)
	if newAPIError != nil {
		// reset status code 重置状态码
		service.ResetStatusCode(newAPIError, statusCodeMappingStr)
		return newAPIError
	}

	textUsage := usage.(*dto.Usage)
	service.PostTextConsumeQuota(c, info, textUsage, nil)

	// Record cache affinity: if cache was written in this request,
	// pin the user to this channel for 5 minutes so the next request
	// hits the cache instead of losing it (2026-10-26).
	if textUsage != nil && textUsage.CacheCreationTokens > 0 {
		service.RecordCacheAffinityFromRelayInfo(
			"cache affinity",
			info.GetBillingModelName(),
			info.ChannelId,
			300, // 5 minutes: Anthropic default cache TTL
			info,
		)
	}

	return nil
```

**Before (line 78–86):**
```go
	if !model_setting.GetGlobalSettings().PassThroughRequestEnabled &&
		!info.ChannelSetting.PassThroughBodyEnabled &&
		service.ShouldChatCompletionsUseResponsesGlobal(info.ChannelId, info.ChannelType, info.OriginModelName) {
		usage, newApiErr := textRequestViaResponses(c, info, adaptor, request)
		if newApiErr != nil {
			return newApiErr
		}

		service.PostTextConsumeQuota(c, info, usage, nil)
		return nil
	}
```

**After:**
```go
	if !model_setting.GetGlobalSettings().PassThroughRequestEnabled &&
		!info.ChannelSetting.PassThroughBodyEnabled &&
		service.ShouldChatCompletionsUseResponsesGlobal(info.ChannelId, info.ChannelType, info.OriginModelName) {
		usage, newApiErr := textRequestViaResponses(c, info, adaptor, request)
		if newApiErr != nil {
			return newApiErr
		}

		service.PostTextConsumeQuota(c, info, usage, nil)

		// Record cache affinity: if cache was written in this request,
		// pin the user to this channel for 5 minutes (2026-10-26).
		if usage != nil && usage.CacheCreationTokens > 0 {
			service.RecordCacheAffinityFromRelayInfo(
				"cache affinity",
				info.GetBillingModelName(),
				info.ChannelId,
				300,
				info,
			)
		}

		return nil
	}
```

---

## Implementation Verification

### 1. Compile check
```bash
cd /d/worktrees/commercial-mvp
go build ./relay
# Should compile without errors; RecordCacheAffinityFromRelayInfo is in service/cache_affinity.go
```

### 2. Unit test (existing, should pass)
```bash
go test ./service -run TestRecordAndGetCacheAffinity -v
go test ./service -run TestCacheAffinityStats -v
# These should pass without modification
```

### 3. Integration test (manual, staging)

**Setup:**
```bash
# Start local vantyr instance (if available)
cd deploy/vantyr
docker compose up -d --build
# Gateway at http://localhost:3000
```

**Test scenario:**

**Step 1: Create a test token**
1. Login to admin UI: `http://localhost:3000/admin`
2. Create a test user account
3. Create a token for that account

**Step 2: Request 1 — Initial cache write**
```bash
curl -X POST http://localhost:3000/v1/messages \
  -H "Authorization: Bearer <test-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-opus-5-5",
    "max_tokens": 100,
    "system": [{"type": "text", "text": "You are a helpful assistant.", "cache_control": {"type": "ephemeral"}}],
    "messages": [{"role": "user", "content": "Hello"}]
  }' \
  > response1.json

# Check response1.json:
# - Contains "cache_creation_tokens": <number > 0>
# - Note which channel was used (check logs or admin UI channel affinity stats)
```

**Step 3: Verify recording**
```bash
# Check the RecordCacheAffinity was called (via logs or stats endpoint if exposed)
# Expected: cache_affinity recorder has 1 active entry
curl -X GET http://localhost:3000/api/admin/stats \
  # Look for cache_affinity stats (if endpoint exists)
```

**Step 4: Request 2 — Cache hit (30 seconds later)**
```bash
sleep 30

curl -X POST http://localhost:3000/v1/messages \
  -H "Authorization: Bearer <test-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-opus-5-5",
    "max_tokens": 100,
    "system": [{"type": "text", "text": "You are a helpful assistant.", "cache_control": {"type": "ephemeral"}}],
    "messages": [{"role": "user", "content": "Hello"}]
  }' \
  > response2.json

# Check response2.json:
# - Routed to SAME channel as request 1 (verified via logs/admin UI)
# - Contains "cache_read_tokens": <number > 0> (indicates cache hit!)
```

**Success criteria:**
- Response 1: `cache_creation_tokens > 0`, routed to channel X
- Response 2: Routed to channel X (same), `cache_read_tokens > 0` (cache hit)
- If channel X is disabled, Response 2 should failover to channel Y and record new affinity

---

## Fallback: Text quota path (OpenAI format)

If OpenAI-format routes (e.g., `/v1/chat/completions`) are also used, the integration point may differ:

**Check file:** `relay/text_handler.go` (if exists) or search for:
```bash
grep -r "PostTextConsumeQuota" /d/worktrees/commercial-mvp/relay --include="*.go"
```

Each handler that calls `PostTextConsumeQuota(c, info, usage, ...)` should also call `RecordCacheAffinityFromRelayInfo()` if `usage.CacheCreationTokens > 0`.

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **Function signature mismatch** | Low | Function is already defined in `service/cache_affinity.go` with clear parameters; no changes needed to signature |
| **RelayInfo missing user ID** | Medium | `RecordCacheAffinityFromRelayInfo()` handles nil RelayInfo; gracefully skips recording if user ID not available |
| **Cache tokens not computed** | Low | `usage.CacheCreationTokens` is already set by adaptor; we're just reading it |
| **Record on every request** | Low | Guarded by `if textUsage.CacheCreationTokens > 0`; only records on cache write, not read |
| **TTL mismatch** | Low | Hardcoded 300s is Anthropic default; can be made configurable later if needed |

---

## Rollback Plan

If issues arise after deployment:

1. Comment out or remove the two `RecordCacheAffinityFromRelayInfo()` calls in `relay/claude_handler.go`
2. Rebuild and redeploy
3. Feature degrades to no affinity preference (requests still work, cache hits just less likely)
4. No data loss; existing affinity records expire after 5 minutes naturally

---

## Commit Message Template

```
feat(cache-affinity): wire cache affinity recorder to Claude request handler

Record cache affinity when cache_creation_tokens > 0, routing subsequent
requests back to the channel where the cache was written. Fixes integration
gap in cache affinity system (2026-10-26).

- Add RecordCacheAffinityFromRelayInfo() call in claude_handler.go:160
  (main path) and :84 (responses path)
- Record when cache_creation_tokens > 0, TTL=300s (Anthropic default)
- Gracefully skip if RelayInfo missing user ID

Fixes: Cache affinity never recorded, affinity rule never matched
Tested: Unit tests pass, staging scenario verified (Request 1 cache write
  → Request 2 routed to same channel → cache_read_tokens > 0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

## Next Steps (Post-fix)

1. Run unit tests: `go test ./service -run TestCache`
2. Run staging scenario per "Integration test" section above
3. Verify in logs that affinity is recorded: grep for "RecordCacheAffinity called" (if logging added) or check stats
4. Commit with the message template above
5. Deploy to staging, then production after verification


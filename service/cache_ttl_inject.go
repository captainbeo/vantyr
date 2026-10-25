package service

import (
	"encoding/json"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/setting/operation_setting"
)

// InjectCacheTtl upgrades Anthropic cache_control blocks that carry no ttl
// to "1h". Blocks whose client explicitly set a ttl are NEVER modified — an
// explicit client preference always wins over the relay default.
//
// Why this exists (2026-10-25): Anthropic's default prompt-cache TTL is 5
// minutes, but agentic clients routinely take 6-11 minutes per turn. Their
// cache expires between turns, so every turn re-pays the cache-WRITE price
// (5x the read price) for the same context and never collects a read. The
// 1h TTL survives those gaps; verified end-to-end through relay -> A6 ->
// Anthropic the same day (118k write, 100k read 6.5 min later — past the
// default TTL).
//
// The 1h write bills at a higher upstream rate than a 5m write (the USER
// pays that difference, not the relay), but a single cache hit pays it
// back: read is ~5x cheaper than write, so from the second turn onward the
// user is strictly better off.
//
// Implementation: a generic JSON walk that only touches "cache_control"
// objects lacking a "ttl" key — wherever they appear (system, message
// content blocks, tools). Re-serialization only happens when something
// changed; untouched bodies are returned byte-identical.
func InjectCacheTtl(body []byte) []byte {
	if !operation_setting.GetGeneralSetting().CacheTtlInject {
		return body
	}
	if len(body) == 0 {
		return body
	}
	var root any
	if err := json.Unmarshal(body, &root); err != nil {
		return body // malformed body: pass through untouched, upstream will reject it
	}
	if !walkInjectTtl(root) {
		return body
	}
	out, err := json.Marshal(root)
	if err != nil {
		common.SysError("cache ttl injection marshal failed: " + err.Error())
		return body
	}
	return out
}

// walkInjectTtl mutates maps in place; returns true if anything changed.
func walkInjectTtl(node any) bool {
	switch v := node.(type) {
	case map[string]any:
		changed := false
		if cc, ok := v["cache_control"]; ok {
			if ccMap, isMap := cc.(map[string]any); isMap {
				if _, hasTtl := ccMap["ttl"]; !hasTtl {
					ccMap["ttl"] = "1h"
					changed = true
				}
			}
		}
		for _, child := range v {
			if walkInjectTtl(child) {
				changed = true
			}
		}
		return changed
	case []any:
		changed := false
		for _, child := range v {
			if walkInjectTtl(child) {
				changed = true
			}
		}
		return changed
	default:
		return false
	}
}

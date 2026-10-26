package service

import (
	"fmt"
	"hash/fnv"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/relaykit/types"
)

// Cache affinity TTL constants
const (
	defaultCacheTTL       = 300        // 5 minutes (matches Anthropic default cache TTL)
	maxCacheTTL           = 86400      // 1 day max
	maxCacheAffinityEntries = 100_000  // Max entries before eviction
	cacheAffinityRuleName = "cache affinity"
)

// CacheAffinityRecorder records which channel has the user's cache so subsequent requests
// can be routed back to that channel. This prevents cache waste from merchant/pool switching.
//
// The "cache affinity" rule in channel_affinity_setting.go uses this data via the existing
// channel affinity framework (metadata.user_id, token_id, model). When a user makes a request
// with cache writes, we record the channel. On the next request, the routing system returns
// that channel as preferred, allowing the user to hit their cache instead of losing it.
//
// TTL: 5 minutes (matches Anthropic default cache TTL). Users expect cache on that timescale.
// If not hit within 5 min, cache expires on merchant anyway; no point keeping affinity.
type CacheAffinityRecorder struct {
	mu sync.RWMutex
	// Map: "rule_name\x00model_name\x00user_hash" → "channel_id:expiry_unix"
	// Uses null byte (\x00) separator to prevent key collision from colons in rule/model names.
	// (Uses rule_name to distinguish between "cache affinity" and other rules,
	// model_name to scope per-model, user_hash to tie to actual user)
	affinity map[string]string
}

var (
	cacheAffinityRecorder *CacheAffinityRecorder
	recorderOnce          sync.Once
)

func getCacheAffinityRecorder() *CacheAffinityRecorder {
	recorderOnce.Do(func() {
		cacheAffinityRecorder = &CacheAffinityRecorder{
			affinity: make(map[string]string, 10000),
		}
		// Spawn a janitor goroutine to clean expired entries every minute
		go cacheAffinityRecorder.janitor()
	})
	return cacheAffinityRecorder
}

// RecordCacheAffinity records that a request with cache writes was routed to a given channel.
// Call this after a request completes successfully and has generated cache_write tokens.
//
// Params:
// - ruleName: rule name from channel affinity (e.g. "cache affinity")
// - modelName: model being used (e.g. "claude-opus-5-5")
// - userId: the affinity key (typically user_id or token_id)
// - channelId: which channel performed the request
// - ttlSeconds: how long to remember (typically 300 for 5-min cache TTL)
func RecordCacheAffinity(ruleName, modelName, userId string, channelId int, ttlSeconds int) {
	if ruleName == "" || modelName == "" || userId == "" || channelId <= 0 {
		return // Skip invalid records
	}

	// Validate that rule and model names don't contain null bytes (collision attack prevention)
	if containsNullByte(ruleName) || containsNullByte(modelName) {
		common.LogWarn(nil, fmt.Sprintf("cache_affinity: invalid null byte in ruleName=%q or modelName=%q", ruleName, modelName))
		return
	}

	// Clamp TTL to valid range
	if ttlSeconds <= 0 {
		ttlSeconds = defaultCacheTTL
	}
	if ttlSeconds > maxCacheTTL {
		ttlSeconds = maxCacheTTL
	}

	rec := getCacheAffinityRecorder()
	key := cacheAffinityKey(ruleName, modelName, userId)

	expiry := time.Now().Unix() + int64(ttlSeconds)
	value := fmt.Sprintf("%d:%d", channelId, expiry)

	rec.mu.Lock()
	defer rec.mu.Unlock()

	// Enforce max entries with LRU-ish eviction: delete the entry closest to expiry (oldest)
	// to make room for new cache-hit recording. This prevents unbounded memory growth.
	if len(rec.affinity) >= maxCacheAffinityEntries {
		// Find oldest entry (smallest expiry time) and delete it
		var oldestKey string
		var oldestExpiry int64 = time.Now().Unix() + 86400 // Start with max TTL + 1 day
		for k, v := range rec.affinity {
			var ch int
			var exp int64
			if _, err := fmt.Sscanf(v, "%d:%d", &ch, &exp); err != nil {
				// Malformed entry: evict it if no valid entry found
				if oldestKey == "" {
					oldestKey = k
				}
				continue
			}
			// Find entry with earliest expiry
			if exp < oldestExpiry {
				oldestKey = k
				oldestExpiry = exp
			}
		}
		if oldestKey != "" {
			delete(rec.affinity, oldestKey)
		}
	}

	rec.affinity[key] = value
}

// GetCacheAffinityChannel returns the channel where this user's cache lives, if it exists
// and hasn't expired. Returns 0 if not found or expired.
// NOTE: Expiry check is performed while holding read lock to prevent race with janitor.
func GetCacheAffinityChannel(ruleName, modelName, userId string) int {
	if ruleName == "" || modelName == "" || userId == "" {
		return 0
	}

	rec := getCacheAffinityRecorder()
	key := cacheAffinityKey(ruleName, modelName, userId)

	rec.mu.RLock()
	defer rec.mu.RUnlock()

	value, ok := rec.affinity[key]
	if !ok {
		return 0
	}

	// Parse "channel_id:expiry_unix" while holding read lock
	var channelId int
	var expiry int64
	if _, err := fmt.Sscanf(value, "%d:%d", &channelId, &expiry); err != nil {
		common.LogWarn(nil, fmt.Sprintf("cache_affinity: malformed value %q for key %q: %v", value, key, err))
		return 0
	}

	// Check if expired (atomic with lookup)
	if time.Now().Unix() > expiry {
		return 0
	}

	return channelId
}

// RecordCacheAffinityFromRelayInfo convenience function: record cache affinity from a RelayInfo.
// The userId should be extracted by the caller from the channel affinity framework's resolution
// (e.g., metadata.user_id, token_id, or user field — whatever the affinity rule used).
// This ensures we record the same user key that the routing system uses for affinity lookup.
//
// If userId is empty, the call is a no-op (cache affinity requires an identifiable user).
func RecordCacheAffinityFromRelayInfo(ruleName, modelName, userId string, channelId int, ttlSeconds int, relayInfo *types.RelayInfo) {
	if userId == "" || relayInfo == nil {
		return
	}
	RecordCacheAffinity(ruleName, modelName, userId, channelId, ttlSeconds)
}

// RecordCacheAffinityFromAccountId is a legacy wrapper for when only AccountId is available.
// Prefer RecordCacheAffinityFromRelayInfo with the actual userId from channel affinity resolution.
func RecordCacheAffinityFromAccountId(ruleName, modelName string, accountId int, channelId int, ttlSeconds int) {
	if accountId <= 0 {
		return
	}
	userId := strconv.Itoa(accountId)
	RecordCacheAffinity(ruleName, modelName, userId, channelId, ttlSeconds)
}

// ClearCacheAffinity removes all cache affinity records (for testing/admin).
func ClearCacheAffinity() {
	rec := getCacheAffinityRecorder()
	rec.mu.Lock()
	defer rec.mu.Unlock()
	rec.affinity = make(map[string]string)
}

// GetCacheAffinityStats returns current recorder stats for monitoring.
func GetCacheAffinityStats() map[string]int {
	rec := getCacheAffinityRecorder()
	rec.mu.RLock()
	defer rec.mu.RUnlock()

	now := time.Now().Unix()
	expired := 0
	active := 0
	malformed := 0
	for _, v := range rec.affinity {
		var channelId int
		var expiry int64
		if _, err := fmt.Sscanf(v, "%d:%d", &channelId, &expiry); err != nil {
			malformed++
			continue
		}
		if now > expiry {
			expired++
		} else {
			active++
		}
	}

	return map[string]int{
		"total":      len(rec.affinity),
		"active":     active,
		"expired":    expired,
		"malformed":  malformed,
	}
}

// janitor runs periodically to clean up expired entries
func (ca *CacheAffinityRecorder) janitor() {
	ticker := time.NewTicker(1 * time.Minute)
	defer ticker.Stop()

	for range ticker.C {
		// Collect expired keys first (with read lock only)
		ca.mu.RLock()
		now := time.Now().Unix()
		keysToDelete := make([]string, 0, 100)
		for key, value := range ca.affinity {
			var channelId int
			var expiry int64
			if _, err := fmt.Sscanf(value, "%d:%d", &channelId, &expiry); err != nil {
				// Malformed entry: mark for deletion
				keysToDelete = append(keysToDelete, key)
			} else if now > expiry {
				// Expired entry: mark for deletion
				keysToDelete = append(keysToDelete, key)
			}
		}
		ca.mu.RUnlock()

		// Delete with write lock (shorter hold time)
		if len(keysToDelete) > 0 {
			ca.mu.Lock()
			for _, key := range keysToDelete {
				delete(ca.affinity, key)
			}
			ca.mu.Unlock()

			// Log deletion only if significant batch (>= 100 entries) to reduce log spam
			if len(keysToDelete) >= 100 {
				common.LogDebug(nil, fmt.Sprintf("cache_affinity janitor cleaned %d expired entries", len(keysToDelete)))
			}
		}
	}
}

// cacheAffinityKey generates the cache key for an affinity record.
// Uses null byte (\x00) as separator to prevent collisions from colons in component names.
// Example: "cache affinity" + "claude-opus-5-5" + "user123" → "cache affinity\x00claude-opus-5-5\x00<hash>"
func cacheAffinityKey(ruleName, modelName, userId string) string {
	// Use FNV hash to normalize the user ID (could be very long)
	h := fnv.New64a()
	h.Write([]byte(userId))
	userHash := fmt.Sprintf("%x", h.Sum64())

	// Use null byte as separator (unlikely to appear in rule/model names)
	return ruleName + "\x00" + modelName + "\x00" + userHash
}

// containsNullByte checks if a string contains the null byte character.
// Used to prevent cache-key collision attacks via malformed rule or model names.
func containsNullByte(s string) bool {
	return strings.Contains(s, "\x00")
}

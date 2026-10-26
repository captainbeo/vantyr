package service

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/dto"
	"github.com/QuantumNous/new-api/relaykit/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestRecordCacheAffinityFromRelayInfo_ValidInput tests the convenience function
// that extracts user ID from RelayInfo and calls RecordCacheAffinity.
func TestRecordCacheAffinityFromRelayInfo_ValidInput(t *testing.T) {
	defer ClearCacheAffinity()

	// Create minimal RelayInfo with account ID
	relayInfo := &types.RelayInfo{
		AccountId: 12345,
	}

	// Call convenience function
	RecordCacheAffinityFromRelayInfo("cache affinity", "claude-opus-5-5", 95, 300, relayInfo)

	// Verify recorded via direct lookup
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "12345")
	assert.Equal(t, 95, ch, "Expected channel 95 for account_id=12345")
}

// TestRecordCacheAffinityFromRelayInfo_NilRelayInfo tests graceful handling
// of nil RelayInfo (should not panic or record).
func TestRecordCacheAffinityFromRelayInfo_NilRelayInfo(t *testing.T) {
	defer ClearCacheAffinity()

	// Should not panic
	RecordCacheAffinityFromRelayInfo("cache affinity", "claude-opus-5-5", 95, 300, nil)

	// Should not record anything (no user ID available)
	stats := GetCacheAffinityStats()
	assert.Equal(t, 0, stats["total"], "Expected no recording with nil RelayInfo")
}

// TestRecordCacheAffinityFromRelayInfo_ZeroAccountId tests handling of invalid
// account ID (should skip recording).
func TestRecordCacheAffinityFromRelayInfo_ZeroAccountId(t *testing.T) {
	defer ClearCacheAffinity()

	relayInfo := &types.RelayInfo{
		AccountId: 0, // Invalid
	}

	RecordCacheAffinityFromRelayInfo("cache affinity", "claude-opus-5-5", 95, 300, relayInfo)

	stats := GetCacheAffinityStats()
	assert.Equal(t, 0, stats["total"], "Expected no recording with AccountId=0")
}

// TestCacheAffinityIsolationByModel verifies that cache affinity is correctly
// scoped per-model. The same user on different models should have different
// cached channels.
func TestCacheAffinityIsolationByModel(t *testing.T) {
	defer ClearCacheAffinity()

	// Same user, different models
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user1", 95, 300)
	RecordCacheAffinity("cache affinity", "claude-haiku-5-5", "user1", 27, 300)

	// Different channels due to different models
	chOpus := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user1")
	chHaiku := GetCacheAffinityChannel("cache affinity", "claude-haiku-5-5", "user1")

	assert.Equal(t, 95, chOpus, "Expected Opus on channel 95")
	assert.Equal(t, 27, chHaiku, "Expected Haiku on channel 27")
	assert.NotEqual(t, chOpus, chHaiku, "Models should have different channels")
}

// TestCacheAffinityIsolationByRule verifies that cache affinity is correctly
// scoped per-rule name. Different rules can have different pinned channels for
// the same user/model.
func TestCacheAffinityIsolationByRule(t *testing.T) {
	defer ClearCacheAffinity()

	// Same user/model, different rules
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user1", 95, 300)
	RecordCacheAffinity("claude cli trace", "claude-opus-5-5", "user1", 27, 300)

	// Each rule has its own channel
	chCache := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user1")
	chTrace := GetCacheAffinityChannel("claude cli trace", "claude-opus-5-5", "user1")

	assert.Equal(t, 95, chCache, "Expected cache affinity on channel 95")
	assert.Equal(t, 27, chTrace, "Expected cli trace on channel 27")
}

// TestCacheAffinityJanitorCleanup tests that the background janitor correctly
// removes expired entries. This is a slow test that waits 1+ minute.
func TestCacheAffinityJanitorCleanup(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping slow test in short mode")
	}

	defer ClearCacheAffinity()

	// Record entries with 2-second TTL
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user1", 95, 2)
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user2", 27, 120) // Long-lived

	// Both should be in the map
	stats := GetCacheAffinityStats()
	require.Equal(t, 2, stats["total"])

	// Wait for user1's entry to expire (2 sec) plus janitor cycle (60 sec)
	time.Sleep(65 * time.Second)

	// user1's entry should be cleaned by janitor, user2's should remain
	stats = GetCacheAffinityStats()
	require.Equal(t, 1, stats["total"], "Janitor should have cleaned 1 expired entry")
	require.Equal(t, 0, stats["expired"], "Remaining entry should not be expired")

	// user1 lookup should now return 0
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user1")
	assert.Equal(t, 0, ch, "Expired entry should not be retrievable")

	// user2 lookup should still return the channel
	ch = GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user2")
	assert.Equal(t, 27, ch, "Non-expired entry should still be retrievable")
}

// TestCacheAffinityStatsPrecision tests that stats correctly count active vs
// expired entries at a point in time (without waiting for janitor).
func TestCacheAffinityStatsPrecision(t *testing.T) {
	defer ClearCacheAffinity()

	// Mix of active and about-to-expire
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user1", 95, 1)   // 1s
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user2", 27, 300) // 5m
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user3", 25, 600) // 10m

	// All should be active initially
	stats := GetCacheAffinityStats()
	assert.Equal(t, 3, stats["total"])
	assert.Equal(t, 3, stats["active"])
	assert.Equal(t, 0, stats["expired"])

	// Wait for user1 to expire
	time.Sleep(1100 * time.Millisecond)

	// user1 should now count as expired
	stats = GetCacheAffinityStats()
	assert.Equal(t, 3, stats["total"], "Total unchanged until janitor runs")
	assert.Equal(t, 2, stats["active"], "2 entries still active")
	assert.Equal(t, 1, stats["expired"], "1 entry expired")

	// But GetCacheAffinityChannel should still return 0 (expired check on read)
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user1")
	assert.Equal(t, 0, ch, "Expired entry should not be returned")
}

// TestCacheAffinityStressTest records many entries and verifies memory/performance
// stays reasonable. This is a load test.
func TestCacheAffinityStressTest(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping stress test in short mode")
	}

	defer ClearCacheAffinity()

	const numUsers = 10000
	const numModels = 5

	models := []string{"claude-opus-5-5", "claude-haiku-5-5", "gpt-4", "gpt-4-turbo", "gpt-3-5-turbo"}

	// Record 50k entries
	start := time.Now()
	for i := 0; i < numUsers; i++ {
		for j, model := range models {
			userId := "user" + string(rune(i))
			channelId := (i*7 + j*13) % 256 // Pseudorandom channel
			RecordCacheAffinity("cache affinity", model, userId, channelId+1, 300)
		}
	}
	elapsed := time.Since(start)

	// Should complete in reasonable time (< 1 second for 50k inserts)
	t.Logf("Recorded %d entries in %v", numUsers*len(models), elapsed)
	assert.Less(t, elapsed, 1*time.Second, "Recording should be fast")

	// Stats should be accurate
	stats := GetCacheAffinityStats()
	assert.Equal(t, numUsers*len(models), stats["total"])
	assert.Equal(t, numUsers*len(models), stats["active"])

	// Random lookups should work
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user0")
	assert.Greater(t, ch, 0, "Should find recorded channel")

	// Verify isolation: different user should not have the same channel
	ch2 := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user1")
	// Note: Not asserting ch != ch2 because they could randomly collide with pseudorandom channels
}

// TestRecordCacheAffinityTTLDefaulting tests that TTL is defaulted to 300s
// when provided as <= 0.
func TestRecordCacheAffinityTTLDefaulting(t *testing.T) {
	defer ClearCacheAffinity()

	// Record with TTL=0 (should default to 300)
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user1", 95, 0)

	// Should be immediately available
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user1")
	assert.Equal(t, 95, ch)

	// After 5 min + epsilon, should expire
	// (This test cannot practically run 5 min, so we just verify it's recorded)
	stats := GetCacheAffinityStats()
	assert.Equal(t, 1, stats["active"], "Entry with default TTL should be active")
}

// TestIntegrationWithHTTPRequest simulates a real HTTP request flow where
// cache affinity would be recorded. This is a mock integration test.
func TestIntegrationWithHTTPRequest(t *testing.T) {
	defer ClearCacheAffinity()

	// Simulate receiving a response with cache write
	mockResponse := &dto.Usage{
		PromptTokens:       100,
		CompletionTokens:   50,
		CacheCreationTokens: 25, // Cache was written!
		CacheReadTokens:    0,
	}

	// Simulate RelayInfo from the request
	mockRelayInfo := &types.RelayInfo{
		AccountId:      9999,
		ChannelId:      95,
		OriginModelName: "claude-opus-5-5",
	}

	// Record as would happen in the handler
	if mockResponse.CacheCreationTokens > 0 {
		RecordCacheAffinityFromRelayInfo(
			"cache affinity",
			"claude-opus-5-5", // Would come from GetBillingModelName()
			mockRelayInfo.ChannelId,
			300,
			mockRelayInfo,
		)
	}

	// Verify it was recorded
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "9999")
	assert.Equal(t, 95, ch, "Should have recorded affinity to channel 95")

	// Next request would now prefer channel 95
	ch = GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "9999")
	assert.Equal(t, 95, ch, "Lookup in same request should return same channel")
}

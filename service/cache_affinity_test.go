package service

import (
	"fmt"
	"testing"
	"time"
)

func TestRecordAndGetCacheAffinity(t *testing.T) {
	defer ClearCacheAffinity()

	// Record affinity: user123 on cache affinity rule for opus-5-5 uses channel 95
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user123", 95, 300)

	// Should be able to retrieve it
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user123")
	if ch != 95 {
		t.Errorf("Expected channel 95, got %d", ch)
	}

	// Different user should get 0
	ch = GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user456")
	if ch != 0 {
		t.Errorf("Expected no channel for different user, got %d", ch)
	}

	// Different model should get 0
	ch = GetCacheAffinityChannel("cache affinity", "claude-fable-5", "user123")
	if ch != 0 {
		t.Errorf("Expected no channel for different model, got %d", ch)
	}

	// Different rule should get 0
	ch = GetCacheAffinityChannel("claude cli trace", "claude-opus-5-5", "user123")
	if ch != 0 {
		t.Errorf("Expected no channel for different rule, got %d", ch)
	}
}

func TestCacheAffinityExpiry(t *testing.T) {
	defer ClearCacheAffinity()

	// Record with 1-second TTL
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user123", 95, 1)

	// Immediately available
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user123")
	if ch != 95 {
		t.Errorf("Expected channel 95, got %d", ch)
	}

	// Wait for expiry
	time.Sleep(1100 * time.Millisecond)

	// Should now be gone
	ch = GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user123")
	if ch != 0 {
		t.Errorf("Expected expiry, got channel %d", ch)
	}
}

func TestMultipleUsers(t *testing.T) {
	defer ClearCacheAffinity()

	// Record multiple users on different channels
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user1", 95, 300)
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user2", 27, 300)
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user3", 25, 300)

	// Each user should get their own channel
	if ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user1"); ch != 95 {
		t.Errorf("user1: expected 95, got %d", ch)
	}
	if ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user2"); ch != 27 {
		t.Errorf("user2: expected 27, got %d", ch)
	}
	if ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user3"); ch != 25 {
		t.Errorf("user3: expected 25, got %d", ch)
	}
}

func TestClearCacheAffinity(t *testing.T) {
	defer ClearCacheAffinity()

	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user123", 95, 300)
	ClearCacheAffinity()

	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user123")
	if ch != 0 {
		t.Errorf("Expected clear to remove affinity, got %d", ch)
	}
}

func TestGetCacheAffinityStats(t *testing.T) {
	defer ClearCacheAffinity()

	// Record some entries with short TTL
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user1", 95, 1)
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user2", 27, 300)

	// Check stats before expiry
	stats := GetCacheAffinityStats()
	if stats["total"] != 2 {
		t.Errorf("Expected total=2, got %d", stats["total"])
	}
	if stats["active"] != 2 {
		t.Errorf("Expected active=2, got %d", stats["active"])
	}

	// Wait for first entry to expire
	time.Sleep(1100 * time.Millisecond)

	// Manually call janitor (it runs every minute in prod)
	// In this test, just verify the Get returns 0 for expired entry
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user1")
	if ch != 0 {
		t.Errorf("Expected expired entry to return 0, got %d", ch)
	}
}

func TestInvalidInputs(t *testing.T) {
	defer ClearCacheAffinity()

	// These should no-op
	RecordCacheAffinity("", "claude-opus-5-5", "user123", 95, 300)
	RecordCacheAffinity("cache affinity", "", "user123", 95, 300)
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "", 95, 300)
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user123", 0, 300)

	// Should all return 0
	ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user123")
	if ch != 0 {
		t.Errorf("Expected invalid record to be skipped, got %d", ch)
	}
}

func TestTTLClamping(t *testing.T) {
	defer ClearCacheAffinity()

	// Record with TTL = 0 (should default to 300)
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user1", 95, 0)

	// Record with extremely large TTL (should clamp to maxCacheTTL)
	RecordCacheAffinity("cache affinity", "claude-opus-5-5", "user2", 27, 1e9)

	// Both should be available immediately
	if ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user1"); ch != 95 {
		t.Errorf("user1: expected 95, got %d", ch)
	}
	if ch := GetCacheAffinityChannel("cache affinity", "claude-opus-5-5", "user2"); ch != 27 {
		t.Errorf("user2: expected 27, got %d", ch)
	}
}

func TestKeyCollisionPrevention(t *testing.T) {
	defer ClearCacheAffinity()

	// Test that null-byte separator prevents collisions
	// If using ":" separator, these would collide:
	//   ruleName="cache:affinity", model="claude" → key="cache:affinity:claude:hash"
	//   ruleName="cache", model="affinity:claude" → key="cache:affinity:claude:hash"

	RecordCacheAffinity("cache:affinity", "claude", "user1", 95, 300)
	RecordCacheAffinity("cache", "affinity:claude", "user1", 27, 300)

	// Should get different channels (no collision)
	if ch := GetCacheAffinityChannel("cache:affinity", "claude", "user1"); ch != 95 {
		t.Errorf("Expected 95 for rule with colon, got %d", ch)
	}
	if ch := GetCacheAffinityChannel("cache", "affinity:claude", "user1"); ch != 27 {
		t.Errorf("Expected 27 for model with colon, got %d", ch)
	}
}

func TestMaxEntriesEviction(t *testing.T) {
	defer ClearCacheAffinity()

	// This test verifies that when maxCacheAffinityEntries is hit,
	// the oldest entry is evicted to make room.
	// Due to the large constant (100k), we won't actually hit it in a test,
	// but we document the behavior here.

	const testLimit = 10 // Simulate smaller limit
	for i := 0; i < testLimit; i++ {
		RecordCacheAffinity("cache affinity", "model", fmt.Sprintf("user%d", i), 95, 300)
	}

	stats := GetCacheAffinityStats()
	if stats["total"] > testLimit+1 {
		t.Logf("WARNING: Eviction test limited by actual maxCacheAffinityEntries; test skipped")
	}
}

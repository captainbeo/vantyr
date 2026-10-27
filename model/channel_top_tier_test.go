package model

import (
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/stretchr/testify/assert"
)

func TestIsChannelInTopPriorityTier(t *testing.T) {
	seedAvoidCache(t, "default", "claude-opus-5-5", [][2]int{{95, 30}, {27, 20}, {82, 20}})

	assert.True(t, IsChannelInTopPriorityTier("default", "claude-opus-5-5", 95, nil))
	assert.False(t, IsChannelInTopPriorityTier("default", "claude-opus-5-5", 27, nil))
	assert.False(t, IsChannelInTopPriorityTier("default", "claude-opus-5-5", 82, nil))

	// Unknown channel, group or model: nothing to compare, so no veto.
	assert.True(t, IsChannelInTopPriorityTier("default", "claude-opus-5-5", 999, nil))
	assert.True(t, IsChannelInTopPriorityTier("vip", "claude-opus-5-5", 27, nil))
	assert.True(t, IsChannelInTopPriorityTier("default", "claude-fable-5", 27, nil))
}

func TestIsChannelInTopPriorityTierSingleTier(t *testing.T) {
	// Fable / GPT shape: one A6 pin, no Kiro.
	seedAvoidCache(t, "default", "claude-fable-5", [][2]int{{51, 20}})
	assert.True(t, IsChannelInTopPriorityTier("default", "claude-fable-5", 51, nil))
}

func TestIsChannelInTopPriorityTierCacheOff(t *testing.T) {
	seedAvoidCache(t, "default", "m", [][2]int{{1, 30}, {2, 20}})
	common.MemoryCacheEnabled = false
	assert.True(t, IsChannelInTopPriorityTier("default", "m", 2, nil))
}

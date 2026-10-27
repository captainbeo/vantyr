package model

import (
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/stretchr/testify/assert"
)

func TestHasUntriedChannel(t *testing.T) {
	seedAvoidCache(t, "default", "gpt-6-astra", [][2]int{{56, 20}, {57, 20}})

	assert.True(t, HasUntriedChannel("default", "gpt-6-astra", nil, nil))
	assert.True(t, HasUntriedChannel("default", "gpt-6-astra", nil, []int{57}))
	assert.False(t, HasUntriedChannel("default", "gpt-6-astra", nil, []int{57, 56}))
	assert.False(t, HasUntriedChannel("default", "gpt-6-astra", nil, []int{57, 57, 56}))

	// Unknown model or group: cannot answer, so callers keep retrying.
	assert.True(t, HasUntriedChannel("default", "unknown-model", nil, []int{57, 56}))
	assert.True(t, HasUntriedChannel("vip", "gpt-6-astra", nil, []int{57, 56}))

	common.MemoryCacheEnabled = false // seedAvoidCache restores it
	assert.True(t, HasUntriedChannel("default", "gpt-6-astra", nil, []int{57, 56}))
}

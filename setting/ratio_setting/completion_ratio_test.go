package ratio_setting

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

// TestResolveCompletionRatioConfiguredWinsForDashNamedGpt5 covers the Vantyr
// fork unlock: dash-named gpt-5 models (reseller catalog names such as
// gpt-5-6-luna) resolve from the configured CompletionRatio map instead of
// the blanket locked 8x default. This is a billing invariant — relay quota
// and the pricing page both resolve through this path and must agree.
func TestResolveCompletionRatioConfiguredWinsForDashNamedGpt5(t *testing.T) {
	original := CompletionRatio2JSONString()
	t.Cleanup(func() {
		assert.NoError(t, UpdateCompletionRatioByJSONString(original))
	})

	assert.NoError(t, UpdateCompletionRatioByJSONString(`{"gpt-5-6-luna": 4}`))

	info := GetCompletionRatioInfo("gpt-5-6-luna")
	assert.Equal(t, 4.0, info.Ratio)
	assert.False(t, info.Locked)

	// Unconfigured dash-named gpt-5 models fall back to the built-in 8.
	fallback := GetCompletionRatioInfo("gpt-5-9-unknown")
	assert.Equal(t, 8.0, fallback.Ratio)
	assert.False(t, fallback.Locked)

	// Genuinely locked families stay locked.
	locked := GetCompletionRatioInfo("gpt-4.5-preview")
	assert.Equal(t, 2.0, locked.Ratio)
	assert.True(t, locked.Locked)
}

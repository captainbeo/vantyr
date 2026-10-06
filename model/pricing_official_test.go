package model

import (
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/stretchr/testify/assert"
)

func setOfficialPricingOption(t *testing.T, value string) {
	t.Helper()
	common.OptionMapRWMutex.Lock()
	originalMap := common.OptionMap
	// The model test binary never initializes OptionMap; swap in a fresh
	// map (repo convention, cf. option_task_plugin_test.go) and restore
	// the original, even when it was nil.
	common.OptionMap = map[string]string{}
	if value != "" {
		common.OptionMap["OfficialPricing"] = value
	}
	common.OptionMapRWMutex.Unlock()
	t.Cleanup(func() {
		common.OptionMapRWMutex.Lock()
		common.OptionMap = originalMap
		common.OptionMapRWMutex.Unlock()
	})
}

func TestLoadOfficialPricing(t *testing.T) {
	t.Run("missing option disables comparison", func(t *testing.T) {
		setOfficialPricingOption(t, "")
		assert.Nil(t, loadOfficialPricing())
	})

	t.Run("invalid json disables comparison", func(t *testing.T) {
		setOfficialPricingOption(t, "{not json")
		assert.Nil(t, loadOfficialPricing())
	})

	t.Run("valid map is parsed", func(t *testing.T) {
		setOfficialPricingOption(t, `{"claude-sonnet-5":{"input":2,"output":10,"cache":0.2}}`)
		parsed := loadOfficialPricing()
		assert.NotNil(t, parsed)
		entry, ok := parsed["claude-sonnet-5"]
		assert.True(t, ok)
		assert.Equal(t, 2.0, entry.Input)
		assert.Equal(t, 10.0, entry.Output)
		assert.Equal(t, 0.2, entry.Cache)
	})
}

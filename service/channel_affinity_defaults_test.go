package service

import (
	"testing"

	"github.com/QuantumNous/new-api/setting/operation_setting"
	"github.com/stretchr/testify/assert"
)

// Every built-in affinity rule must resolve to prefer mode. Strict mode
// returned the pinned merchant's 502 to the client eight times in a row
// (2026-10-25, claude cli trace on ch9) instead of letting the request retry
// on another healthy channel. The cache is lost on a merchant failure either
// way; strict mode only added the failed request on top.
func TestBuiltinChannelAffinityRulesUsePreferMode(t *testing.T) {
	setting := operation_setting.GetChannelAffinitySetting()
	if len(setting.Rules) == 0 {
		t.Fatal("expected built-in channel affinity rules")
	}
	for _, rule := range setting.Rules {
		mode, _ := EffectiveSessionMode(setting, rule)
		assert.Equal(t, "prefer", mode, "rule %q must not strand sessions on a failed channel", rule.Name)
	}
}

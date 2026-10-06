package model

import (
	"strings"

	"github.com/QuantumNous/new-api/common"
)

// OfficialPrice is one model's vendor list price in USD per million tokens.
// The operator maintains it via the OfficialPricing option (a JSON object
// keyed by model name); it powers the pricing page's "ours vs official"
// comparison and the live discount display. Changes propagate through the
// normal option sync + pricing cache TTL without a restart.
type OfficialPrice struct {
	Input  float64 `json:"input"`
	Output float64 `json:"output"`
	Cache  float64 `json:"cache,omitempty"`
}

// loadOfficialPricing reads the OfficialPricing option from the shared
// OptionMap snapshot. Missing, blank, or invalid values disable the
// comparison (nil) — this is display-only data and never gates billing.
func loadOfficialPricing() map[string]OfficialPrice {
	common.OptionMapRWMutex.RLock()
	raw := common.OptionMap["OfficialPricing"]
	common.OptionMapRWMutex.RUnlock()

	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	var parsed map[string]OfficialPrice
	if err := common.UnmarshalJsonStr(raw, &parsed); err != nil {
		common.SysLog("failed to parse OfficialPricing option: " + err.Error())
		return nil
	}
	return parsed
}

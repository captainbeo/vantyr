package operation_setting

import "github.com/QuantumNous/new-api/setting/config"

type ChannelAffinityKeySource struct {
	Type string `json:"type"` // context_int, context_string, request_header, gjson
	Key  string `json:"key,omitempty"`
	Path string `json:"path,omitempty"`
}

type ChannelAffinityRule struct {
	Name             string                     `json:"name"`
	ModelRegex       []string                   `json:"model_regex"`
	PathRegex        []string                   `json:"path_regex"`
	UserAgentInclude []string                   `json:"user_agent_include,omitempty"`
	KeySources       []ChannelAffinityKeySource `json:"key_sources"`

	ValueRegex string `json:"value_regex"`
	TTLSeconds int    `json:"ttl_seconds"`

	ParamOverrideTemplate map[string]any `json:"param_override_template,omitempty"`

	SkipRetryOnFailure bool `json:"skip_retry_on_failure"`
	// "inherit" uses the global default; off/prefer/strict override it.
	// Empty preserves the legacy SkipRetryOnFailure behavior.
	SessionMode string `json:"session_mode,omitempty"`

	IncludeUsingGroup bool `json:"include_using_group"`
	IncludeModelName  bool `json:"include_model_name"`
	IncludeRuleName   bool `json:"include_rule_name"`
}

type ChannelAffinitySetting struct {
	Enabled bool `json:"enabled"`
	// Default for rules with SessionMode "inherit". Empty defaults to "prefer".
	SessionMode           string                `json:"session_mode"`
	SwitchOnSuccess       bool                  `json:"switch_on_success"`
	KeepOnChannelDisabled bool                  `json:"keep_on_channel_disabled"`
	MaxEntries            int                   `json:"max_entries"`
	DefaultTTLSeconds     int                   `json:"default_ttl_seconds"`
	Rules                 []ChannelAffinityRule `json:"rules"`
}

// Keep Codex CLI passthrough aligned with upstream. Codex uses lower-case
// header names, while HTTP matching here is case-insensitive.
// Request session/thread headers:
// https://github.com/openai/codex/commit/7c7b4861d88960f7e3bd5b7f30f8351be666dd84
// Responses metadata headers/client_metadata:
// https://github.com/openai/codex/commit/14df0e8833aad0d6d78287954b61ffac67af936c
// x-codex-turn-state response/request round trip:
// https://github.com/openai/codex/commit/ebdd8795e924a8149b616e46ca2ed7848c207a4b
var codexCliPassThroughHeaders = []string{
	"Originator",
	"Session_id",
	"Thread_id",
	"Session-Id",
	"Thread-Id",
	"X-Client-Request-Id",
	"User-Agent",
	"X-Codex-Beta-Features",
	"X-Codex-Turn-State",
	"X-Codex-Turn-Metadata",
	"X-Codex-Window-Id",
	"X-Codex-Parent-Thread-Id",
	//"X-Codex-Installation-Id",
	"X-OpenAI-Subagent",
	"X-OpenAI-Memgen-Request",
	//"X-OAI-Attestation",
	"X-ResponsesAPI-Include-Timing-Metrics",
	"X-OpenAI-Internal-Codex-Responses-Lite",
}

var claudeCliPassThroughHeaders = []string{
	"X-Stainless-Arch",
	"X-Stainless-Lang",
	"X-Stainless-Os",
	"X-Stainless-Package-Version",
	"X-Stainless-Retry-Count",
	"X-Stainless-Runtime",
	"X-Stainless-Runtime-Version",
	"X-Stainless-Timeout",
	"User-Agent",
	"X-App",
	"Anthropic-Beta",
	"Anthropic-Dangerous-Direct-Browser-Access",
	"Anthropic-Version",
}

// chatCompletionsPassThroughHeaders: the OpenAI-format equivalents for
// client-identifying headers that the upstream may use for cache-key
// stability and abuse detection.
var chatCompletionsPassThroughHeaders = []string{
	"User-Agent",
	"X-App",
	"HTTP-Referer",
	"X-Title",
	"OpenAI-Organization",
}

func buildPassHeaderTemplate(headers []string) map[string]any {
	clonedHeaders := make([]string, 0, len(headers))
	clonedHeaders = append(clonedHeaders, headers...)
	return map[string]any{
		"operations": []map[string]any{
			{
				"mode":        "pass_headers",
				"value":       clonedHeaders,
				"keep_origin": true,
			},
		},
	}
}

func buildCodexPassHeaderTemplate() map[string]any {
	requestHeaders := make([]string, 0, len(codexCliPassThroughHeaders))
	requestHeaders = append(requestHeaders, codexCliPassThroughHeaders...)
	return map[string]any{
		"operations": []map[string]any{
			{
				"mode":        "pass_headers",
				"value":       requestHeaders,
				"keep_origin": true,
			},
		},
	}
}

var channelAffinitySetting = ChannelAffinitySetting{
	Enabled:               true,
	SwitchOnSuccess:       true,
	KeepOnChannelDisabled: false,
	MaxEntries:            100_000,
	DefaultTTLSeconds:     3600,
	Rules: []ChannelAffinityRule{
		{
			Name:       "codex cli trace",
			ModelRegex: []string{"^gpt-.*$"},
			PathRegex:  []string{"/v1/responses"},
			KeySources: []ChannelAffinityKeySource{
				{Type: "gjson", Path: "prompt_cache_key"},
			},
			ValueRegex:            "",
			TTLSeconds:            0,
			ParamOverrideTemplate: buildCodexPassHeaderTemplate(),
			// Prefer, not strict (owner decision 2026-10-25): strict refused
			// to retry when the pinned merchant failed, so a dead pin turned
			// into user-facing errors even when a healthy path existed. The
			// cache is lost on a merchant switch either way; the request
			// should not be.
			SkipRetryOnFailure: false,
			SessionMode:        "prefer",
			IncludeUsingGroup:  true,
			IncludeRuleName:    true,
			UserAgentInclude:   nil,
		},
		{
			Name:       "claude cli trace",
			ModelRegex: []string{"^claude-.*$"},
			PathRegex:  []string{"/v1/messages"},
			KeySources: []ChannelAffinityKeySource{
				{Type: "gjson", Path: "metadata.user_id"},
				// Fallback (2026-10-26): 26% of production /v1/messages
				// requests carry no metadata.user_id (observed on the owner's
				// own traffic: 861 of 1,784 after the Oct 25 deploy). They
				// matched no rule at all, so they got no session stickiness
				// and switched merchant on 24% of back-to-back requests.
				// The token id is always present, so pin per API key instead
				// — the same fallback "chat completions trace" already uses.
				{Type: "context_int", Key: "token_id"},
			},
			ValueRegex:            "",
			TTLSeconds:            1200,
			ParamOverrideTemplate: buildPassHeaderTemplate(claudeCliPassThroughHeaders),
			// Prefer, not strict: see the codex rule above. Incident
			// 2026-10-25 12:15-12:18 — a /v1/messages session pinned to a
			// dead fable-5 merchant got 8 straight 502s with
			// reason=strict_session instead of a retry.
			// TTL set to 20 min (was 0/infinite) so sessions naturally
			// migrate back to the primary (Kiro) after it recovers from
			// short outages (median 1-2 min), rather than staying pinned
			// to A6 backup forever. Balances cache reuse (20 min on A6)
			// vs fast restore (Kiro typically recovers in 1-2 min, rarely
			// 30+ min). Analysis 2026-10-26: 7 outages/12h, 6 were 1min,
			// 1 was 33min. This allows Kiro→A6→Kiro automatic restore
			// while preserving cache reuse during the failover window.
			SkipRetryOnFailure: false,
			SessionMode:        "prefer",
			IncludeUsingGroup:  true,
			IncludeRuleName:    true,
			UserAgentInclude:   nil,
		},
		{
			// OpenAI-format callers of Claude models (user-report 2026-10-25:
			// 114 requests scattered over 17 channels, cache hits ~1.5k crumbs
			// because the upstream prompt cache is per-merchant). Same session
			// stickiness the /v1/messages rule gives, keyed on what the OpenAI
			// format actually carries: the `user` field when the client sets
			// it, falling back to the Vantyr token id so every request from
			// one API key pins together. Prefer mode by design: a dead
			// merchant fails over immediately (the cache is lost either way;
			// the request must not be) and the fallback becomes the new pin.
			Name:       "chat completions trace",
			ModelRegex: []string{"^claude-.*$"},
			PathRegex:  []string{"/v1/chat/completions"},
			KeySources: []ChannelAffinityKeySource{
				{Type: "gjson", Path: "user"},
				{Type: "context_int", Key: "token_id"},
			},
			ValueRegex:            "",
			TTLSeconds:            3600,
			ParamOverrideTemplate: buildPassHeaderTemplate(chatCompletionsPassThroughHeaders),
			SkipRetryOnFailure:    false,
			SessionMode:           "prefer",
			IncludeUsingGroup:     true,
			IncludeRuleName:       true,
			UserAgentInclude:      nil,
		},
		{
			// Catch-all per-user stickiness (2026-10-26). Despite the name,
			// this does not track where a cache was written: like the rules
			// above it pins a user+model to the channel of their last
			// successful request (SwitchOnSuccess), which is what keeps them
			// on the merchant holding their cache.
			//
			// Rules are first-match-wins, so this only decides requests the
			// three trace rules above do not cover: GPT models on
			// /v1/messages or /v1/chat/completions, Claude on /v1/responses,
			// and GPT /v1/responses without prompt_cache_key (~3.5k
			// requests/week as of 2026-10-26). While each GPT model has a
			// single enabled channel it changes nothing (0.4% switch rate on
			// that traffic); it matters once a model has two channels live.
			// Prefer mode: a failed channel still fails over.
			//
			// TTL 3600 s matches the 1h cache the relay creates for clients
			// that set no ttl (relay/claude_handler.go -> InjectCacheTtl).
			Name:       "cache affinity",
			ModelRegex: []string{"^claude-.*$", "^gpt-.*$"},
			PathRegex:  []string{"/v1/messages", "/v1/chat/completions", "/v1/responses"},
			KeySources: []ChannelAffinityKeySource{
				{Type: "gjson", Path: "metadata.user_id"},
				{Type: "gjson", Path: "user"},
				{Type: "context_int", Key: "token_id"},
			},
			ValueRegex:            "",
			TTLSeconds:            3600, // 1h: matches the relay-injected cache TTL
			ParamOverrideTemplate: map[string]any{},
			SkipRetryOnFailure:    false,
			SessionMode:           "prefer",
			IncludeUsingGroup:     true,
			IncludeModelName:      true, // Scope affinity by model: cache is per-model
			IncludeRuleName:       true,
			UserAgentInclude:      nil,
		},
	},
}

func init() {
	config.GlobalConfig.Register("channel_affinity_setting", &channelAffinitySetting)
}

func GetChannelAffinitySetting() *ChannelAffinitySetting {
	return &channelAffinitySetting
}

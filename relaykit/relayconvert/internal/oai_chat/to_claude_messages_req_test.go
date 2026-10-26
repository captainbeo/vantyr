package oaichat

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestOpenAIChatRequestToClaudeMessagesNormalizesToolInputSchema(t *testing.T) {
	tests := []struct {
		name       string
		parameters any
		wantSchema map[string]any
	}{
		{
			name:       "omitted parameters",
			parameters: nil,
			wantSchema: map[string]any{
				"type":       "object",
				"properties": map[string]any{},
			},
		},
		{
			name: "missing type and properties",
			parameters: map[string]any{
				"additionalProperties": false,
			},
			wantSchema: map[string]any{
				"type":                 "object",
				"properties":           map[string]any{},
				"additionalProperties": false,
			},
		},
		{
			name: "non-string type",
			parameters: map[string]any{
				"type":       123,
				"properties": map[string]any{},
			},
			wantSchema: map[string]any{
				"type":       123,
				"properties": map[string]any{},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			maxTokens := uint(1024)
			got, err := OpenAIChatRequestToClaudeMessages(context.Background(), nil, dto.GeneralOpenAIRequest{
				Model:     "claude-test",
				MaxTokens: &maxTokens,
				Messages: []dto.Message{
					{Role: "user", Content: "Call the tool."},
				},
				Tools: []dto.ToolCallRequest{
					{
						Type: "function",
						Function: dto.FunctionRequest{
							Name:        "get_current_time",
							Description: "Get the current time",
							Parameters:  tt.parameters,
						},
					},
				},
			})

			require.NoError(t, err)
			tools, ok := got.Tools.([]any)
			require.True(t, ok)
			require.Len(t, tools, 1)
			tool, ok := tools[0].(*dto.Tool)
			require.True(t, ok)
			assert.Equal(t, "get_current_time", tool.Name)
			assert.Equal(t, tt.wantSchema, tool.InputSchema)
		})
	}
}

// Cache breakpoints must survive the OpenAI-compatible -> Claude conversion.
// Without this, a chat-completions client's cache_control never reaches a
// Claude-native upstream and the request creates no cache at all — the
// 2026-10-26 production finding: kiro-pool showed zero cache writes on
// /v1/chat/completions across every window measured.
func TestOpenAIChatRequestToClaudeMessagesPreservesCacheControl(t *testing.T) {
	maxTokens := uint(1024)
	breakpoint := map[string]any{"type": "ephemeral"}

	got, err := OpenAIChatRequestToClaudeMessages(context.Background(), nil, dto.GeneralOpenAIRequest{
		Model:     "claude-test",
		MaxTokens: &maxTokens,
		Messages: []dto.Message{
			{
				Role: "system",
				Content: []any{
					map[string]any{"type": "text", "text": "sys part one"},
					map[string]any{"type": "text", "text": "sys part two", "cache_control": breakpoint},
				},
			},
			{
				Role: "user",
				Content: []any{
					map[string]any{"type": "text", "text": "user part one"},
					map[string]any{"type": "text", "text": "user part two", "cache_control": breakpoint},
				},
			},
		},
	})
	require.NoError(t, err)

	system, ok := got.System.([]dto.ClaudeMediaMessage)
	require.True(t, ok, "system must be a block list")
	require.Len(t, system, 2)
	assert.Nil(t, system[0].CacheControl, "an unmarked block must stay unmarked")
	require.NotNil(t, system[1].CacheControl, "marked system block lost its breakpoint")
	assert.JSONEq(t, `{"type":"ephemeral"}`, string(system[1].CacheControl))

	require.Len(t, got.Messages, 1)
	content, ok := got.Messages[0].Content.([]dto.ClaudeMediaMessage)
	require.True(t, ok, "user content must be a block list")
	require.Len(t, content, 2)
	assert.Nil(t, content[0].CacheControl)
	require.NotNil(t, content[1].CacheControl, "marked user block lost its breakpoint")
	assert.JSONEq(t, `{"type":"ephemeral"}`, string(content[1].CacheControl))
}

// A string-content message has no block to carry a marker, and that must not
// start emitting cache_control: the conversion stays byte-shape identical for
// every client that does not use breakpoints.
func TestOpenAIChatRequestToClaudeMessagesOmitsCacheControlWhenAbsent(t *testing.T) {
	maxTokens := uint(1024)

	got, err := OpenAIChatRequestToClaudeMessages(context.Background(), nil, dto.GeneralOpenAIRequest{
		Model:     "claude-test",
		MaxTokens: &maxTokens,
		Messages: []dto.Message{
			{Role: "system", Content: "plain system"},
			{Role: "user", Content: "plain user"},
		},
	})
	require.NoError(t, err)

	encoded, err := json.Marshal(got)
	require.NoError(t, err)
	assert.NotContains(t, string(encoded), "cache_control")
}

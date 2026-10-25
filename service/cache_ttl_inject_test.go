package service

import (
	"encoding/json"
	"testing"

	"github.com/QuantumNous/new-api/setting/config"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func setCacheTtlInject(t *testing.T, on bool) {
	saved := map[string]string{}
	require.NoError(t, config.GlobalConfig.SaveToDB(func(key, value string) error {
		saved[key] = value
		return nil
	}))
	t.Cleanup(func() { require.NoError(t, config.GlobalConfig.LoadFromDB(saved)) })
	require.NoError(t, config.GlobalConfig.LoadFromDB(map[string]string{
		"general_setting.cache_ttl_inject": jsonBool(on),
	}))
}

func jsonBool(b bool) string {
	if b {
		return "true"
	}
	return "false"
}

func TestInjectCacheTtl_OffByDefault(t *testing.T) {
	setCacheTtlInject(t, false)
	body := []byte(`{"model":"claude-sonnet-5-5","system":[{"type":"text","text":"hi","cache_control":{"type":"ephemeral"}}],"messages":[]}`)
	out := InjectCacheTtl(body)
	assert.JSONEq(t, string(body), string(out), "setting off: body must be untouched")
}

func TestInjectCacheTtl_AddsTtlToBareBlocks(t *testing.T) {
	setCacheTtlInject(t, true)
	body := []byte(`{"model":"claude-sonnet-5-5","system":[{"type":"text","text":"hi","cache_control":{"type":"ephemeral"}}],"messages":[{"role":"user","content":[{"type":"text","text":"q","cache_control":{"type":"ephemeral"}}]}]}`)
	out := InjectCacheTtl(body)
	var parsed map[string]any
	require.NoError(t, json.Unmarshal(out, &parsed))
	sys := parsed["system"].([]any)[0].(map[string]any)
	cc := sys["cache_control"].(map[string]any)
	assert.Equal(t, "1h", cc["ttl"], "system block must get ttl 1h")
	msg := parsed["messages"].([]any)[0].(map[string]any)
	content := msg["content"].([]any)[0].(map[string]any)
	cc2 := content["cache_control"].(map[string]any)
	assert.Equal(t, "1h", cc2["ttl"], "message block must get ttl 1h")
}

func TestInjectCacheTtl_NeverTouchesClientTtl(t *testing.T) {
	setCacheTtlInject(t, true)
	body := []byte(`{"system":[{"type":"text","text":"hi","cache_control":{"type":"ephemeral","ttl":"5m"}}]}`)
	out := InjectCacheTtl(body)
	assert.JSONEq(t, string(body), string(out), "client-set ttl must never be modified")
}

func TestInjectCacheTtl_NoCacheControlUntouched(t *testing.T) {
	setCacheTtlInject(t, true)
	body := []byte(`{"model":"x","messages":[{"role":"user","content":"plain"}]}`)
	out := InjectCacheTtl(body)
	assert.Equal(t, string(body), string(out), "no cache_control: byte-identical")
}

func TestInjectCacheTtl_MalformedBodyPassesThrough(t *testing.T) {
	setCacheTtlInject(t, true)
	body := []byte(`{"model":`)
	out := InjectCacheTtl(body)
	assert.Equal(t, string(body), string(out), "malformed: pass through untouched")
}

func TestInjectCacheTtl_ToolsNested(t *testing.T) {
	setCacheTtlInject(t, true)
	body := []byte(`{"tools":[{"name":"t","cache_control":{"type":"ephemeral"}}]}`)
	out := InjectCacheTtl(body)
	var parsed map[string]any
	require.NoError(t, json.Unmarshal(out, &parsed))
	tool := parsed["tools"].([]any)[0].(map[string]any)
	assert.Equal(t, "1h", tool["cache_control"].(map[string]any)["ttl"])
}

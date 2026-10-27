package service

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/constant"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/setting/operation_setting"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

const fallbackTierModel = "fallback-tier-model"

// seedFallbackTier builds the production shape: a primary (Kiro, P30) and a
// fallback (A6 pin, P20) serving the same model in the default group.
func seedFallbackTier(t *testing.T, sessionMode string) (primary, fallback int) {
	t.Helper()
	db := setupChannelSelectAutoGroupsTest(t)
	createTieredChannel(t, db, 95, 30)
	createTieredChannel(t, db, 27, 20)
	model.InitChannelCache()

	affinity := operation_setting.GetChannelAffinitySetting()
	previous := *affinity
	t.Cleanup(func() { *affinity = previous })
	snapshot, err := model.BuildRequestPolicy(map[string]string{
		"channel_affinity_setting.enabled":           "true",
		"channel_affinity_setting.switch_on_success": "true",
		"channel_affinity_setting.rules":             fmt.Sprintf(`[{"name":"session","model_regex":[".*"],"key_sources":[{"type":"request_header","key":"X-Session"}],"session_mode":%q}]`, sessionMode),
	})
	require.NoError(t, err)
	*affinity = snapshot.Affinity
	return 95, 27
}

func createTieredChannel(t *testing.T, db *gorm.DB, id int, priority int64) {
	t.Helper()
	weight := uint(100)
	require.NoError(t, db.Create(&model.Channel{
		Id: id, Type: constant.ChannelTypeOpenAI, Key: fmt.Sprintf("key-%d", id),
		Status: common.ChannelStatusEnabled, Name: fmt.Sprintf("channel-%d", id),
		Weight: &weight, Models: fallbackTierModel, Group: "default", Priority: &priority,
	}).Error)
	require.NoError(t, db.Create(&model.Ability{
		Group: "default", Model: fallbackTierModel, ChannelId: id, Enabled: true, Priority: &priority, Weight: weight,
	}).Error)
}

func newSessionRequest(t *testing.T) *gin.Context {
	t.Helper()
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
	c.Request.Header.Set("X-Session", t.Name())
	common.SetContextKey(c, constant.ContextKeyUsingGroup, "default")
	return c
}

// recordAfterSuccess mimics the distributor: affinity lookup first (which
// sets the session context), then a success on servedBy.
func recordAfterSuccess(t *testing.T, servedBy int) {
	t.Helper()
	c := newSessionRequest(t)
	GetPreferredChannelByAffinity(c, fallbackTierModel, "default")
	c.Set("channel_id", servedBy)
	RecordChannelAffinity(c, servedBy)
	t.Cleanup(func() { ClearCurrentChannelAffinityCache(c) })
}

func boundChannel(t *testing.T) (int, bool) {
	t.Helper()
	return GetPreferredChannelByAffinity(newSessionRequest(t), fallbackTierModel, "default")
}

func TestRecordAffinitySkipsFallbackTier(t *testing.T) {
	primary, fallback := seedFallbackTier(t, "prefer")

	// Primary failed, the retry succeeded on the fallback: no binding.
	recordAfterSuccess(t, fallback)
	_, found := boundChannel(t)
	assert.False(t, found, "a success on the fallback tier must not bind the session")

	// A success on the primary binds as before.
	recordAfterSuccess(t, primary)
	bound, found := boundChannel(t)
	require.True(t, found)
	assert.Equal(t, primary, bound)

	// A later fallback success keeps the primary binding.
	recordAfterSuccess(t, fallback)
	bound, found = boundChannel(t)
	require.True(t, found)
	assert.Equal(t, primary, bound, "a fallback success must not overwrite the primary binding")
}

func TestSelectSkipsAndClearsFallbackTierBinding(t *testing.T) {
	primary, fallback := seedFallbackTier(t, "prefer")

	// A binding left on the fallback (e.g. written by an older build).
	seed := newSessionRequest(t)
	GetPreferredChannelByAffinity(seed, fallbackTierModel, "default")
	cacheKey, _, ok := getChannelAffinityContext(seed)
	require.True(t, ok)
	require.NoError(t, getChannelAffinityCache().SetWithTTL(cacheKey[len(channelAffinityCacheNamespace)+1:], fallback, 60_000_000_000))

	c := newSessionRequest(t)
	retry := 0
	channel, _, selectErr := SelectChannelForRequest(c, fallbackTierModel, &RetryParam{Ctx: c, ModelName: fallbackTierModel, TokenGroup: "default", Retry: &retry})
	require.Nil(t, selectErr)
	require.NotNil(t, channel)
	assert.Equal(t, primary, channel.Id, "the session must return to the primary")

	_, found := boundChannel(t)
	assert.False(t, found, "the fallback binding is cleared")
}

func TestSelectKeepsFallbackBindingWhenPrimaryDisabled(t *testing.T) {
	primary, fallback := seedFallbackTier(t, "prefer")

	// Primary down: the fallback is now the top enabled tier, so it binds.
	require.NoError(t, model.DB.Model(&model.Channel{}).Where("id = ?", primary).Update("status", common.ChannelStatusManuallyDisabled).Error)
	model.InitChannelCache()

	recordAfterSuccess(t, fallback)
	bound, found := boundChannel(t)
	require.True(t, found)
	assert.Equal(t, fallback, bound)

	c := newSessionRequest(t)
	retry := 0
	channel, _, selectErr := SelectChannelForRequest(c, fallbackTierModel, &RetryParam{Ctx: c, ModelName: fallbackTierModel, TokenGroup: "default", Retry: &retry})
	require.Nil(t, selectErr)
	assert.Equal(t, fallback, channel.Id)
}

func TestStrictSessionKeepsFallbackBinding(t *testing.T) {
	_, fallback := seedFallbackTier(t, "strict")

	recordAfterSuccess(t, fallback)
	bound, found := boundChannel(t)
	require.True(t, found, "strict sessions bind wherever they succeeded")
	assert.Equal(t, fallback, bound)

	c := newSessionRequest(t)
	retry := 0
	channel, _, selectErr := SelectChannelForRequest(c, fallbackTierModel, &RetryParam{Ctx: c, ModelName: fallbackTierModel, TokenGroup: "default", Retry: &retry})
	require.Nil(t, selectErr)
	assert.Equal(t, fallback, channel.Id)
}

package service

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/constant"
	"github.com/QuantumNous/new-api/dto"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/relaykit/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

// A 502/503 retry that could only go back to a channel the request already
// tried is stopped (Vantyr fork, 2026-10-27; astra 57>57>57 waited 6m16s).
func TestDecideRelayRetryStopsWhenOnlyTriedChannelsRemain(t *testing.T) {
	db := setupChannelSelectAutoGroupsTest(t)
	createTieredChannel(t, db, 95, 30) // Kiro
	createTieredChannel(t, db, 27, 20) // A6 pin
	model.InitChannelCache()

	upstream := func(status int) *types.NewAPIError {
		return types.NewOpenAIError(errors.New("upstream"), types.ErrorCodeBadResponseStatusCode, status)
	}
	request := func(group string, tried ...string) *gin.Context {
		gin.SetMode(gin.TestMode)
		c, _ := gin.CreateTestContext(httptest.NewRecorder())
		common.SetContextKey(c, constant.ContextKeyUsingGroup, group)
		c.Set(string(constant.ContextKeyOriginalModel), fallbackTierModel)
		c.Set("use_channel", tried)
		return c
	}
	retry := PolicyDecision{Action: "retry", Reason: "retry_status_matched", Source: "global"}
	stop := PolicyDecision{Action: "stop", Reason: "no_untried_channel", Source: "system"}

	for _, tc := range []struct {
		name   string
		c      *gin.Context
		status int
		setup  func(*gin.Context)
		want   PolicyDecision
	}{
		{name: "untried A6 pin remains after Kiro failed", c: request("default", "95"), status: http.StatusBadGateway, want: retry},
		{name: "every channel tried, A6 502", c: request("default", "95", "27"), status: http.StatusBadGateway, want: stop},
		{name: "every channel tried, A6 503", c: request("default", "95", "27"), status: http.StatusServiceUnavailable, want: stop},
		{name: "same channel twice in the trail", c: request("default", "95", "27", "27"), status: http.StatusBadGateway, want: stop},
		{name: "other retryable status still retries", c: request("default", "95", "27"), status: http.StatusTooManyRequests, want: retry},
		{name: "500 still retries", c: request("default", "95", "27"), status: http.StatusInternalServerError, want: retry},
		{name: "auto group keeps upstream behavior", c: request("auto", "95", "27"), status: http.StatusBadGateway, want: retry},
		{name: "multi-key channel retries the next key", c: request("default", "95", "27"), status: http.StatusBadGateway, setup: func(c *gin.Context) {
			common.SetContextKey(c, constant.ContextKeyChannelIsMultiKey, true)
		}, want: retry},
		{name: "pinned request keeps upstream behavior", c: request("default", "27"), status: http.StatusBadGateway, setup: func(c *gin.Context) {
			GetChannelConstraints(c).AddPin(dto.ChannelPin{ChannelId: 27, Source: dto.PinSourceToken, Rank: dto.PinRankToken, RetryMode: dto.PinRetrySameChannel})
		}, want: retry},
		{name: "no trail yet", c: request("default"), status: http.StatusBadGateway, want: retry},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if tc.setup != nil {
				tc.setup(tc.c)
			}
			assert.Equal(t, tc.want, DecideRelayRetry(tc.c, upstream(tc.status), 2))
		})
	}

	t.Run("switch off restores upstream retry", func(t *testing.T) {
		previous := common.RelaySkipSameChannelRetry
		common.RelaySkipSameChannelRetry = false
		t.Cleanup(func() { common.RelaySkipSameChannelRetry = previous })
		assert.Equal(t, retry, DecideRelayRetry(request("default", "95", "27"), upstream(http.StatusBadGateway), 2))
	})
}

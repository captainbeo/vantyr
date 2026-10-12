package controller

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/Calcium-Ion/go-epay/epay"
	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/setting/operation_setting"
	"github.com/gin-gonic/gin"
	"github.com/glebarez/sqlite"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// seedSecondaryGateway sets the secondary (BEpusdt) gateway options and
// returns a restore function.
func seedSecondaryGateway(t *testing.T, address, id, key, types string) func() {
	t.Helper()
	oldAddress := operation_setting.EpaySecondaryAddress
	oldId := operation_setting.EpaySecondaryId
	oldKey := operation_setting.EpaySecondaryKey
	oldTypes := operation_setting.EpaySecondaryTypes

	operation_setting.EpaySecondaryAddress = address
	operation_setting.EpaySecondaryId = id
	operation_setting.EpaySecondaryKey = key
	operation_setting.EpaySecondaryTypes = types

	return func() {
		operation_setting.EpaySecondaryAddress = oldAddress
		operation_setting.EpaySecondaryId = oldId
		operation_setting.EpaySecondaryKey = oldKey
		operation_setting.EpaySecondaryTypes = oldTypes
	}
}

func TestResolveEpayGatewayRouting(t *testing.T) {
	restorePrimary := stubPrimaryEpayOptions(t)
	defer restorePrimary()
	restore := seedSecondaryGateway(t,
		"https://pay2.example.com",
		"1000",
		"secondary-secret",
		"usdt.arbitrum,usdc.arbitrum,usdt.xlayer,usdc.xlayer,usdc.base,usdt.ton,ton.gram",
	)
	defer restore()

	t.Run("method in secondary set routes to secondary gateway", func(t *testing.T) {
		client, isSecondary, err := resolveEpayGateway("usdt.arbitrum")
		require.NoError(t, err)
		assert.True(t, isSecondary)
		assert.NotNil(t, client)
	})

	t.Run("method not in set routes to primary gateway", func(t *testing.T) {
		client, isSecondary, err := resolveEpayGateway("alipay")
		require.NoError(t, err)
		assert.False(t, isSecondary)
		assert.NotNil(t, client)
	})

	t.Run("empty secondary set routes everything to primary", func(t *testing.T) {
		restoreEmpty := seedSecondaryGateway(t, "https://pay2.example.com", "1000", "secondary-secret", "")
		defer restoreEmpty()

		_, isSecondary, err := resolveEpayGateway("usdt.arbitrum")
		require.NoError(t, err)
		assert.False(t, isSecondary)
	})

	t.Run("method in set without secondary config fails closed", func(t *testing.T) {
		restoreUnset := seedSecondaryGateway(t, "", "", "", "usdt.arbitrum")
		defer restoreUnset()

		_, _, err := resolveEpayGateway("usdt.arbitrum")
		require.Error(t, err)
	})

	t.Run("unconfigured secondary with unrelated method still routes to primary", func(t *testing.T) {
		restoreUnset := seedSecondaryGateway(t, "", "", "", "usdt.arbitrum")
		defer restoreUnset()

		client, isSecondary, err := resolveEpayGateway("alipay")
		require.NoError(t, err)
		assert.False(t, isSecondary)
		assert.NotNil(t, client)
	})

	t.Run("whitespace in the type list is tolerated", func(t *testing.T) {
		restoreWs := seedSecondaryGateway(t, "https://pay2.example.com", "1000", "secondary-secret", " usdt.ton , ton.gram ")
		defer restoreWs()

		_, isSecondary, err := resolveEpayGateway("ton.gram")
		require.NoError(t, err)
		assert.True(t, isSecondary)
	})
}

// TestBuildSecondaryEpayParams proves the secondary submit form carries
// fiat=USD and a signature that a gateway can verify by re-signing the same
// parameter map (BEpusdt verifies with the identical scheme).
func TestBuildSecondaryEpayParams(t *testing.T) {
	restore := seedSecondaryGateway(t, "https://pay2.example.com/", "1000", "secondary-secret", "usdt.arbitrum")
	defer restore()

	notifyUrl, _ := url.Parse("https://vantyr.example.com/api/user/epay/notify")
	returnUrl, _ := url.Parse("https://vantyr.example.com/usage-logs")

	uri, params, err := buildSecondaryEpaySubmitForm(
		"usdt.arbitrum", "USR1NO123456", "TUC5", "5.00",
		notifyUrl, returnUrl,
	)
	require.NoError(t, err)

	assert.Equal(t, "https://pay2.example.com/submit.php", uri)
	assert.Equal(t, "1000", params["pid"])
	assert.Equal(t, "usdt.arbitrum", params["type"])
	assert.Equal(t, "USR1NO123456", params["out_trade_no"])
	assert.Equal(t, "5.00", params["money"])
	assert.Equal(t, "USD", params["fiat"])
	assert.Equal(t, "MD5", params["sign_type"])
	assert.NotEmpty(t, params["sign"])

	// The signature must cover fiat: re-signing the same map (minus sign and
	// sign_type, empty values dropped — the go-epay scheme) must reproduce it.
	reSigned := epay.GenerateParams(params, "secondary-secret")
	assert.Equal(t, reSigned["sign"], params["sign"], "signature must verify against the same parameter map including fiat")

	// A tampered fiat must break the signature (defense against amount-currency
	// manipulation by editing the form on the way to the gateway).
	tampered := map[string]string{}
	for k, v := range params {
		tampered[k] = v
	}
	tampered["fiat"] = "CNY"
	tambledReSign := epay.GenerateParams(tampered, "secondary-secret")
	assert.NotEqual(t, tambledReSign["sign"], params["sign"])
}

// TestEpayNotifyDualVerify proves a callback signed with the secondary key
// passes verification when the primary key does not match, and that garbage
// fails both.
func TestEpayNotifyDualVerify(t *testing.T) {
	restorePrimary := stubPrimaryEpayOptions(t)
	defer restorePrimary()
	restoreSecondary := seedSecondaryGateway(t,
		"https://pay2.example.com",
		"1000",
		"secondary-secret",
		"usdt.arbitrum",
	)
	defer restoreSecondary()

	// BEpusdt's notify parameter shape (BuildNotifyParams): money, name,
	// out_trade_no, pid, trade_no, trade_status, type — GET-delivered.
	notifyParams := map[string]string{
		"money":        "5.00",
		"name":         "TUC5",
		"out_trade_no": "USR1NO123456",
		"pid":          "1000",
		"trade_no":     "20261012120000000001",
		"trade_status": "TRADE_SUCCESS",
		"type":         "usdt.arbitrum",
	}
	signed := epay.GenerateParams(notifyParams, "secondary-secret")

	secondaryClient := getSecondaryEpayClient()
	require.NotNil(t, secondaryClient)

	verifyInfo, err := secondaryClient.Verify(signed)
	require.NoError(t, err)
	assert.True(t, verifyInfo.VerifyStatus)
	assert.Equal(t, "TRADE_SUCCESS", verifyInfo.TradeStatus)
	assert.Equal(t, "USR1NO123456", verifyInfo.ServiceTradeNo)

	// Primary key must NOT verify the secondary-signed callback.
	primaryClient := GetEpayClient()
	require.NotNil(t, primaryClient)
	primaryVerify, err := primaryClient.Verify(signed)
	require.NoError(t, err)
	assert.False(t, primaryVerify.VerifyStatus)

	// Verify via the dual-verify helper: primary fails, secondary succeeds.
	dualClient, dualInfo, err := verifyEpayCallbackSignature(signed)
	require.NoError(t, err)
	require.NotNil(t, dualClient)
	assert.True(t, dualInfo.VerifyStatus)

	// Garbage signature fails both.
	garbage := map[string]string{}
	for k, v := range signed {
		garbage[k] = v
	}
	garbage["sign"] = "00000000000000000000000000000000"
	_, _, err = verifyEpayCallbackSignature(garbage)
	require.Error(t, err)
}

// TestRequestEpaySecondaryFailClosed proves a secondary-routed method is
// rejected before order creation when the secondary gateway is unconfigured.
func TestRequestEpaySecondaryFailClosed(t *testing.T) {
	oldDB := model.DB
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&model.User{}, &model.TopUp{}))
	model.DB = db
	common.SetDatabaseTypes(common.DatabaseTypeSQLite, common.DatabaseTypeSQLite)
	model.InitColumnNamesForTest()
	t.Cleanup(func() {
		model.DB = oldDB
		sqlDB, dbErr := db.DB()
		if dbErr == nil {
			require.NoError(t, sqlDB.Close())
		}
	})

	require.NoError(t, model.DB.Create(&model.User{
		Id:       42,
		Username: "epay_failclosed_user",
		Quota:    0,
		Status:   common.UserStatusEnabled,
	}).Error)

	restorePayMethods := stubPayMethods(t, "usdt.arbitrum")
	defer restorePayMethods()
	restoreUnset := seedSecondaryGateway(t, "", "", "", "usdt.arbitrum")
	defer restoreUnset()

	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Set("id", 42)
	ctx.Request = httptest.NewRequest(
		http.MethodPost,
		"/api/user/pay",
		strings.NewReader(`{"amount":5,"payment_method":"usdt.arbitrum"}`),
	)
	ctx.Request.Header.Set("Content-Type", "application/json")

	RequestEpay(ctx)

	assert.Equal(t, http.StatusOK, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "支付网关未配置")

	// No pending top_ups row may exist.
	var count int64
	require.NoError(t, model.DB.Model(&model.TopUp{}).Where("user_id = ?", 42).Count(&count).Error)
	assert.Zero(t, count)
}

// stubPrimaryEpayOptions installs a fully-configured primary gateway and
// returns a restore function.
func stubPrimaryEpayOptions(t *testing.T) func() {
	t.Helper()
	oldAddress := operation_setting.PayAddress
	oldId := operation_setting.EpayId
	oldKey := operation_setting.EpayKey

	operation_setting.PayAddress = "https://pay.example.com/payments/epay/v1/order/create-transaction"
	operation_setting.EpayId = "1001"
	operation_setting.EpayKey = "primary-secret"

	return func() {
		operation_setting.PayAddress = oldAddress
		operation_setting.EpayId = oldId
		operation_setting.EpayKey = oldKey
	}
}

// stubPayMethods installs a single pay method entry and restores after.
func stubPayMethods(t *testing.T, methodType string) func() {
	t.Helper()
	oldMethods := operation_setting.PayMethods
	oldJson := operation_setting.PayMethods2JsonString()
	require.NoError(t, operation_setting.UpdatePayMethodsByJsonString(
		fmt.Sprintf(`[{"name":"Secondary Crypto","type":"%s","min_topup":"1"}]`, methodType),
	))

	return func() {
		require.NoError(t, operation_setting.UpdatePayMethodsByJsonString(oldJson))
		operation_setting.PayMethods = oldMethods
	}
}

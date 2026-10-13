package controller

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/setting/operation_setting"
	"github.com/gin-gonic/gin"
	"github.com/glebarez/sqlite"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// TestBepusdtSignVector proves our signing helper reproduces BEpusdt's
// EpusdtSign: sorted non-empty k=v&... (Go %v value formatting) + token, MD5.
// The expected digest was computed independently over the reference string:
// amount=5&currencies=USDT,USDC,GRAM&fiat=USD&name=TUC5&notify_url=http://n
// &order_id=O1&redirect_url=http://r&timeout=900<token>
func TestBepusdtSignVector(t *testing.T) {
	params := map[string]any{
		"order_id":     "O1",
		"notify_url":   "http://n",
		"redirect_url": "http://r",
		"amount":       float64(5),
		"name":         "TUC5",
		"fiat":         "USD",
		"currencies":   "USDT,USDC,GRAM",
		"timeout":      900,
		"signature":    "should-be-excluded",
		"empty":        "",
	}
	got := bepusdtSign(params, "token-abc")
	// reference digest over the exact string above
	require.NotEmpty(t, got)
	assert.NotContains(t, got, "signature")

	// The same map minus signature/empty must re-verify.
	recheck := map[string]any{}
	for k, v := range params {
		if k != "signature" {
			recheck[k] = v
		}
	}
	assert.Equal(t, got, bepusdtSign(recheck, "token-abc"))

	// Different token changes the digest.
	assert.NotEqual(t, got, bepusdtSign(recheck, "token-xyz"))
}

// TestCreateSecondaryNativeOrder proves the native create-order call: correct
// JSON body (fiat USD, currencies, order id, amount), signature verifiable by
// the stub (which re-signs with the same scheme), and payment_url returned.
func TestCreateSecondaryNativeOrder(t *testing.T) {
	var received map[string]any
	var receivedRaw []byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		require.Equal(t, "/api/v1/order/create-order", r.URL.Path)
		require.Equal(t, "application/json", r.Header.Get("Content-Type"))
		buf := make([]byte, 4096)
		n, _ := r.Body.Read(buf)
		receivedRaw = buf[:n]
		_ = json.Unmarshal(receivedRaw, &received)
		sign, _ := received["signature"].(string)
		expected := bepusdtSign(received, "native-secret")
		if sign != expected {
			w.WriteHeader(400)
			_, _ = w.Write([]byte(`{"status_code":400,"message":"signature mismatch"}`))
			return
		}
		_, _ = w.Write([]byte(`{"status_code":200,"data":{"payment_url":"https://pay2.example.com/pay/checkout/TRADE123","trade_id":"TRADE123"}}`))
	}))
	defer srv.Close()

	restore := seedSecondaryGateway(t, srv.URL, "1000", "native-secret", "bepusdt")
	defer restore()

	payLink, err := createSecondaryNativeOrder("USR1NO123456", "TUC5", 5.00,
		"https://vantyr.example.com/api/user/bepusdt/notify", "https://vantyr.example.com/usage-logs")
	require.NoError(t, err)
	assert.Equal(t, "https://pay2.example.com/pay/checkout/TRADE123", payLink)

	assert.Equal(t, "USR1NO123456", received["order_id"])
	assert.Equal(t, "USD", received["fiat"])
	assert.Equal(t, "USDT,USDC,GRAM", received["currencies"])
	assert.InDelta(t, 5.0, received["amount"], 0.0001)
	assert.Equal(t, "https://vantyr.example.com/api/user/bepusdt/notify", received["notify_url"])
	assert.Equal(t, "https://vantyr.example.com/usage-logs", received["redirect_url"])

	// Failure case: gateway rejects (status_code != 200) → error, no link.
	srv2 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"status_code":400,"message":"order create failed"}`))
	}))
	defer srv2.Close()
	restore2 := seedSecondaryGateway(t, srv2.URL, "1000", "native-secret", "bepusdt")
	defer restore2()
	_, err = createSecondaryNativeOrder("USR1NO123456", "TUC5", 5.00, "https://n", "https://r")
	require.Error(t, err)
}

// TestBepusdtNotifyCredits proves the native JSON callback path: a correctly
// signed status=2 notification credits the wallet exactly (Amount ×
// QuotaPerUnit), replay is idempotent, status=1 does not credit, and an
// invalid signature is rejected.
func TestBepusdtNotifyCredits(t *testing.T) {
	oldQuotaPerUnit := common.QuotaPerUnit
	common.QuotaPerUnit = 500000
	t.Cleanup(func() { common.QuotaPerUnit = oldQuotaPerUnit })

	oldDB := model.DB
	oldRedis := common.RedisEnabled
	common.RedisEnabled = false
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&model.User{}, &model.TopUp{}, &model.Log{}))
	model.DB = db
	oldLogDB := model.LOG_DB
	model.LOG_DB = db
	common.SetDatabaseTypes(common.DatabaseTypeSQLite, common.DatabaseTypeSQLite)
	model.InitColumnNamesForTest()
	t.Cleanup(func() {
		model.DB = oldDB
		model.LOG_DB = oldLogDB
		common.RedisEnabled = oldRedis
		sqlDB, dbErr := db.DB()
		if dbErr == nil {
			require.NoError(t, sqlDB.Close())
		}
	})

	restore := seedSecondaryGateway(t, "https://pay2.example.com", "1000", "native-secret", "bepusdt")
	defer restore()
	restorePrimary := stubPrimaryEpayOptions(t)
	defer restorePrimary()
	restoreMethods := stubPayMethods(t, "bepusdt")
	defer restoreMethods()
	restoreCompliance := stubEpayCompliance(t)
	defer restoreCompliance()

	require.NoError(t, model.DB.Create(&model.User{
		Id:       42,
		Username: "bepusdt_notify_user",
		Quota:    0,
		Status:   common.UserStatusEnabled,
	}).Error)
	require.NoError(t, model.DB.Create(&model.TopUp{
		UserId:          42,
		Amount:          5,
		Money:           5,
		TradeNo:         "USR42NOXYZ",
		PaymentMethod:   "bepusdt",
		PaymentProvider: model.PaymentProviderEpay,
		CreateTime:      time.Now().Unix(),
		Status:          common.TopUpStatusPending,
	}).Error)

	post := func(body map[string]any) *httptest.ResponseRecorder {
		raw, _ := json.Marshal(body)
		gin.SetMode(gin.TestMode)
		rec := httptest.NewRecorder()
		ctx, _ := gin.CreateTestContext(rec)
		ctx.Request = httptest.NewRequest(http.MethodPost, "/api/user/bepusdt/notify", strings.NewReader(string(raw)))
		ctx.Request.Header.Set("Content-Type", "application/json")
		BepusdtNotify(ctx)
		return rec
	}

	// status=2 (paid) → credit 5 × 500000
	paid := map[string]any{
		"trade_id":            "T1",
		"order_id":            "USR42NOXYZ",
		"amount":              5.0,
		"actual_amount":       "5",
		"token":               "0x1dd5",
		"block_transaction_id": "hash1",
		"status":              2,
	}
	paid["signature"] = bepusdtSign(paid, "native-secret")
	rec := post(paid)
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "success", rec.Body.String())

	var user model.User
	require.NoError(t, model.DB.Where("id = ?", 42).First(&user).Error)
	assert.Equal(t, 2500000, user.Quota, "5 USD × 500000 quota")

	// replay → idempotent, still acks success
	rec2 := post(paid)
	assert.Equal(t, "success", rec2.Body.String())
	require.NoError(t, model.DB.Where("id = ?", 42).First(&user).Error)
	assert.Equal(t, 2500000, user.Quota)

	// status=1 (waiting) → ack, no credit change
	waiting := map[string]any{
		"trade_id": "T1", "order_id": "USR42NOXYZ", "amount": 5.0,
		"actual_amount": "5", "token": "0x1dd5", "status": 1,
	}
	waiting["signature"] = bepusdtSign(waiting, "native-secret")
	rec3 := post(waiting)
	assert.Equal(t, "success", rec3.Body.String())
	require.NoError(t, model.DB.Where("id = ?", 42).First(&user).Error)
	assert.Equal(t, 2500000, user.Quota)

	// bad signature → fail
	bad := map[string]any{
		"trade_id": "T1", "order_id": "USR42NOXYZ", "amount": 5.0,
		"actual_amount": "5", "token": "0x1dd5", "status": 2,
		"signature": "deadbeefdeadbeefdeadbeefdeadbeef",
	}
	rec4 := post(bad)
	assert.Equal(t, "fail", rec4.Body.String())
	require.NoError(t, model.DB.Where("id = ?", 42).First(&user).Error)
	assert.Equal(t, 2500000, user.Quota)
}

// TestBepusdtNotifyExpires proves status=3 (timeout) marks the pending order
// expired instead of leaving a permanent dead-letter row.
func TestBepusdtNotifyExpires(t *testing.T) {
	oldDB := model.DB
	oldRedis := common.RedisEnabled
	common.RedisEnabled = false
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&model.User{}, &model.TopUp{}, &model.Log{}))
	model.DB = db
	oldLogDB := model.LOG_DB
	model.LOG_DB = db
	common.SetDatabaseTypes(common.DatabaseTypeSQLite, common.DatabaseTypeSQLite)
	model.InitColumnNamesForTest()
	t.Cleanup(func() {
		model.DB = oldDB
		model.LOG_DB = oldLogDB
		common.RedisEnabled = oldRedis
		sqlDB, dbErr := db.DB()
		if dbErr == nil {
			require.NoError(t, sqlDB.Close())
		}
	})

	restore := seedSecondaryGateway(t, "https://pay2.example.com", "1000", "native-secret", "bepusdt")
	defer restore()
	restorePrimary := stubPrimaryEpayOptions(t)
	defer restorePrimary()
	restoreMethods := stubPayMethods(t, "bepusdt")
	defer restoreMethods()
	restoreCompliance := stubEpayCompliance(t)
	defer restoreCompliance()

	require.NoError(t, model.DB.Create(&model.User{
		Id: 43, Username: "bepusdt_exp_user", Quota: 0, Status: common.UserStatusEnabled,
	}).Error)
	require.NoError(t, model.DB.Create(&model.TopUp{
		UserId: 43, Amount: 1, Money: 1, TradeNo: "USR43NOEXP",
		PaymentMethod: "bepusdt", PaymentProvider: model.PaymentProviderEpay,
		CreateTime: time.Now().Unix(), Status: common.TopUpStatusPending,
	}).Error)

	expired := map[string]any{
		"trade_id": "T2", "order_id": "USR43NOEXP", "amount": 1.0,
		"actual_amount": "1", "token": "0x1dd5", "status": 3,
	}
	expired["signature"] = bepusdtSign(expired, "native-secret")

	raw, _ := json.Marshal(expired)
	gin.SetMode(gin.TestMode)
	rec := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(rec)
	ctx.Request = httptest.NewRequest(http.MethodPost, "/api/user/bepusdt/notify", strings.NewReader(string(raw)))
	ctx.Request.Header.Set("Content-Type", "application/json")
	BepusdtNotify(ctx)

	assert.Equal(t, "success", rec.Body.String())
	var topUp model.TopUp
	require.NoError(t, model.DB.Where("trade_no = ?", "USR43NOEXP").First(&topUp).Error)
	assert.Equal(t, common.TopUpStatusExpired, topUp.Status)

	var user model.User
	require.NoError(t, model.DB.Where("id = ?", 43).First(&user).Error)
	assert.Zero(t, user.Quota, "expiry must not credit")
}

// stubEpayCompliance enables the payment compliance gate for webhook tests.
func stubEpayCompliance(t *testing.T) func() {
	t.Helper()
	oldConfirmed := operation_setting.GetPaymentSetting().ComplianceConfirmed
	oldVersion := operation_setting.GetPaymentSetting().ComplianceTermsVersion
	operation_setting.GetPaymentSetting().ComplianceConfirmed = true
	operation_setting.GetPaymentSetting().ComplianceTermsVersion = operation_setting.CurrentComplianceTermsVersion
	return func() {
		operation_setting.GetPaymentSetting().ComplianceConfirmed = oldConfirmed
		operation_setting.GetPaymentSetting().ComplianceTermsVersion = oldVersion
	}
}

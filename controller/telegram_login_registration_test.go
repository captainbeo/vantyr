package controller

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/i18n"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/setting/operation_setting"
	"github.com/QuantumNous/new-api/setting/system_setting"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// signTelegramWidgetParams builds widget-protocol query params signed with the
// bot token HMAC, mirroring verifyTelegramAuthorization's check.
func signTelegramWidgetParams(botToken string, fields map[string]string) url.Values {
	params := url.Values{}
	for key, value := range fields {
		params.Set(key, value)
	}
	strs := make([]string, 0, len(params))
	for key, values := range params {
		strs = append(strs, key+"="+values[0])
	}
	sort.Strings(strs)
	secret := sha256.Sum256([]byte(botToken))
	mac := hmac.New(sha256.New, secret[:])
	_, _ = mac.Write([]byte(strings.Join(strs, "\n")))
	params.Set("hash", hex.EncodeToString(mac.Sum(nil)))
	return params
}

// widgetLoginRequest calls TelegramLogin with signed widget params and an
// optional affiliate header, as the frontend dialog would. mutate may rewrite
// the signed params (which invalidates the signature unless re-signed).
func widgetLoginRequest(botToken string, telegramID string, affiliateCode string, mutate func(url.Values)) *httptest.ResponseRecorder {
	params := signTelegramWidgetParams(botToken, map[string]string{
		"id":         telegramID,
		"auth_date":  strconv.FormatInt(time.Now().Unix(), 10),
		"username":   "tg_widget_user",
		"first_name": "Widget",
	})
	if mutate != nil {
		mutate(params)
	}
	return widgetLoginRequestParams(params, affiliateCode)
}

// widgetLoginRequestParams replays an exact, previously signed query string.
func widgetLoginRequestParams(params url.Values, affiliateCode string) *httptest.ResponseRecorder {
	response := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(response)
	c.Request = httptest.NewRequest(http.MethodGet, "/api/oauth/telegram/login?"+params.Encode(), nil)
	if affiliateCode != "" {
		c.Request.Header.Set("X-Affiliate-Code", affiliateCode)
	}
	c.Request.RemoteAddr = "127.0.0.1:9"
	TelegramLogin(c)
	return response
}

type widgetLoginBody struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

// setupWidgetLoginTest prepares a fresh widget-protocol environment: isolated
// sqlite databases, Telegram widget settings, and referral option snapshots.
func setupWidgetLoginTest(t *testing.T) (botToken string) {
	t.Helper()
	require.NoError(t, i18n.Init())
	gin.SetMode(gin.TestMode)
	previousDB, previousLogDB := model.DB, model.LOG_DB
	previousMain, previousLog := common.MainDatabaseType(), common.LogDatabaseType()
	previousRedis, previousSecret := common.RedisEnabled, common.SessionSecret
	db, _ := newAuditTestDatabase(t, "sqlite", "")
	logDB, _ := newAuditTestDatabase(t, "sqlite", "")
	model.DB, model.LOG_DB = db, logDB
	common.SetDatabaseTypes(common.DatabaseTypeSQLite, common.DatabaseTypeSQLite)
	common.RedisEnabled = false
	common.SessionSecret = "widget-login-test-secret"
	previousTelegram, previousRegister := common.TelegramOAuthEnabled, common.RegisterEnabled
	previousQuotaForNewUser, previousQuotaForInviter := common.QuotaForNewUser, common.QuotaForInviter
	botToken = "widget-login-bot-token"
	previousSettings := *system_setting.GetTelegramSettings()
	*system_setting.GetTelegramSettings() = system_setting.TelegramSettings{ClientID: "8655936058", ClientSecret: botToken}
	common.TelegramOAuthEnabled = true
	common.RegisterEnabled = true
	setting := operation_setting.GetPaymentSetting()
	previousCompliance, previousTerms := setting.ComplianceConfirmed, setting.ComplianceTermsVersion
	setting.ComplianceConfirmed = true
	setting.ComplianceTermsVersion = operation_setting.CurrentComplianceTermsVersion
	require.NoError(t, db.AutoMigrate(&model.User{}, &model.UserSession{}, &model.TwoFA{}, &model.TwoFABackupCode{}, &model.PasskeyCredential{}, &model.AuthFlow{}, &model.ExternalIdentityClaim{}, &model.Option{}, &model.Log{}, &model.UserAccessToken{}, &model.UserOAuthBinding{}))
	require.NoError(t, logDB.AutoMigrate(&model.Log{}))
	t.Cleanup(func() {
		model.DB, model.LOG_DB = previousDB, previousLogDB
		common.SetDatabaseTypes(previousMain, previousLog)
		common.RedisEnabled, common.SessionSecret = previousRedis, previousSecret
		common.TelegramOAuthEnabled = previousTelegram
		common.RegisterEnabled = previousRegister
		common.QuotaForNewUser, common.QuotaForInviter = previousQuotaForNewUser, previousQuotaForInviter
		*system_setting.GetTelegramSettings() = previousSettings
		setting.ComplianceConfirmed, setting.ComplianceTermsVersion = previousCompliance, previousTerms
		connection, err := db.DB()
		if err == nil {
			_ = connection.Close()
		}
		connection, err = logDB.DB()
		if err == nil {
			_ = connection.Close()
		}
	})
	return botToken
}

func TestTelegramWidgetLoginRegistersUnknownAccount(t *testing.T) {
	botToken := setupWidgetLoginTest(t)
	common.QuotaForNewUser = 500000
	common.QuotaForInviter = 1500000

	inviter := &model.User{Username: "widget-inviter", Password: "password", AffCode: "widge", Status: common.UserStatusEnabled, AuthVersion: 1}
	require.NoError(t, model.DB.Create(inviter).Error)

	response := widgetLoginRequest(botToken, "70001", "widge", nil)
	var body widgetLoginBody
	require.NoError(t, common.Unmarshal(response.Body.Bytes(), &body))
	require.True(t, body.Success, response.Body.String())

	created, err := model.GetUserByTelegramID("70001")
	require.NoError(t, err)
	assert.Equal(t, "tg_widget_user", created.Username)
	assert.Equal(t, inviter.Id, created.InviterId)
	assert.Equal(t, 500000, created.Quota, "trial credit granted at registration")

	var claim model.ExternalIdentityClaim
	require.NoError(t, model.DB.Where("provider = ? AND subject = ?", model.ExternalIdentityProviderTelegram, "70001").First(&claim).Error)
	assert.Equal(t, created.Id, claim.UserId)

	var reloadedInviter model.User
	require.NoError(t, model.DB.First(&reloadedInviter, inviter.Id).Error)
	assert.Equal(t, 1500000, reloadedInviter.AffQuota, "inviter reward paid post-commit")
	assert.Equal(t, 1, reloadedInviter.AffCount)
}

func TestTelegramWidgetLoginUnknownAccountWithoutInviter(t *testing.T) {
	botToken := setupWidgetLoginTest(t)
	common.QuotaForNewUser = 500000

	response := widgetLoginRequest(botToken, "70002", "nocode", nil)
	var body widgetLoginBody
	require.NoError(t, common.Unmarshal(response.Body.Bytes(), &body))
	require.True(t, body.Success, response.Body.String())

	created, err := model.GetUserByTelegramID("70002")
	require.NoError(t, err)
	assert.Zero(t, created.InviterId)
	assert.Equal(t, 500000, created.Quota)
}

func TestTelegramWidgetLoginRegisterDisabledRejectsUnknownAccount(t *testing.T) {
	botToken := setupWidgetLoginTest(t)
	common.RegisterEnabled = false

	response := widgetLoginRequest(botToken, "70003", "", nil)
	var body widgetLoginBody
	require.NoError(t, common.Unmarshal(response.Body.Bytes(), &body))
	assert.False(t, body.Success)
	assert.Contains(t, body.Message, "未绑定")

	var count int64
	require.NoError(t, model.DB.Model(&model.User{}).Where("telegram_id = ?", "70003").Count(&count).Error)
	assert.Zero(t, count)
}

func TestTelegramWidgetLoginRejectsReplay(t *testing.T) {
	botToken := setupWidgetLoginTest(t)
	common.QuotaForNewUser = 500000

	// Sign once and replay the identical query string: the one-time
	// assertion claim must reject the second delivery.
	params := signTelegramWidgetParams(botToken, map[string]string{
		"id":         "70004",
		"auth_date":  strconv.FormatInt(time.Now().Unix(), 10),
		"username":   "tg_widget_user",
		"first_name": "Widget",
	})
	response := widgetLoginRequestParams(params, "")
	var body widgetLoginBody
	require.NoError(t, common.Unmarshal(response.Body.Bytes(), &body))
	require.True(t, body.Success, response.Body.String())

	replay := widgetLoginRequestParams(params, "")
	assert.Equal(t, http.StatusForbidden, replay.Code)

	var count int64
	require.NoError(t, model.DB.Model(&model.User{}).Where("telegram_id = ?", "70004").Count(&count).Error)
	assert.EqualValues(t, 1, count, "a replay must not create a second account")
}

func TestTelegramWidgetLoginRejectsTamperedParams(t *testing.T) {
	botToken := setupWidgetLoginTest(t)

	response := widgetLoginRequest(botToken, "70006", "", func(params url.Values) {
		params.Set("id", "70007")
	})
	var body widgetLoginBody
	require.NoError(t, common.Unmarshal(response.Body.Bytes(), &body))
	assert.False(t, body.Success)

	var count int64
	require.NoError(t, model.DB.Model(&model.User{}).Count(&count).Error)
	assert.Zero(t, count)
}

func TestTelegramWidgetLoginExistingUserPathUnchanged(t *testing.T) {
	botToken := setupWidgetLoginTest(t)
	common.QuotaForNewUser = 500000

	existing := &model.User{Username: "existing-widget", Password: "password", TelegramId: "70005", Status: common.UserStatusEnabled, AuthVersion: 1}
	require.NoError(t, model.DB.Create(existing).Error)
	require.NoError(t, model.DB.Transaction(func(tx *gorm.DB) error {
		return model.ClaimExternalIdentityWithTx(tx, model.ExternalIdentityProviderTelegram, "70005", existing.Id)
	}))

	response := widgetLoginRequest(botToken, "70005", "", nil)
	var body widgetLoginBody
	require.NoError(t, common.Unmarshal(response.Body.Bytes(), &body))
	require.True(t, body.Success, response.Body.String())

	// No trial credit for an already-existing account and no second user.
	var stored model.User
	require.NoError(t, model.DB.First(&stored, existing.Id).Error)
	assert.Zero(t, stored.Quota)
	var count int64
	require.NoError(t, model.DB.Model(&model.User{}).Count(&count).Error)
	assert.EqualValues(t, 1, count)
}

func TestTelegramWidgetLoginAffiliateHeaderIgnoredForExistingUser(t *testing.T) {
	botToken := setupWidgetLoginTest(t)

	existing := &model.User{Username: "existing-widget-2", Password: "password", TelegramId: "70008", Status: common.UserStatusEnabled, AuthVersion: 1}
	require.NoError(t, model.DB.Create(existing).Error)
	require.NoError(t, model.DB.Transaction(func(tx *gorm.DB) error {
		return model.ClaimExternalIdentityWithTx(tx, model.ExternalIdentityProviderTelegram, "70008", existing.Id)
	}))

	response := widgetLoginRequest(botToken, "70008", "anycode", nil)
	var body widgetLoginBody
	require.NoError(t, common.Unmarshal(response.Body.Bytes(), &body))
	require.True(t, body.Success, response.Body.String())
	var stored model.User
	require.NoError(t, model.DB.First(&stored, existing.Id).Error)
	assert.Zero(t, stored.InviterId, "affiliate code never rewrites an existing account")
}

func TestPasswordRegisterDoesNotCreditInviter(t *testing.T) {
	setupWidgetLoginTest(t)
	common.QuotaForInviter = 1500000

	inviter := &model.User{Username: "register-inviter", Password: "password", AffCode: "regin", Status: common.UserStatusEnabled, AuthVersion: 1}
	require.NoError(t, model.DB.Create(inviter).Error)

	requestBody := `{"username":"password-registrant","password":"register-password-1","aff_code":"regin"}`
	response := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(response)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/user/register", strings.NewReader(requestBody))
	c.Request.Header.Set("Content-Type", "application/json")
	common.PasswordRegisterEnabled = true
	Register(c)

	var body widgetLoginBody
	require.NoError(t, common.Unmarshal(response.Body.Bytes(), &body))
	require.True(t, body.Success, response.Body.String())

	var registrant model.User
	require.NoError(t, model.DB.Where("username = ?", "password-registrant").First(&registrant).Error)
	assert.Zero(t, registrant.InviterId, "password registration never persists an inviter")

	var reloadedInviter model.User
	require.NoError(t, model.DB.First(&reloadedInviter, inviter.Id).Error)
	assert.Zero(t, reloadedInviter.AffQuota, "password registration never pays the inviter")
	assert.Zero(t, reloadedInviter.AffCount)
	assert.Zero(t, registrant.Quota, "Vantyr: registration grants no quota")
}

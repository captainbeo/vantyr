package controller

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/setting"
	"github.com/QuantumNous/new-api/setting/operation_setting"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestGetTopUpInfoStripeButtonLabel pins the customer-visible Stripe button
// name + subtitle: the button must not read as "cards only" while the same
// checkout also serves iDEAL|Wero, Apple Pay, Google Pay and Klarna.
func TestGetTopUpInfoStripeButtonLabel(t *testing.T) {
	oldConfirmed := operation_setting.GetPaymentSetting().ComplianceConfirmed
	oldVersion := operation_setting.GetPaymentSetting().ComplianceTermsVersion
	operation_setting.GetPaymentSetting().ComplianceConfirmed = true
	operation_setting.GetPaymentSetting().ComplianceTermsVersion = operation_setting.CurrentComplianceTermsVersion
	defer func() {
		operation_setting.GetPaymentSetting().ComplianceConfirmed = oldConfirmed
		operation_setting.GetPaymentSetting().ComplianceTermsVersion = oldVersion
	}()

	oldApiSecret := setting.StripeApiSecret
	oldWebhookSecret := setting.StripeWebhookSecret
	oldPriceId := setting.StripePriceId
	setting.StripeApiSecret = "sk_test_stub"
	setting.StripeWebhookSecret = "whsec_stub"
	setting.StripePriceId = "price_eur_primary"
	defer func() {
		setting.StripeApiSecret = oldApiSecret
		setting.StripeWebhookSecret = oldWebhookSecret
		setting.StripePriceId = oldPriceId
	}()

	// Epay methods must stay empty so only the Stripe entry is returned.
	oldMethods := operation_setting.PayMethods
	operation_setting.PayMethods = nil
	defer func() {
		operation_setting.PayMethods = oldMethods
	}()

	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/api/user/topup/info", nil)

	GetTopUpInfo(ctx)

	require.Equal(t, http.StatusOK, recorder.Code)
	var payload struct {
		Data struct {
			PayMethods []map[string]string `json:"pay_methods"`
		} `json:"data"`
	}
	require.NoError(t, common.Unmarshal(recorder.Body.Bytes(), &payload))
	require.Len(t, payload.Data.PayMethods, 1, "only the Stripe entry should be present")

	method := payload.Data.PayMethods[0]
	assert.Equal(t, "stripe", method["type"])
	assert.Equal(t, "Card / iDEAL | WERO / Apple Pay / Google Pay", method["name"])
	assert.Equal(t,
		"Stripe: Cards, iDEAL | Wero, Apple Pay, Google Pay, Klarna",
		method["subtitle"],
		"the subtitle must enumerate the checkout's payment methods so customers know wallets and iDEAL are available",
	)
}

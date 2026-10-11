package controller

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/QuantumNous/new-api/setting"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/stripe/stripe-go/v81"
)

// stubStripeSessionTransport captures Checkout Session creations and answers
// with a minimal valid session payload so price selection can be tested
// without any network access.
type stubStripeSessionTransport struct {
	http.RoundTripper

	// calls records one entry per Checkout Session creation.
	calls []stubStripeCall
}

type stubStripeCall struct {
	URL       string
	LineItems []stubStripeLineItem
}

type stubStripeLineItem struct {
	Price    string
	Quantity int64
}

func (t *stubStripeSessionTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	body, err := io.ReadAll(req.Body)
	if err != nil {
		return nil, err
	}
	values := parseFormEncoded(string(body))

	price, priceExists := values["line_items[0][price]"]
	quantity, quantityExists := values["line_items[0][quantity]"]
	if !priceExists || !quantityExists {
		return stubResponse(400, `{"error": {"message": "missing line_items"}}`), nil
	}

	call := stubStripeCall{
		URL: req.URL.String(),
		LineItems: []stubStripeLineItem{{
			Price:    price,
			Quantity: parseInt64(quantity),
		}},
	}
	t.calls = append(t.calls, call)

	payload := map[string]any{
		"id":     "cs_test_stub",
		"object": "checkout.session",
		"url":    "https://checkout.stripe.test/stub-session",
	}
	encoded, _ := json.Marshal(payload)
	return stubResponse(200, string(encoded)), nil
}

func parseFormEncoded(body string) map[string]string {
	values := map[string]string{}
	for _, pair := range strings.Split(body, "&") {
		parts := strings.SplitN(pair, "=", 2)
		if len(parts) == 2 {
			values[parts[0]] = parts[1]
		}
	}
	return values
}

func parseInt64(value string) int64 {
	var parsed int64
	fmt.Sscanf(value, "%d", &parsed)
	return parsed
}

func stubResponse(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     http.Header{"Content-Type": []string{"application/json"}},
	}
}

// installStripeStub swaps the stripe-go API backend onto a stub HTTP transport
// that records Checkout Session creations. The caller must register
// restoreStripeBackends via t.Cleanup to re-attach the default backend.
func installStripeStub(t *testing.T) *stubStripeSessionTransport {
	t.Helper()

	stub := &stubStripeSessionTransport{}
	httpClient := &http.Client{Transport: stub}
	stripe.SetBackend(stripe.APIBackend, stripe.GetBackendWithConfig(
		stripe.APIBackend,
		&stripe.BackendConfig{HTTPClient: httpClient},
	))

	return stub
}

func restoreStripeBackends() {
	stripe.SetBackend(stripe.APIBackend, stripe.GetBackend(stripe.APIBackend))
}

// TestGenStripeLinkCurrencyPriceSelection proves the dual-currency price
// selection: EUR (or unset) uses the primary StripePriceId, USD uses
// StripePriceIdUsd when configured, and USD fails closed when it is not.
func TestGenStripeLinkCurrencyPriceSelection(t *testing.T) {
	oldApiSecret := setting.StripeApiSecret
	oldPriceId := setting.StripePriceId
	oldPriceIdUsd := setting.StripePriceIdUsd
	setting.StripeApiSecret = "sk_test_stub"
	setting.StripePriceId = "price_eur_primary"
	setting.StripePriceIdUsd = "price_usd_secondary"
	t.Cleanup(func() {
		setting.StripeApiSecret = oldApiSecret
		setting.StripePriceId = oldPriceId
		setting.StripePriceIdUsd = oldPriceIdUsd
		restoreStripeBackends()
	})

	stub := installStripeStub(t)

	type testCase struct {
		name        string
		currency    string
		wantErr     bool
		wantPriceId string
	}

	tests := []testCase{
		{
			name:        "unset currency uses primary EUR price",
			currency:    "",
			wantPriceId: "price_eur_primary",
		},
		{
			name:        "eur currency uses primary EUR price",
			currency:    "eur",
			wantPriceId: "price_eur_primary",
		},
		{
			name:        "usd currency uses secondary USD price",
			currency:    "usd",
			wantPriceId: "price_usd_secondary",
		},
		{
			name:     "usd currency fails closed without USD price",
			currency: "usd",
			wantErr:  true,
		},
		{
			name:        "unknown currency falls back to EUR price",
			currency:    "gbp",
			wantPriceId: "price_eur_primary",
		},
	}

	sessionCount := 0
	for i, tc := range tests {
		if tc.name == "usd currency fails closed without USD price" {
			setting.StripePriceIdUsd = ""
		} else {
			setting.StripePriceIdUsd = "price_usd_secondary"
		}

		link, err := genStripeLink("ref_test", "", "user@example.com", 5, "", "", tc.currency)
		if tc.wantErr {
			require.Error(t, err, "case %d %s: expected error", i, tc.name)
			continue
		}
		require.NoError(t, err, "case %d %s", i, tc.name)
		assert.Equal(t, "https://checkout.stripe.test/stub-session", link, "case %d %s", i, tc.name)

		sessionCount++
		require.Len(t, stub.calls, sessionCount, "case %d %s: expected a new session creation", i, tc.name)
		assert.Equal(t, tc.wantPriceId, stub.calls[sessionCount-1].LineItems[0].Price, "case %d %s", i, tc.name)
		assert.Equal(t, int64(5), stub.calls[sessionCount-1].LineItems[0].Quantity, "case %d %s", i, tc.name)
	}
}

// TestRequestStripeAmountRejectsUnconfiguredUsd proves the amount calculator
// fails closed when the customer requests USD but no secondary price exists
// (the guard runs before any DB access, so no test database is needed).
func TestRequestStripeAmountRejectsUnconfiguredUsd(t *testing.T) {
	oldPriceIdUsd := setting.StripePriceIdUsd
	setting.StripePriceIdUsd = ""
	t.Cleanup(func() {
		setting.StripePriceIdUsd = oldPriceIdUsd
	})

	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(
		http.MethodPost,
		"/api/user/stripe/amount",
		strings.NewReader(`{"amount":5,"currency":"usd"}`),
	)
	ctx.Request.Header.Set("Content-Type", "application/json")

	RequestStripeAmount(ctx)

	assert.Equal(t, http.StatusOK, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "USD 支付未配置")
}

// TestStripeCurrencyUsdGuard verifies the currency selector normalization:
// only an explicit "usd" selects the secondary price.
func TestStripeCurrencyUsdGuard(t *testing.T) {
	assert.True(t, stripeCurrencyUsd("usd"))
	assert.True(t, stripeCurrencyUsd(" USD "))
	assert.False(t, stripeCurrencyUsd(""))
	assert.False(t, stripeCurrencyUsd("eur"))
	assert.False(t, stripeCurrencyUsd("EUR"))
	assert.False(t, stripeCurrencyUsd("gbp"))
}

package setting

var StripeApiSecret = ""
var StripeWebhookSecret = ""
var StripePriceId = ""

// StripePriceIdUsd optionally holds a second one-time price in USD for
// dual-currency top-ups. Empty means only the primary (StripePriceId)
// currency is offered.
var StripePriceIdUsd = ""
var StripeUnitPrice = 8.0
var StripeMinTopUp = 1
var StripePromotionCodesEnabled = false

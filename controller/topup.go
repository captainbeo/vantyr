package controller

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/logger"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/service"
	"github.com/QuantumNous/new-api/setting"
	"github.com/QuantumNous/new-api/setting/operation_setting"

	"github.com/Calcium-Ion/go-epay/epay"
	"github.com/gin-gonic/gin"
	"github.com/samber/lo"
	"github.com/shopspring/decimal"
)

func GetTopUpInfo(c *gin.Context) {
	complianceConfirmed := operation_setting.IsPaymentComplianceConfirmed()

	// 获取支付方式
	payMethods := operation_setting.PayMethods
	if !complianceConfirmed {
		payMethods = []map[string]string{}
	}

	// 如果启用了 Stripe 支付，添加到支付方法列表
	if isStripeTopUpEnabled() {
		// 检查是否已经包含 Stripe
		hasStripe := false
		for _, method := range payMethods {
			if method["type"] == "stripe" {
				hasStripe = true
				break
			}
		}

		if !hasStripe {
			stripeMethod := map[string]string{
				"name":      "Card / iDEAL | WERO / Apple + Google Pay / Paypal and more",
				"subtitle":  "powered by Stripe",
				"type":      "stripe",
				"color":     "#635BFF",
				"min_topup": strconv.Itoa(setting.StripeMinTopUp),
			}
			payMethods = append(payMethods, stripeMethod)
		}
	}

	// Waffo Pancake is displayed above the standard Waffo gateway.
	enableWaffoPancake := isWaffoPancakeTopUpEnabled()
	if enableWaffoPancake {
		hasWaffoPancake := false
		for _, method := range payMethods {
			if method["type"] == model.PaymentMethodWaffoPancake {
				hasWaffoPancake = true
				break
			}
		}

		if !hasWaffoPancake {
			payMethods = append(payMethods, map[string]string{
				"name":      "Waffo Pancake",
				"type":      model.PaymentMethodWaffoPancake,
				"color":     "#F97316",
				"min_topup": strconv.Itoa(setting.WaffoPancakeMinTopUp),
			})
		}
	}

	// 如果启用了 Waffo 支付，添加到支付方法列表
	enableWaffo := isWaffoTopUpEnabled()
	if enableWaffo {
		hasWaffo := false
		for _, method := range payMethods {
			if method["type"] == model.PaymentMethodWaffo {
				hasWaffo = true
				break
			}
		}

		if !hasWaffo {
			waffoMethod := map[string]string{
				"name":      "Waffo (Global Payment)",
				"type":      model.PaymentMethodWaffo,
				"color":     "#3B82F6",
				"min_topup": strconv.Itoa(setting.WaffoMinTopUp),
			}
			payMethods = append(payMethods, waffoMethod)
		}
	}

	data := gin.H{
		"enable_online_topup":              isEpayTopUpEnabled(),
		"enable_stripe_topup":              isStripeTopUpEnabled(),
		"enable_creem_topup":               isCreemTopUpEnabled(),
		"enable_waffo_topup":               enableWaffo,
		"enable_waffo_pancake_topup":       enableWaffoPancake,
		"enable_redemption":                complianceConfirmed,
		"payment_compliance_confirmed":     complianceConfirmed,
		"payment_compliance_terms_version": operation_setting.CurrentComplianceTermsVersion,
		"waffo_pay_methods": func() any {
			if enableWaffo {
				return setting.GetWaffoPayMethods()
			}
			return nil
		}(),
		"creem_products":          setting.CreemProducts,
		"pay_methods":             payMethods,
		"min_topup":               operation_setting.MinTopUp,
		"stripe_min_topup":        setting.StripeMinTopUp,
		"stripe_usd_enabled":      isStripeTopUpEnabled() && strings.TrimSpace(setting.StripePriceIdUsd) != "",
		"waffo_min_topup":         setting.WaffoMinTopUp,
		"waffo_pancake_min_topup": setting.WaffoPancakeMinTopUp,
		"amount_options":          operation_setting.GetPaymentSetting().AmountOptions,
		"discount":                operation_setting.GetPaymentSetting().AmountDiscount,
		"topup_link":              common.TopUpLink,
	}
	common.ApiSuccess(c, data)
}

type EpayRequest struct {
	Amount        int64  `json:"amount"`
	PaymentMethod string `json:"payment_method"`
}

type AmountRequest struct {
	Amount int64 `json:"amount"`
}

func GetEpayClient() *epay.Client {
	if operation_setting.PayAddress == "" || operation_setting.EpayId == "" || operation_setting.EpayKey == "" {
		return nil
	}
	withUrl, err := epay.NewClient(&epay.Config{
		PartnerID: operation_setting.EpayId,
		Key:       operation_setting.EpayKey,
	}, operation_setting.PayAddress)
	if err != nil {
		return nil
	}
	return withUrl
}

// getSecondaryEpayClient 返回副易支付网关（BEpusdt）客户端，未配置时返回 nil。
func getSecondaryEpayClient() *epay.Client {
	if operation_setting.EpaySecondaryAddress == "" ||
		operation_setting.EpaySecondaryId == "" ||
		operation_setting.EpaySecondaryKey == "" {
		return nil
	}
	withUrl, err := epay.NewClient(&epay.Config{
		PartnerID: operation_setting.EpaySecondaryId,
		Key:       operation_setting.EpaySecondaryKey,
	}, operation_setting.EpaySecondaryAddress)
	if err != nil {
		return nil
	}
	return withUrl
}

// epaySecondaryTypesSet 解析 EpaySecondaryTypes（逗号分隔的支付方式）为集合。
func epaySecondaryTypesSet() map[string]bool {
	types := make(map[string]bool)
	for _, t := range strings.Split(operation_setting.EpaySecondaryTypes, ",") {
		t = strings.TrimSpace(t)
		if t != "" {
			types[t] = true
		}
	}
	return types
}

// resolveEpayGateway 按支付方式选择易支付网关：EpaySecondaryTypes 命中的
// 方式路由到副网关，其余走主网关。副网关未配置却命中其类型时 fail-closed
// 返回错误（禁止静默改走主网关——主网关不认识这些交易类型，订单必失败）。
func resolveEpayGateway(paymentMethod string) (*epay.Client, bool, error) {
	secondary := getSecondaryEpayClient()
	if epaySecondaryTypesSet()[paymentMethod] {
		if secondary == nil {
			return nil, false, errors.New("支付网关未配置")
		}
		return secondary, true, nil
	}
	primary := GetEpayClient()
	if primary == nil {
		return nil, false, errors.New("支付网关未配置")
	}
	return primary, false, nil
}

// buildSecondaryEpaySubmitForm 构建发往副网关（BEpusdt）的易支付提交表单。
// 与 go-epay 的 Purchase() 参数一致，但额外携带 fiat=USD：BEpusdt 的易支付
// 提交默认按 CNY 计价，只有显式传 fiat 才会按 USD 汇率折算加密货币金额。
// fiat 参与 MD5 签名（GenerateParams 过滤空值后对全部参数签名）。
func buildSecondaryEpaySubmitForm(
	paymentMethod string,
	tradeNo string,
	name string,
	money string,
	notifyUrl *url.URL,
	returnUrl *url.URL,
) (string, map[string]string, error) {
	requestParams := map[string]string{
		"pid":          operation_setting.EpaySecondaryId,
		"type":         paymentMethod,
		"out_trade_no": tradeNo,
		"name":         name,
		"money":        money,
		"fiat":         "USD",
		"device":       string(epay.PC),
		"sign_type":    "MD5",
		"notify_url":   notifyUrl.String(),
		"return_url":   returnUrl.String(),
		"sign":         "",
	}
	base, err := url.Parse(strings.TrimRight(operation_setting.EpaySecondaryAddress, "/"))
	if err != nil {
		return "", nil, err
	}
	uri := base.String() + "/submit.php"
	return uri, epay.GenerateParams(requestParams, operation_setting.EpaySecondaryKey), nil
}

// bepusdtSign 复现 BEpusdt 的 EpusdtSign 签名算法（原生 API/回调共用）：
// 排除 signature 键、跳过空值，按 key 排序拼 k=v&k=v（值按 %v 格式化，
// float 1.0 输出 "1"），拼接商户令牌后取 MD5。见 BEpusdt app/utils。
func bepusdtSign(data map[string]any, token string) string {
	keys := make([]string, 0, len(data))
	for k := range data {
		if k == "signature" {
			continue
		}
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var sign strings.Builder
	for _, k := range keys {
		v := data[k]
		if v == nil || v == "" {
			continue
		}
		sign.WriteString(k)
		sign.WriteString("=")
		sign.WriteString(fmt.Sprintf("%v", v))
		sign.WriteString("&")
	}
	raw := strings.TrimRight(sign.String(), "&") + token
	return fmt.Sprintf("%x", md5.Sum([]byte(raw)))
}

// bepusdtNativeCurrencies 是原生 create-order 请求的币种白名单：
// 收银台只展示这些币种对应的网络供客户选择（一按钮多链）。
var bepusdtNativeCurrencies = "USDT,USDC,GRAM"

// bepusdtCreateOrderReq / bepusdtCreateOrderResp 是原生创建订单
// 接口（POST /api/v1/order/create-order）的请求与响应结构。
type bepusdtCreateOrderReq struct {
	OrderID     string  `json:"order_id"`
	NotifyURL   string  `json:"notify_url"`
	RedirectURL string  `json:"redirect_url"`
	Amount      float64 `json:"amount"`
	Name        string  `json:"name"`
	Fiat        string  `json:"fiat"`
	Currencies  string  `json:"currencies"`
	Timeout     int64   `json:"timeout"`
	Signature   string  `json:"signature"`
}

type bepusdtCreateOrderResp struct {
	StatusCode int    `json:"status_code"`
	Message    string `json:"message"`
	Data       struct {
		TradeID     string `json:"trade_id"`
		PaymentURL  string `json:"payment_url"`
		OrderID     string `json:"order_id"`
		Amount      string `json:"amount"`
		Fiat        string `json:"fiat"`
		ExpirationTime int64 `json:"expiration_time"`
		Reselect    bool   `json:"reselect"`
	} `json:"data"`
}

// createSecondaryNativeOrder 通过 BEpusdt 原生 API 创建订单（区别于易支付
// submit.php 表单）：不指定 trade_type、限定 currencies → 收银台自带
// 网络选择器（reselect=true），一个入口覆盖副网关全部链。浏览器直接
// GET payment_url，无需表单 POST（也消除“不安全提交”浏览器警告）。
// 金额按 USD 报价（fiat=USD），BEpusdt 按各币种汇率折算。
func createSecondaryNativeOrder(
	tradeNo string,
	name string,
	amount float64,
	notifyUrl string,
	returnUrl string,
) (string, error) {
	base, err := url.Parse(strings.TrimRight(operation_setting.EpaySecondaryAddress, "/"))
	if err != nil {
		return "", err
	}
	payload := map[string]any{
		"order_id":     tradeNo,
		"notify_url":   notifyUrl,
		"redirect_url": returnUrl,
		"amount":       amount,
		"name":         name,
		"fiat":         "USD",
		"currencies":   bepusdtNativeCurrencies,
		"timeout":      int64(900),
	}
	reqBody := bepusdtCreateOrderReq{
		OrderID:     tradeNo,
		NotifyURL:   notifyUrl,
		RedirectURL: returnUrl,
		Amount:      amount,
		Name:        name,
		Fiat:        "USD",
		Currencies:  bepusdtNativeCurrencies,
		Timeout:     900,
	}
	reqBody.Signature = bepusdtSign(payload, operation_setting.EpaySecondaryKey)

	raw, err := json.Marshal(reqBody)
	if err != nil {
		return "", err
	}
	httpReq, err := http.NewRequestWithContext(context.Background(), http.MethodPost,
		base.String()+"/api/v1/order/create-order", bytes.NewReader(raw))
	if err != nil {
		return "", err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	resp, err := secondaryHTTPClient.Do(httpReq)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	var parsed bepusdtCreateOrderResp
	if err := json.Unmarshal(body, &parsed); err != nil {
		return "", fmt.Errorf("BEpusdt 响应解析失败: %w", err)
	}
	if parsed.StatusCode != 200 || parsed.Data.PaymentURL == "" {
		return "", fmt.Errorf("BEpusdt 创建订单失败: %s", parsed.Message)
	}
	return parsed.Data.PaymentURL, nil
}

// secondaryHTTPClient 副网关调用客户端：短超时（支付拉起是同步请求）。
var secondaryHTTPClient = &http.Client{Timeout: 15 * time.Second}

// bepusdtNotifyPayload 是 BEpusdt 原生回调（POST JSON）结构。
type bepusdtNotifyPayload struct {
	TradeID            string  `json:"trade_id"`
	OrderID            string  `json:"order_id"`
	Amount             float64 `json:"amount"`
	ActualAmount       string  `json:"actual_amount"`
	Token              string  `json:"token"`
	BlockTransactionID string  `json:"block_transaction_id"`
	Signature          string  `json:"signature"`
	Status             int     `json:"status"`
}

// BepusdtNotify 处理 BEpusdt 原生 JSON 回调（/api/user/bepusdt/notify）。
// 验签（EpusdtSign）后：status=2（支付成功）走 RechargeEpay 入账（行锁
// 幂等，额度取订单行 Amount，不取回调金额）；status=3（超时）把 pending
// 订单标记 expired；status=1（等待中）仅确认。均须回 success 纯文本。
func BepusdtNotify(c *gin.Context) {
	if !isEpayWebhookEnabled() {
		logger.LogWarn(c.Request.Context(), fmt.Sprintf("BEpusdt webhook 被拒绝 reason=webhook_disabled path=%q client_ip=%s", c.Request.RequestURI, c.ClientIP()))
		_, _ = c.Writer.Write([]byte("fail"))
		return
	}
	raw, err := io.ReadAll(c.Request.Body)
	if err != nil {
		_, _ = c.Writer.Write([]byte("fail"))
		return
	}
	var payload bepusdtNotifyPayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		logger.LogWarn(c.Request.Context(), fmt.Sprintf("BEpusdt webhook JSON 解析失败 path=%q client_ip=%s error=%q", c.Request.RequestURI, c.ClientIP(), err.Error()))
		_, _ = c.Writer.Write([]byte("fail"))
		return
	}
	// 验签：把已知字段按 BEpusdt 签名规则重算（signature 键排除、空值跳过）
	signMap := map[string]any{
		"trade_id":            payload.TradeID,
		"order_id":            payload.OrderID,
		"amount":              payload.Amount,
		"actual_amount":       payload.ActualAmount,
		"token":               payload.Token,
		"block_transaction_id": payload.BlockTransactionID,
		"status":              payload.Status,
	}
	if bepusdtSign(signMap, operation_setting.EpaySecondaryKey) != payload.Signature {
		logger.LogWarn(c.Request.Context(), fmt.Sprintf("BEpusdt webhook 验签失败 trade_id=%s order_id=%s client_ip=%s", payload.TradeID, payload.OrderID, c.ClientIP()))
		_, _ = c.Writer.Write([]byte("fail"))
		return
	}
	logger.LogInfo(c.Request.Context(), fmt.Sprintf("BEpusdt webhook 验签成功 trade_id=%s order_id=%s status=%d client_ip=%s", payload.TradeID, payload.OrderID, payload.Status, c.ClientIP()))

	switch payload.Status {
	case 2: // 支付成功
		LockOrder(payload.OrderID)
		defer UnlockOrder(payload.OrderID)
		alreadyDone, err := model.RechargeEpay(payload.OrderID, "bepusdt", c.ClientIP())
		if err != nil {
			switch {
			case errors.Is(err, model.ErrTopUpNotFound):
				logger.LogWarn(c.Request.Context(), fmt.Sprintf("BEpusdt 回调订单不存在 order_id=%s client_ip=%s", payload.OrderID, c.ClientIP()))
			case errors.Is(err, model.ErrPaymentMethodMismatch):
				logger.LogWarn(c.Request.Context(), fmt.Sprintf("BEpusdt 订单支付网关不匹配 order_id=%s client_ip=%s", payload.OrderID, c.ClientIP()))
			case errors.Is(err, model.ErrTopUpStatusInvalid):
				logger.LogWarn(c.Request.Context(), fmt.Sprintf("BEpusdt 订单状态非法 order_id=%s client_ip=%s", payload.OrderID, c.ClientIP()))
			default:
				logger.LogError(c.Request.Context(), fmt.Sprintf("BEpusdt 充值处理失败 order_id=%s client_ip=%s error=%q", payload.OrderID, c.ClientIP(), err.Error()))
			}
			_, _ = c.Writer.Write([]byte("fail"))
			return
		}
		if alreadyDone {
			logger.LogInfo(c.Request.Context(), fmt.Sprintf("BEpusdt 重复回调幂等忽略 order_id=%s client_ip=%s", payload.OrderID, c.ClientIP()))
		} else {
			logger.LogInfo(c.Request.Context(), fmt.Sprintf("BEpusdt 充值成功 order_id=%s amount=%.2f actual=%s client_ip=%s", payload.OrderID, payload.Amount, payload.ActualAmount, c.ClientIP()))
		}
	case 3: // 订单超时 → 标记过期，避免死信堆积
		LockOrder(payload.OrderID)
		defer UnlockOrder(payload.OrderID)
		if err := model.UpdatePendingTopUpStatus(payload.OrderID, model.PaymentProviderEpay, common.TopUpStatusExpired); err != nil && !errors.Is(err, model.ErrTopUpNotFound) {
			logger.LogError(c.Request.Context(), fmt.Sprintf("BEpusdt 订单过期处理失败 order_id=%s error=%q", payload.OrderID, err.Error()))
		} else {
			logger.LogInfo(c.Request.Context(), fmt.Sprintf("BEpusdt 订单已过期 order_id=%s", payload.OrderID))
		}
	case 1: // 等待支付，仅确认
		logger.LogInfo(c.Request.Context(), fmt.Sprintf("BEpusdt 订单等待支付 order_id=%s", payload.OrderID))
	default:
		logger.LogWarn(c.Request.Context(), fmt.Sprintf("BEpusdt 未知订单状态 order_id=%s status=%d", payload.OrderID, payload.Status))
	}
	_, _ = c.Writer.Write([]byte("success"))
}

// verifyEpayCallbackSignature 对回调参数依次用主、副网关密钥验签，
// 返回验签成功的客户端与结果。两个网关使用不同密钥时仅其中一方通过；
// 主密钥先试（现网全部历史订单均为主网关订单），失败再试副密钥。
// 注意：每次 Verify 都在传入的 map 上原地重算 sign（go-epay 的
// GenerateParams 直接写回 map），所以每次尝试必须传副本，否则第一个
// 客户端写入的 sign 会污染第二次比较。
func verifyEpayCallbackSignature(params map[string]string) (*epay.Client, *epay.VerifyRes, error) {
	primary := GetEpayClient()
	if primary != nil {
		verifyInfo, err := primary.Verify(copyEpayParams(params))
		if err == nil && verifyInfo.VerifyStatus {
			return primary, verifyInfo, nil
		}
	}
	secondary := getSecondaryEpayClient()
	if secondary != nil {
		verifyInfo, err := secondary.Verify(copyEpayParams(params))
		if err == nil && verifyInfo.VerifyStatus {
			return secondary, verifyInfo, nil
		}
	}
	return nil, nil, errors.New("验签失败")
}

func copyEpayParams(params map[string]string) map[string]string {
	copied := make(map[string]string, len(params))
	for k, v := range params {
		copied[k] = v
	}
	return copied
}

func getPayMoney(amount int64, group string) float64 {
	dAmount := decimal.NewFromInt(amount)
	// 充值金额以“展示类型”为准：
	// - USD/CNY: 前端传 amount 为金额单位；TOKENS: 前端传 tokens，需要换成 USD 金额
	if operation_setting.GetQuotaDisplayType() == operation_setting.QuotaDisplayTypeTokens {
		dQuotaPerUnit := decimal.NewFromFloat(common.QuotaPerUnit)
		dAmount = dAmount.Div(dQuotaPerUnit)
	}

	topupGroupRatio := common.GetTopupGroupRatio(group)
	if topupGroupRatio == 0 {
		topupGroupRatio = 1
	}

	dTopupGroupRatio := decimal.NewFromFloat(topupGroupRatio)
	dPrice := decimal.NewFromFloat(operation_setting.Price)
	// apply optional preset discount by the original request amount (if configured), default 1.0
	discount := 1.0
	if ds, ok := operation_setting.GetPaymentSetting().AmountDiscount[int(amount)]; ok {
		if ds > 0 {
			discount = ds
		}
	}
	dDiscount := decimal.NewFromFloat(discount)

	payMoney := dAmount.Mul(dPrice).Mul(dTopupGroupRatio).Mul(dDiscount)

	return payMoney.InexactFloat64()
}

func getMinTopup() int64 {
	minTopup := operation_setting.MinTopUp
	if operation_setting.GetQuotaDisplayType() == operation_setting.QuotaDisplayTypeTokens {
		dMinTopup := decimal.NewFromInt(int64(minTopup))
		dQuotaPerUnit := decimal.NewFromFloat(common.QuotaPerUnit)
		quota, err := common.WalletQuotaFromDecimalStrict(dMinTopup.Mul(dQuotaPerUnit))
		if err != nil {
			return common.MaxWalletQuota
		}
		minTopup = quota
	}
	return int64(minTopup)
}

func getTopUpQuota(amount int64) (int, error) {
	quota := decimal.NewFromInt(amount)
	if operation_setting.GetQuotaDisplayType() == operation_setting.QuotaDisplayTypeTokens {
		quotaPerUnit := decimal.NewFromFloat(common.QuotaPerUnit)
		quota = decimal.NewFromInt(quota.Div(quotaPerUnit).IntPart()).Mul(quotaPerUnit)
	} else {
		quota = quota.Mul(decimal.NewFromFloat(common.QuotaPerUnit))
	}
	return common.WalletQuotaFromDecimalStrict(quota)
}

func getMaxTopUpAmount() int64 {
	if common.QuotaPerUnit <= 0 {
		return 0
	}
	quotaPerUnit := decimal.NewFromFloat(common.QuotaPerUnit)
	maxStoredAmount := decimal.NewFromInt(common.MaxWalletQuota).
		Div(quotaPerUnit).
		Floor()
	if operation_setting.GetQuotaDisplayType() == operation_setting.QuotaDisplayTypeTokens {
		return maxStoredAmount.Add(decimal.NewFromInt(1)).
			Mul(quotaPerUnit).
			Ceil().
			Sub(decimal.NewFromInt(1)).
			IntPart()
	}
	return maxStoredAmount.IntPart()
}

func validateCreditedQuota(quota decimal.Decimal) (int, error) {
	value, err := common.WalletQuotaFromDecimalStrict(quota)
	if err != nil {
		return 0, errors.New("充值额度超出系统可表示范围")
	}
	if value <= 0 {
		return 0, errors.New("充值额度必须大于 0")
	}
	return value, nil
}

func validateTopUpQuota(amount int64) (int, error) {
	quota, err := getTopUpQuota(amount)
	if err == nil && quota > 0 {
		return quota, nil
	}
	maxAmount := getMaxTopUpAmount()
	if maxAmount > 0 && amount > maxAmount {
		return 0, fmt.Errorf("单笔充值数量不能大于 %d", maxAmount)
	}
	return 0, errors.New("充值数量无效")
}

func rejectInvalidCreditedQuota(c *gin.Context, userId int, quota decimal.Decimal) bool {
	creditedQuota, err := validateCreditedQuota(quota)
	if err == nil {
		err = model.ValidateTopUpQuotaCapacity(userId, creditedQuota)
	}
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": err.Error()})
		return true
	}
	return false
}

func rejectInvalidTopUpQuota(c *gin.Context, userId int, amount int64) bool {
	creditedQuota, err := validateTopUpQuota(amount)
	if err == nil {
		err = model.ValidateTopUpQuotaCapacity(userId, creditedQuota)
	}
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": err.Error()})
		return true
	}
	return false
}

func RequestEpay(c *gin.Context) {
	var req EpayRequest
	err := c.ShouldBindJSON(&req)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": "参数错误"})
		return
	}
	if req.Amount < getMinTopup() {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": fmt.Sprintf("充值数量不能小于 %d", getMinTopup())})
		return
	}
	id := c.GetInt("id")
	if rejectInvalidTopUpQuota(c, id, req.Amount) {
		return
	}

	group, err := model.GetUserGroup(id, true)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": "获取用户分组失败"})
		return
	}
	payMoney := getPayMoney(req.Amount, group)
	if payMoney < 0.01 {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": "充值金额过低"})
		return
	}

	if !operation_setting.ContainsPayMethod(req.PaymentMethod) {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": "支付方式不存在"})
		return
	}

	// 副网关配置校验（fail-closed）：命中副网关类型但副网关未配置时，
	// 在任何数据库访问与订单创建之前拒绝——与 Stripe USD fail-closed 同模式。
	if _, _, resolveErr := resolveEpayGateway(req.PaymentMethod); resolveErr != nil {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": resolveErr.Error()})
		return
	}

	callBackAddress := service.GetCallbackAddress()
	returnUrl, _ := url.Parse(paymentReturnPath("/usage-logs"))
	notifyUrl, _ := url.Parse(callBackAddress + "/api/user/epay/notify")
	tradeNo := fmt.Sprintf("%s%d", common.GetRandomString(6), time.Now().Unix())
	tradeNo = fmt.Sprintf("USR%dNO%s", id, tradeNo)
	client, isSecondary, resolveErr := resolveEpayGateway(req.PaymentMethod)
	if resolveErr != nil {
		logger.LogError(c.Request.Context(), fmt.Sprintf("易支付 网关解析失败 user_id=%d payment_method=%s error=%q", id, req.PaymentMethod, resolveErr.Error()))
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": resolveErr.Error()})
		return
	}

	// 副网关（BEpusdt）：走原生 create-order API——收银台自带网络选择器
	// （一个按钮覆盖全部链），浏览器直接 GET payment_url（无表单 POST，
	// 无“不安全提交”警告），回调走 /api/user/bepusdt/notify（JSON+签名）。
	if isSecondary {
		payLink, nativeErr := createSecondaryNativeOrder(
			tradeNo,
			fmt.Sprintf("TUC%d", req.Amount),
			payMoney,
			callBackAddress+"/api/user/bepusdt/notify",
			returnUrl.String(),
		)
		if nativeErr != nil {
			logger.LogError(c.Request.Context(), fmt.Sprintf("BEpusdt 创建订单失败 user_id=%d trade_no=%s amount=%d error=%q", id, tradeNo, req.Amount, nativeErr.Error()))
			c.JSON(http.StatusOK, gin.H{"message": "error", "data": "拉起支付失败"})
			return
		}
		amount := req.Amount
		if operation_setting.GetQuotaDisplayType() == operation_setting.QuotaDisplayTypeTokens {
			dAmount := decimal.NewFromInt(int64(amount))
			dQuotaPerUnit := decimal.NewFromFloat(common.QuotaPerUnit)
			amount = dAmount.Div(dQuotaPerUnit).IntPart()
		}
		topUp := &model.TopUp{
			UserId:          id,
			Amount:          amount,
			Money:           payMoney,
			TradeNo:         tradeNo,
			PaymentMethod:   "bepusdt",
			PaymentProvider: model.PaymentProviderEpay,
			CreateTime:      time.Now().Unix(),
			Status:          common.TopUpStatusPending,
		}
		if insertErr := topUp.Insert(); insertErr != nil {
			logger.LogError(c.Request.Context(), fmt.Sprintf("BEpusdt 创建充值订单失败 user_id=%d trade_no=%s error=%q", id, tradeNo, insertErr.Error()))
			c.JSON(http.StatusOK, gin.H{"message": "error", "data": "创建订单失败"})
			return
		}
		logger.LogInfo(c.Request.Context(), fmt.Sprintf("BEpusdt 充值订单创建成功 user_id=%d trade_no=%s payment_url=%q", id, tradeNo, payLink))
		c.JSON(http.StatusOK, gin.H{"message": "success", "data": gin.H{"pay_link": payLink}})
		return
	}

	var uri string
	var params map[string]string
	{
		uri, params, err = client.Purchase(&epay.PurchaseArgs{
			Type:           req.PaymentMethod,
			ServiceTradeNo: tradeNo,
			Name:           fmt.Sprintf("TUC%d", req.Amount),
			Money:          strconv.FormatFloat(payMoney, 'f', 2, 64),
			Device:         epay.PC,
			NotifyUrl:      notifyUrl,
			ReturnUrl:      returnUrl,
		})
	}
	if err != nil {
		logger.LogError(c.Request.Context(), fmt.Sprintf("易支付 拉起支付失败 user_id=%d trade_no=%s payment_method=%s amount=%d error=%q", id, tradeNo, req.PaymentMethod, req.Amount, err.Error()))
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": "拉起支付失败"})
		return
	}
	amount := req.Amount
	if operation_setting.GetQuotaDisplayType() == operation_setting.QuotaDisplayTypeTokens {
		dAmount := decimal.NewFromInt(int64(amount))
		dQuotaPerUnit := decimal.NewFromFloat(common.QuotaPerUnit)
		amount = dAmount.Div(dQuotaPerUnit).IntPart()
	}
	topUp := &model.TopUp{
		UserId:          id,
		Amount:          amount,
		Money:           payMoney,
		TradeNo:         tradeNo,
		PaymentMethod:   req.PaymentMethod,
		PaymentProvider: model.PaymentProviderEpay,
		CreateTime:      time.Now().Unix(),
		Status:          common.TopUpStatusPending,
	}
	err = topUp.Insert()
	if err != nil {
		logger.LogError(c.Request.Context(), fmt.Sprintf("易支付 创建充值订单失败 user_id=%d trade_no=%s payment_method=%s amount=%d error=%q", id, tradeNo, req.PaymentMethod, req.Amount, err.Error()))
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": "创建订单失败"})
		return
	}
	logger.LogInfo(c.Request.Context(), fmt.Sprintf("易支付 充值订单创建成功 user_id=%d trade_no=%s payment_method=%s amount=%d money=%.2f uri=%q params=%q", id, tradeNo, req.PaymentMethod, req.Amount, payMoney, uri, common.GetJsonString(params)))
	c.JSON(http.StatusOK, gin.H{"message": "success", "data": params, "url": uri})
}

// tradeNo lock
var orderLocks sync.Map
var createLock sync.Mutex

// refCountedMutex 带引用计数的互斥锁，确保最后一个使用者才从 map 中删除
type refCountedMutex struct {
	mu       sync.Mutex
	refCount int
}

// LockOrder 尝试对给定订单号加锁
func LockOrder(tradeNo string) {
	createLock.Lock()
	var rcm *refCountedMutex
	if v, ok := orderLocks.Load(tradeNo); ok {
		rcm = v.(*refCountedMutex)
	} else {
		rcm = &refCountedMutex{}
		orderLocks.Store(tradeNo, rcm)
	}
	rcm.refCount++
	createLock.Unlock()
	rcm.mu.Lock()
}

// UnlockOrder 释放给定订单号的锁
func UnlockOrder(tradeNo string) {
	v, ok := orderLocks.Load(tradeNo)
	if !ok {
		return
	}
	rcm := v.(*refCountedMutex)
	rcm.mu.Unlock()

	createLock.Lock()
	rcm.refCount--
	if rcm.refCount == 0 {
		orderLocks.Delete(tradeNo)
	}
	createLock.Unlock()
}

func EpayNotify(c *gin.Context) {
	if !isEpayWebhookEnabled() {
		logger.LogWarn(c.Request.Context(), fmt.Sprintf("易支付 webhook 被拒绝 reason=webhook_disabled path=%q client_ip=%s", c.Request.RequestURI, c.ClientIP()))
		_, _ = c.Writer.Write([]byte("fail"))
		return
	}

	var params map[string]string

	if c.Request.Method == "POST" {
		// POST 请求：从 POST body 解析参数
		if err := c.Request.ParseForm(); err != nil {
			logger.LogError(c.Request.Context(), fmt.Sprintf("易支付 webhook POST 表单解析失败 path=%q client_ip=%s error=%q", c.Request.RequestURI, c.ClientIP(), err.Error()))
			_, _ = c.Writer.Write([]byte("fail"))
			return
		}
		params = lo.Reduce(lo.Keys(c.Request.PostForm), func(r map[string]string, t string, i int) map[string]string {
			r[t] = c.Request.PostForm.Get(t)
			return r
		}, map[string]string{})
	} else {
		// GET 请求：从 URL Query 解析参数
		params = lo.Reduce(lo.Keys(c.Request.URL.Query()), func(r map[string]string, t string, i int) map[string]string {
			r[t] = c.Request.URL.Query().Get(t)
			return r
		}, map[string]string{})
	}
	logger.LogInfo(c.Request.Context(), fmt.Sprintf("易支付 webhook 收到请求 path=%q client_ip=%s method=%s params=%q", c.Request.RequestURI, c.ClientIP(), c.Request.Method, common.GetJsonString(params)))

	if len(params) == 0 {
		logger.LogWarn(c.Request.Context(), fmt.Sprintf("易支付 webhook 参数为空 path=%q client_ip=%s", c.Request.RequestURI, c.ClientIP()))
		_, _ = c.Writer.Write([]byte("fail"))
		return
	}
	// 双网关验签：先主网关（历史订单全部为主网关订单），失败再试副网关
	// （BEpusdt）。回调参数不携带网关标识，订单号是唯一的区分依据；
	// 两个密钥各自仅能验签自己网关发出的回调，互验必然失败——所以按
	// “先主后副”顺序尝试即可安全区分。
	_, verifyInfo, verifyErr := verifyEpayCallbackSignature(params)
	if verifyErr != nil || verifyInfo == nil {
		if _, writeErr := c.Writer.Write([]byte("fail")); writeErr != nil {
			logger.LogError(c.Request.Context(), fmt.Sprintf("易支付 webhook 响应写入失败 path=%q client_ip=%s error=%q", c.Request.RequestURI, c.ClientIP(), writeErr.Error()))
		}
		logger.LogWarn(c.Request.Context(), fmt.Sprintf("易支付 webhook 验签失败 path=%q client_ip=%s error=%v", c.Request.RequestURI, c.ClientIP(), verifyErr))
		return
	}
	logger.LogInfo(c.Request.Context(), fmt.Sprintf("易支付 webhook 验签成功 trade_no=%s callback_type=%s trade_status=%s client_ip=%s verify_info=%q", verifyInfo.ServiceTradeNo, verifyInfo.Type, verifyInfo.TradeStatus, c.ClientIP(), common.GetJsonString(verifyInfo)))

	if verifyInfo.TradeStatus == epay.StatusTradeSuccess {
		// 进程内锁只是优化；重复/并发回调的正确性由 RechargeEpay 的
		// 数据库行锁 + 事务内状态校验保证（多实例部署下同样安全）。
		LockOrder(verifyInfo.ServiceTradeNo)
		defer UnlockOrder(verifyInfo.ServiceTradeNo)
		alreadyDone, err := model.RechargeEpay(verifyInfo.ServiceTradeNo, verifyInfo.Type, c.ClientIP())
		if err != nil {
			switch {
			case errors.Is(err, model.ErrTopUpNotFound):
				logger.LogWarn(c.Request.Context(), fmt.Sprintf("易支付 回调订单不存在 trade_no=%s callback_type=%s client_ip=%s verify_info=%q", verifyInfo.ServiceTradeNo, verifyInfo.Type, c.ClientIP(), common.GetJsonString(verifyInfo)))
			case errors.Is(err, model.ErrPaymentMethodMismatch):
				logger.LogWarn(c.Request.Context(), fmt.Sprintf("易支付 订单支付网关不匹配 trade_no=%s callback_type=%s client_ip=%s", verifyInfo.ServiceTradeNo, verifyInfo.Type, c.ClientIP()))
			case errors.Is(err, model.ErrTopUpStatusInvalid):
				logger.LogWarn(c.Request.Context(), fmt.Sprintf("易支付 订单状态非法 trade_no=%s callback_type=%s client_ip=%s", verifyInfo.ServiceTradeNo, verifyInfo.Type, c.ClientIP()))
			default:
				logger.LogError(c.Request.Context(), fmt.Sprintf("易支付 充值处理失败 trade_no=%s client_ip=%s error=%q", verifyInfo.ServiceTradeNo, c.ClientIP(), err.Error()))
			}
			if _, writeErr := c.Writer.Write([]byte("fail")); writeErr != nil {
				logger.LogError(c.Request.Context(), fmt.Sprintf("易支付 webhook 响应写入失败 trade_no=%s client_ip=%s error=%q", verifyInfo.ServiceTradeNo, c.ClientIP(), writeErr.Error()))
			}
			return
		}
		if alreadyDone {
			logger.LogInfo(c.Request.Context(), fmt.Sprintf("易支付 重复回调幂等忽略 trade_no=%s callback_type=%s client_ip=%s", verifyInfo.ServiceTradeNo, verifyInfo.Type, c.ClientIP()))
		} else {
			logger.LogInfo(c.Request.Context(), fmt.Sprintf("易支付 充值成功 trade_no=%s callback_type=%s client_ip=%s", verifyInfo.ServiceTradeNo, verifyInfo.Type, c.ClientIP()))
		}
	} else {
		logger.LogInfo(c.Request.Context(), fmt.Sprintf("易支付 webhook 忽略事件 trade_no=%s callback_type=%s trade_status=%s client_ip=%s verify_info=%q", verifyInfo.ServiceTradeNo, verifyInfo.Type, verifyInfo.TradeStatus, c.ClientIP(), common.GetJsonString(verifyInfo)))
	}
	if _, writeErr := c.Writer.Write([]byte("success")); writeErr != nil {
		logger.LogError(c.Request.Context(), fmt.Sprintf("易支付 webhook 响应写入失败 trade_no=%s client_ip=%s error=%q", verifyInfo.ServiceTradeNo, c.ClientIP(), writeErr.Error()))
	}
}

func RequestAmount(c *gin.Context) {
	var req AmountRequest
	err := c.ShouldBindJSON(&req)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": "参数错误"})
		return
	}

	if req.Amount < getMinTopup() {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": fmt.Sprintf("充值数量不能小于 %d", getMinTopup())})
		return
	}
	id := c.GetInt("id")
	if rejectInvalidTopUpQuota(c, id, req.Amount) {
		return
	}
	group, err := model.GetUserGroup(id, true)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": "获取用户分组失败"})
		return
	}
	payMoney := getPayMoney(req.Amount, group)
	if payMoney <= 0.01 {
		c.JSON(http.StatusOK, gin.H{"message": "error", "data": "充值金额过低"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "success", "data": strconv.FormatFloat(payMoney, 'f', 2, 64)})
}

func GetUserTopUps(c *gin.Context) {
	userId := c.GetInt("id")
	pageInfo := common.GetPageQuery(c)
	keyword := c.Query("keyword")

	var (
		topups []*model.TopUp
		total  int64
		err    error
	)
	if keyword != "" {
		topups, total, err = model.SearchUserTopUps(userId, keyword, pageInfo)
	} else {
		topups, total, err = model.GetUserTopUps(userId, pageInfo)
	}
	if err != nil {
		common.ApiError(c, err)
		return
	}

	pageInfo.SetTotal(int(total))
	pageInfo.SetItems(topups)
	common.ApiSuccess(c, pageInfo)
}

// GetAllTopUps 管理员获取全平台充值记录
func GetAllTopUps(c *gin.Context) {
	pageInfo := common.GetPageQuery(c)
	keyword := c.Query("keyword")

	var (
		topups []*model.TopUp
		total  int64
		err    error
	)
	if keyword != "" {
		topups, total, err = model.SearchAllTopUps(keyword, pageInfo)
	} else {
		topups, total, err = model.GetAllTopUps(pageInfo)
	}
	if err != nil {
		common.ApiError(c, err)
		return
	}

	pageInfo.SetTotal(int(total))
	pageInfo.SetItems(topups)
	common.ApiSuccess(c, pageInfo)
}

type AdminCompleteTopupRequest struct {
	TradeNo string `json:"trade_no"`
}

// AdminCompleteTopUp 管理员补单接口
func AdminCompleteTopUp(c *gin.Context) {
	var req AdminCompleteTopupRequest
	if err := c.ShouldBindJSON(&req); err != nil || req.TradeNo == "" {
		common.ApiErrorMsg(c, "参数错误")
		return
	}

	// 订单级互斥，防止并发补单
	LockOrder(req.TradeNo)
	defer UnlockOrder(req.TradeNo)

	if err := model.ManualCompleteTopUp(req.TradeNo, c.ClientIP()); err != nil {
		common.ApiError(c, err)
		return
	}
	common.ApiSuccess(c, nil)
}

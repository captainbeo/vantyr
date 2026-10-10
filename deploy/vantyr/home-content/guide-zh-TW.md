# Vantyr API

以遠低於官方定價的價格，暢享 Claude 與 Codex —— 一個金鑰、一個儀表板，按量付費或無限暢用。

## 5 分鐘開始使用

1. **建立帳戶** — [註冊](/register)，然後[登入](/login)。接著在 安全 → 帳戶綁定 中連結您的 **Telegram**，即可獲得 **$5 免費額度** —— 足以充分試用每一個模型，無需綁卡。
2. **儲值** — 開啟[錢包](/wallet)頁面，選擇儲值金額，並使用信用卡（Stripe）付款。
   PAYG（按量付費）費率按請求計費；詳見[模型與定價](/pricing)頁面。
3. **建立 API 金鑰** — 前往[金鑰](/keys)頁面，點擊**建立**，為其命名，然後複製金鑰。
   > **提示：** 保持勾選**無限配額**。額度欄位會限制此金鑰的總消費上限；設為無限後，支出即由錢包餘額控制。
4. **將您的工具指向 Vantyr** — 基礎 URL 為 `https://vantyr.example.com/v1`（佔位符；以正式上線網域為準），認證標頭為 `Authorization: Bearer sk-...`。

## 使用 Codex CLI

將以下內容新增至 `~/.codex/config.toml`（若檔案不存在，請先建立）：

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.example.com/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

接著匯出您的金鑰並執行：

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**推薦模型：** `gpt-6-astra`（旗艦型）、`gpt-5-6-luna`（經濟型）。Claude 模型可在任何 OpenAI 相容工具中使用。

## 使用任何 OpenAI 相容用戶端

```bash
curl https://vantyr.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Claude Code 與 Anthropic SDK 用戶：將 `ANTHROPIC_BASE_URL` 設為 `https://vantyr.example.com`，並將 `ANTHROPIC_API_KEY` 設為您的 Vantyr 金鑰。

## 無限月付 — $180

一次付款，30 天**無限**暢用 Claude + Codex。沒有按 token 計費，沒有意料之外的帳單。

- 固定 $180/月，隨時可取消（到期後存取權限即失效；再次購買即可續期）
- 包含所有模型，API 介面完全一致
- 適用公平使用速率限制

[在定價頁面訂閱](/pricing)

## 常見問題

- **"insufficient quota" 錯誤？** 您的錢包餘額已用盡 —— 請前往[錢包](/wallet)頁面儲值。
- **"429 rate limit" 錯誤？** 已達每分鐘請求上限。請稍候一分鐘，或聯繫我們提高限額。
- 使用記錄：[日誌](/logs)頁面會顯示每一次請求、其 token 用量與費用。

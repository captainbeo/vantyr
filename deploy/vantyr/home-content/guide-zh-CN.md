# Vantyr API

以远低于官方定价的价格畅享 Claude 与 Codex —— 一个密钥、一个控制台，按量付费或无限畅用。

## 5 分钟开始使用

1. **创建账户** — [注册](/register)，然后[登录](/login)。接着在 安全 → 账户绑定 中绑定您的 **Telegram**，即可获得 **$5 免费额度** —— 足以充分试用每一个模型，无需绑卡。
2. **充值** — 打开[钱包](/wallet)页面，选择充值金额，使用银行卡（Stripe）支付。
   PAYG（按量付费）费率按请求计费；详情请见[模型与定价](/pricing)页面。
3. **创建 API 密钥** — 前往[密钥](/keys)，点击**新建**，为其命名，然后复制密钥。
   > **提示：** 保持勾选**无限配额**。额度字段限制该密钥的总消费；设为无限后，支出由钱包余额控制。
4. **将您的工具指向 Vantyr** — 基础 URL 为 `https://vantyr.example.com/v1`（占位符；以正式上线域名为准），认证头为 `Authorization: Bearer sk-...`。

## 使用 Codex CLI

将以下内容添加到 `~/.codex/config.toml`（文件不存在时请先创建）：

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.example.com/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

然后导出您的密钥并运行：

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**推荐模型：** `gpt-6-astra`（旗舰）、`gpt-5-6-luna`（经济型）。Claude 模型可在任何 OpenAI 兼容工具中使用。

## 使用任意 OpenAI 兼容客户端

```bash
curl https://vantyr.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Claude Code 与 Anthropic SDK 用户：将 `ANTHROPIC_BASE_URL` 设为 `https://vantyr.example.com`，将 `ANTHROPIC_API_KEY` 设为您的 Vantyr 密钥。

## 无限月付 — $180

一次支付，30 天**无限**畅用 Claude + Codex。没有按 token 计费，没有意外账单。

- 固定 $180/月，随时可取消（到期后访问权限自动失效；再次购买即可续期）
- 包含全部模型，API 接口完全一致
- 适用公平使用速率限制

[在定价页面订阅](/pricing)

## 常见问题

- **"insufficient quota" 错误？** 您的钱包余额已用尽 —— 请前往[钱包](/wallet)页面充值。
- **"429 rate limit" 错误？** 已达到每分钟请求上限。请稍等一分钟，或联系我们提高限额。
- 使用记录：[日志](/logs)页面会显示每一次请求、其 token 用量与费用。


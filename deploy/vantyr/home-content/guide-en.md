# Vantyr API

Premium Claude & Codex access at a fraction of official pricing — one key, one dashboard, pay as you go or unlimited.

## Get started in 5 minutes

1. **Create an account** — [Register](/register), then [log in](/login). Then link your **Telegram** under Security → Account bindings to receive **$5 of free credit** — enough to try every model properly, no card needed.
2. **Add credit** — open the [Wallet](/wallet) page, choose a top-up amount, and pay by card (Stripe).
   PAYG rates apply per request; see the [Models & Pricing](/pricing) page.
3. **Create an API key** — go to [Keys](/keys), click **Create**, name it, and copy the key.
   > **Tip:** leave **Unlimited quota** checked. The quota field limits this key's total spend; unlimited lets your wallet balance control spending.
4. **Point your tool at Vantyr** — base URL `https://vantyr.example.com/v1` (placeholder; see launch domain), auth header `Authorization: Bearer sk-...`.

## Using Codex CLI

Add this to `~/.codex/config.toml` (create the file if it doesn't exist):

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.example.com/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

Then export your key and run:

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**Recommended models:** `gpt-6-astra` (flagship), `gpt-5-6-luna` (budget). Claude models work in any OpenAI-compatible tool.

## Using any OpenAI-compatible client

```bash
curl https://vantyr.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Claude Code and Anthropic SDK users: set `ANTHROPIC_BASE_URL` to `https://vantyr.example.com` and `ANTHROPIC_API_KEY` to your Vantyr key.

## Unlimited Monthly — $180

One payment, 30 days, **unlimited** Claude + Codex usage. No per-token billing, no surprise invoices.

- Flat $180/month, cancel anytime (access simply expires; re-purchase to renew)
- All models included, same API surface
- Fair-use rate limits apply

[Subscribe on the Pricing page](/pricing)

## Questions

- **"insufficient quota" error?** Your wallet is empty — top up on the [Wallet](/wallet) page.
- **"429 rate limit" error?** You've hit the per-minute request cap. Wait a minute, or contact us to raise your limit.
- Usage history: the [Logs](/logs) page shows every request, its tokens, and its cost.


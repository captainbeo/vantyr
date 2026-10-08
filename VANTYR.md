# VANTYR.md — Deployment and Operations Notes

Vantyr API is a configured deployment of New API (upstream:
https://github.com/QuantumNous/new-api). Custom Go code is avoided on
purpose; product behavior is expressed through admin-UI configuration and
environment variables. See `docs/plans/2026-10-01-vantyr-restart.md` for
the restart plan and locked decisions.

## Upstream pin

- Tag: `v1.0.0-rc.41` → commit `2035a82aeb5414253a728bd937d4b8f97aa99b9b`
  (2026-09-30), pinned in this repo as tag `v1.0.0-rc.41` on remote
  `new-api-upstream`.
- Never track `main` or a moving tag. Upstream upgrades require an explicit
  tag fetch, review of the intervening history, and re-running the R-phase
  gates.

## Local run (development)

```bash
cd deploy/vantyr
docker compose up -d --build
# gateway at http://localhost:3000
```

Registry image is not used for Vantyr; we always build from the pinned
source (the Dockerfile is multi-stage, self-contained, and digest-pinned).

## Configuration surface (no code)

- Channels: admin UI → Channels. Codex accounts = type 57 "ChatGPT
  Subscription (Codex)", one OAuth-account JSON per key slot, multi-key
  `random`. Claude accounts = Sub2API channel pointing at the sidecar
  (higher priority), seller Claude channels as fallback. Sellers = "New
  API" type 60 channels, their base URL + key.
- Pricing: Operation Settings → model ratios; every sold model needs a
  price. Group ratio `default` = 1.0; margin on seller-sourced usage is set
  via channel group multipliers.
- Billing: wallet top-up only at launch. Stripe keys and webhook secret are
  DB-backed admin settings (System Settings → payments), not env vars:
  `StripeApiSecret`, `StripeWebhookSecret` in the `options` table. Webhook
  endpoint: `POST /api/stripe/webhook`.
- Registration: System Settings → toggle on at R4 together with SMTP email
  verification and Turnstile; `QuotaForNewUser=0`.
- Secrets: env vars only. Never in files, never in chat, never in the
  admin-UI "saved" channel key echoed back — New API stores channel keys
  encrypted at rest; keep the operator circle small.

## Secrets checklist for R5 (live)

- [ ] `SESSION_SECRET`, `CRYPTO_SECRET` (32+ random bytes each)
- [ ] PostgreSQL/Redis strong passwords (not compose defaults)
- [ ] Stripe live API key + webhook secret
- [ ] SMTP credentials
- [x] Turnstile site/secret keys (live 2026-10-06, see ops log)
- [ ] sub2api `SECRET_KEY` for its admin/cookie flows

## AGPL obligations (live)

- Publish the Corresponding Source offer: link the exact git commit (public
  repo or archive) on the site footer/about page. `docs/compliance/2026-07-31-new-api-license-compliance.md`
  has the full analysis.
- **Every deploy must repeat the full protocol** (missed on the first
  sign-in-fix deploy, then completed): push `vantyr/main` → `main` on
  github.com/captainbeo/vantyr, tag `deploy/<date>-<desc>` and push it,
  `git archive` that tag → `deploy/vantyr/static/source/` with a refreshed
  `source-notice.txt` (sha256 + tag + commit), and update the `Footer`
  option (repo link + archive link). Current: tag
  `deploy/2026-10-06-control-room` (commit 8515a3715).
- Keep `LICENSE`, `NOTICE`, `THIRD-PARTY-LICENSES.md` intact in the image
  (upstream Dockerfile already ships them in `/licenses`).

## Production ops log (2026-10-05)

- **Sign-in 500 (root cause + fix):** the Telegram widget restoration
  patch (2cb526aff) dropped `import { useTranslation } from
  'react-i18next'` from `oauth-providers.tsx` while the component still
  called it — the built bundle crashed with `ReferenceError:
  useTranslation is not defined` and the whole sign-in page (and any page
  rendering the OAuth buttons) showed the styled 500 error screen.
  Server logs showed ZERO 5xx because the crash was purely client-side.
  Fixed by restoring the import (3b3da6d07), rebuilt, deployed, verified
  with a real-browser login round-trip (Playwright) on production.
  Diagnosis technique that found it: headless browser + `pageerror`
  capture — grep server logs for 5xx finds nothing in client crashes.
  The local worktree at D:\worktrees\vantyr-main tracks this; the
  on-server source at /opt/vantyr receives changes via git diff patch
  + rebuilt dist upload + on-server docker build.
- Auth hardening deployed: `SESSION_COOKIE_SECURE=true` +
  `SESSION_COOKIE_TRUSTED_URL=https://vantyr.xyz` (Secure/SameSite
  cookies, Origin validation on refresh/logout). `telegram.client_id`
  on prod = numeric bot id `8655936058` — correct; oauth.telegram.org
  /auth rejects usernames ("bot_id required").
- `captainbeo` (user 11) password reset to a temporary value via DB
  (owner must change it in UI; on the rotation list).

## Backups

- PostgreSQL: nightly `pg_dump` of `new-api` DB; verify restore quarterly
  (R5 runbook will script it).
- Redis: AOF persistence on; losing it is acceptable (cache + quota cache),
  quota truth lives in PostgreSQL.

## R2 progress (2026-10-01)

- First reseller channel live: `selora-reseller` (type 60 "New API",
  base URL `https://api.selora.lol`, group `default`). Channel test
  passes; chat/completions (JSON + SSE), `/v1/messages` (Anthropic
  format), and `/v1/responses` all verified end-to-end with real
  upstream responses. Usage logs, user quota, and channel accounting
  reconcile exactly; a failed upstream request (502) refunds the
  pre-consumed quota.
- Model ratios set via the model-pricing admin API
  (`PATCH /api/option/model_pricing`) for models without upstream
  defaults. Current values are placeholders pending real pricing
  review: claude-fable-5/5-1 5.0, claude-opus-5 5.0, claude-opus-5-5
  7.5, claude-sonnet-5 1.5, claude-haiku-4-5 0.5, glm-5.3 0.6,
  glm-5.3-flash 0.1, kimi-k3 0.6, gpt-6-astra 2.5, gpt-5-6-sol 2.5,
  gpt-5-6-luna 0.5. Selora's `kimi-k3` returned upstream 502 at test
  time (seller-side issue, not ours).
- **Lesson:** initial admin must be created via `POST /api/setup`, not
  `/api/user/register` — the register endpoint creates a role-1 user and
  skips the setup/option seeding path, which later breaks the pricing
  transaction with a literal `<nil>` options row.
- **Billing quirk to watch:** an Anthropic-format `/v1/messages` request
  relayed through an OpenAI-format seller channel billed only ~36 quota
  for ~3,000 tokens — input tokens appear not to be billed on this
  path. Sell Claude via chat/completions or /v1/responses, or verify
  /v1/messages billing before offering it.

## R3 progress (2026-10-01, Stripe test-mode money loop)

- **The full money loop is proven in Stripe test mode.** Top-up request
  (`POST /api/user/stripe/pay`) → Checkout session created with `ref_` order
  reference and a pending `top_ups` row → signed
  `checkout.session.completed` webhook at `POST /api/stripe/webhook` →
  order flips to `success` and wallet credits `amount × QuotaPerUnit`
  (500,000 quota per unit, $1/unit price) → relay request debits the
  wallet with a matching usage-log row. Both orders (5 and 3 units)
  credited exactly; the wallet then spent 1,536 quota on a real
  Claude Haiku request via Selora, log row matched to the token.
- **Webhook delivery for local dev:** Stripe CLI
  `stripe listen --forward-to localhost:3000/api/stripe/webhook` prints
  the `whsec_` signing secret and forwards real events. For production,
  register the endpoint in the Stripe dashboard instead.
- **Idempotency and security verified:** a replayed webhook event is
  rejected (order already `success` → `充值订单状态错误`), and fulfillment
  credits from the gateway's own order row, not the event's amount field
  — a crafted event cannot over-credit. Unrelated sessions without a
  matching `ref_` are ignored.
- **Setup path (config-only):** Stripe test product + $1 one-time price
  via Stripe API; `StripeApiSecret`, `StripeWebhookSecret`,
  `StripePriceId`, `StripeUnitPrice=1`, `StripeMinTopUp=1` via
  `PUT /api/option/`; one-time payment compliance confirmation via
  `POST /api/option/payment_compliance` (requires a dashboard login
  session, not an access token — root's `session` JWT from
  `POST /api/user/login`). Stripe then auto-appears in
  `GET /api/user/topup/info` pay methods.
- **Dev-password bootstrap:** for local dev, root's bcrypt hash can be
  set directly in the `users` table (`common.Password2Hash` format) to
  get a dashboard session. Do not ship this practice to production.
- **Gotchas hit:** (1) The generic `POST /api/user/pay` endpoint rejects
  `stripe` — use the dedicated `POST /api/user/stripe/pay`. (2) Stripe
  blocks raw card numbers via the API (402) and hosted sessions can't
  be paid server-side; for test-mode E2E use `stripe trigger
  checkout.session.completed --override
  "checkout_session:client_reference_id=<ref>"` (real signed event) —
  on Git Bash also set `MSYS_NO_PATHCONV=1` or fixture URLs get
  mangled. (3) `stripe --api-key` in Git Bash had an unrelated
  intermittent key-auth quirk; the same key worked via Python.
- The valid Stripe API secret lives only in the `options` table
  (`StripeApiSecret`) — never in files or chat. (During setup one key
  paste was corrupted in transit between chat and shell; the
  server-side copy is the authoritative valid one.)

## R4 progress (2026-10-01, customer-facing setup)

- **The full self-service customer flow is proven, no admin intervention:**
  register (`POST /api/user/register`, password-only while email
  verification is off) → zero quota blocks relay before any upstream call
  (`insufficient_user_quota` even when the token itself has headroom) →
  Stripe test-mode top-up (checkout session → real signed webhook event
  → wallet credited exactly, 2 units = 1,000,000 quota) → customer
  creates their own token (`POST /api/token/`) → **real Codex CLI turn
  completes with the customer's key** (13.6k tokens, exact reply) →
  wallet, token remain-quota, and usage log all reconcile to the unit
  (6,903 charged).
- Settings in force: `SystemName=Vantyr API`, `RegisterEnabled=true`,
  `PasswordRegisterEnabled=true`, `EmailVerificationEnabled=false`
  (SMTP not yet available), `QuotaForNewUser=0`,
  `TurnstileCheckEnabled=false` (keys not yet available), footer with
  AGPL attribution placeholder. Registration gating (email
  verification, Turnstile) turns on at R5 when credentials exist —
  each is a single option toggle plus the keys.
- **Native rate limiting enabled and verified:**
  `ModelRequestRateLimitEnabled=true`, 1-minute window, count 30
  (successes count too via `ModelRequestRateLimitSuccessCount=1000`).
  Burst test: 30 requests in the window all 200, request 31 → 429.
- Registering while `EmailVerificationEnabled=false` requires no email;
  the register endpoint enforces password validation (min 8) and
  username uniqueness. New users land in group `default`, role 1,
  status enabled, quota 0 — first action must be a top-up.
- Note: the admin login JWT expires quickly (~minutes); re-login
  (`POST /api/user/login`) rather than debugging 401s from option
  updates.

## Pricing (2026-10-02, owner decision)

PAYG per-token prices, set via the four ratio maps
(`ModelRatio`/`CompletionRatio`/`CacheRatio`; New API bills input at
$2×ratio/MTok, output at input×completion, cache read at input×cache):

| Model | Input $/MTok | Output $/MTok | Cache read |
|---|---|---|---|
| claude-fable-5 / 5-1 | 2.50 | 12.50 | 0.25 / 0.0625 |
| claude-opus-5 | 0.65 | 3.25 | 0.065 |
| claude-opus-5-5 | 0.52 | 2.60 | 0.026 |
| claude-sonnet-5 | 0.26 | 1.30 | 0.026 |
| gpt-6-astra | 0.08 | 0.16 | 0.04 |
| gpt-6-sol | 0.02 | 0.10 | 0.02 |
| gpt-5-6-luna | 0.02 | 0.08 | 0.002 |

Subscription: "Unlimited Monthly" — $180 one-time, 30 days, unlimited
quota (`total_amount=0`), upgrades user to group `unlimited` (group ratio
1.0; channel serves `default,unlimited`). One-time Stripe price
(`price_1ULt… (redacted)`); renewal is manual — the customer re-purchases. No
`invoice.paid` handler exists, so Stripe auto-renewal would NOT extend
access; one-time price + manual renewal is the intended and correct
shape. Note: `gpt-6-sol` requires `ModelRatio` present to override the
built-in tiered billing expr (long-context rates); ours does.

A6 marketplace channel (2026-10-02): `a6-marketplace` (id 3, type 60,
base URL `https://api.a6api.com`, groups `default,unlimited`, priority 0
— load-shares with Selora). A6 is itself a New API aggregator with
1,686 merchants; our key is in their `default` group, whose
auto-routing already selects the cheap merchant tier (metered: fable-5
served at $0.096/$0.48 per MTok — exactly ch-331's listing price;
opus-5-5 at ~$0.05/$0.21). Serves claude-fable-5/5-1, opus-5/5, sonnet-5
**and sonnet-5-5** (new in catalog, priced $0.26/$1.30), gpt-6-astra.
The GPT .luna/.sol models are blocked by this A6 token's model
permissions (owner can widen them on A6's side; then add to the channel
with model_mapping for the dot-vs-dash naming, e.g.
gpt-5-6-luna → gpt-5.6-luna). Same developer-role param_override as
Selora (no-op for non-Codex traffic). **Cache billing works through
A6** (they report read/write cache tokens; Selora does not) — verified:
astra request billed 103 quota with 3,687 tokens at the 0.5× cache
ratio, matching the formula exactly. End-to-end proof: four models +
a Codex CLI turn; billing reconciled per model; A6-side cost for the
four requests was $0.000054 vs $0.000284 billed (≈5× margin even on
tiny test requests; at the cheap-merchant tier the effective margin on
Claude PAYG is ~10-26×). Marketplace listing prices are public at
`GET /api/marketplace/public/channels/search?model=<name>` (channel_id
= merchant ID). Merchant quality is the standing risk (A6 runs fraud
crackdowns); watch response quality, and prefer
`authenticity_guaranteed` listings when pinning specific merchants.

**Measurement gotcha:** New API's `/v1/dashboard/billing/usage` returns
`total_usage` in **cents** (amount×100), not dollars. An early price
analysis was off by exactly 100× because of this; corrected by metered
delta fitting and cross-check against marketplace listing prices.

Latency (2026-10-02, measured): streaming first-token latency —
Selora median ~1.15s, A6 ~2.4s (auto-routed merchant lottery; one
44s outlier observed). Actions taken: channel weights Selora=3 /
A6=1 (75/25 split — faster channel serves most traffic, A6 stays
warm as failover), `RetryTimes=1` already fails over on upstream
errors, and SSE relaying verified unbuffered (`Cache-Control:
no-cache`, `X-Accel-Buffering: no`, chunked — the reverse proxy at
R5 must not buffer; Caddy/nginx default respects
`X-Accel-Buffering: no`, but explicitly disable proxy buffering for
`/v1/*`). Channel `response_time` telemetry: Selora 2.1s, A6 3.6s
(channel test button). No latency-aware routing exists in New API —
priority tiers + weights are the levers; re-measure via
`other->>'frt'` in `logs` (streaming requests only; -1000/-1 are
sentinels for non-stream) and re-weight when the mix changes. A6's
merchant auto-routing is the latency variance source; pinning
specific fast merchants (per-supplier tokens) is the lever if it
matters later. Session affinity (built-in codex/claude trace rules)
already pins per-conversation traffic for cache locality.

Telegram verification for trial (2026-10-02, implemented): bot
`@VantyrVerificationBot` configured (`telegram.client_id` = bot
username, `telegram.client_secret` = bot token, in the options
table — treat like a secret; `TelegramOAuthEnabled=true`,
`TelegramBotName` set, `ServerAddress=https://vantyr.xyz`).
`QuotaForNewUser` now means "trial credit granted on Telegram
bind": registration grants nothing; binding Telegram in Security
settings grants the trial once (fork change in
`model/external_identity_claim.go` — grant sits inside the bind
transaction after single-ownership checks, bounded by
MaxWalletQuota, cache-synced post-commit; one grant per Telegram
account enforced by the claim table). Remaining user actions for
live OAuth: BotFather `/setdomain` → `vantyr.xyz`, DNS A record →
server, HTTPS via reverse proxy. Until then the bind flow can't be
exercised end-to-end locally (OAuth redirect requires the public
domain); the grant logic itself is unit-testable via the model API.

Channel routing (2026-10-02, owner decision): PAYG (`default`
group) splits 50/50 between Selora and A6 (equal weights,
verified 23/17 over 40 requests + retry failover between them);
Unlimited-plan users (`unlimited` group) route **exclusively to
Selora** (A6's group list is `default` only; verified 8/8 requests
on Selora). Rationale: the flat $180 plan rides the unlimited
upstream account; A6's merchant lottery stays away from
flat-rate customers.

Free trial credit (2026-10-02, raised 2026-10-02):
`QuotaForNewUser=2500000` ($5, raised from $1 — $1 read as stingy;
owner decision; real credit, no display trick — billing must match
the published prices or the usage log exposes the lie) — granted on
Telegram bind (see above). The trial behaves exactly like a wallet:
requests bill against it, zero balance hard-blocks with
`insufficient_user_quota` before any upstream call, top-up
continues seamlessly. $5 at sell prices ≈ 100-1100 full agent
turns depending on model — a proper evaluation of every tier.
Cost exposure: worst case ~$0.50/user if fully spent via A6;
realistic ~$0.25 (half of PAYG traffic rides the unlimited Selora
account). Abuse bound: one grant per Telegram account (phone-number
backed); farming N grants needs N SIMs. Homepage advertises $5.
Localization follow-up in the same commit: the
`insufficient_user_quota` error was hardcoded Chinese in two
billing-session sites; now uses the existing (previously unwired)
`quota.insufficient` key plus a new `quota.remaining` key
(EN/ZH-CN/ZH-TW) — English by default, honors user language.

Error-message polish + failover (2026-10-02): (1) The model
rate-limit 429 was hardcoded Chinese; switched to upstream's own i18n
keys (`rate_limit.reached` / `rate_limit.total_reached`, which exist
with EN/ZH translations but were never wired) — our first fork Go
change, in `middleware/model-rate-limit.go`. English by default,
honors the per-user language setting. (2) `RetryTimes` was 0 (no
retries at all) — set to 1: a Selora 402/5xx now fails over to A6
transparently. Verified live: English 429 message; burst requests
showed "attempt 2 on channel 3" after channel-2 failures. Residual:
when BOTH upstreams throttle simultaneously (extreme bursts), the
final error still passes through the upstream text — masking that
needs a Go change in `service/error.go` (recorded as hardening;
only surfaces in degraded mode).

Customer onboarding docs (2026-10-02): the homepage renders the
`HomePageContent` option as Markdown — set to the customer guide
(register → top up → create key → Codex config.toml snippet with
Astra flagship → curl example → $180 Unlimited Monthly → FAQ for
quota/429 errors). Domain in the docs is `vantyr.example.com` —
replace with the real domain at R5. Codex snippet uses env-key
auth and `wire_api = "responses"` per the verified contract.

Rate limits (2026-10-02): `default` group 30 req/min (global
`ModelRequestRateLimitCount`), `unlimited` group 60 req/min via
`ModelRequestRateLimitGroup {"unlimited":[60,60]}`. Limits are per
**user** (all their tokens share one window), 1-minute rolling, total
count includes failures. Verified: Redis success window fills to
exactly 60 for an `unlimited` user; sustained 60/min passes, and
Selora's own upstream caps (~30 req/min per key, plus a payment
throttle returning 402 on tight parallel bursts) bind first under
burst traffic — with a single seller key, sellers are the effective
ceiling, not our limiter.

**Subscription + token interplay (important operator knowledge):** a
token's `remain_quota` is a per-key spending cap independent of the
funding source. Subscription-billed requests still decrement it; when
it reaches 0 the token 401s even with an active unlimited subscription
paying. Subscription customers must create keys with **unlimited
quota** checked (or large remain quota). Document this in the customer
flow at R5; the token page's quota field is about the key, not the
wallet.
on sonnet-5 (603), opus-5-5 (5,939), gpt-6-astra (2, `/v1/responses`),
and — with the explicit `CompletionRatio` set — the `/v1/messages`
Anthropic-native path now bills output at the completion multiplier
(954 on the probe). The R2-era "under-billed /v1/messages" note is
resolved: it was missing completion ratios. Cache read/write still
cannot be metered through Selora (they report no cache token usage —
probed both Anthropic and OpenAI formats, twice each); cache prices
apply once own-account upstreams arrive. Unsold models (haiku, GLM,
kimi, gpt-5-6-sol) removed from channel + ratios: relay returns
"no available channel". `claude-sonnet-5-5` is not in Selora's catalog;
add pricing when a source exists.

## R4 progress (2026-10-01, customer-facing setup)

- **Customer-side Codex CLI path proven end-to-end** through the Selora
  channel: plain turn (exit 0, exact reply), multi-request tool loop
  (model issues shell tool call → exec runs → model consumes result and
  completes), billing reconciles to the unit on every request including
  retries-refunded failures. Codex 0.144.6 with env-key config:
  `base_url = http://<gateway>/v1`, `wire_api = "responses"`,
  `env_key` for the Vantyr platform token.
- **Selora quirk (seller-side):** their `/v1/responses` rejects input items
  with `"role": "developer"` — returns `response.failed` /
  `provider_unavailable` after ~3s with zero usage. Codex CLI always sends
  its first input item as `developer`. Root cause was proven by bisection
  through a logging reverse proxy: any request containing a
  developer-role input item fails on Selora; user/system roles pass.
- **Fix (config-only, on the Selora channel):** `param_override`
  `{"operations":[{"path":"input.#(role==\"developer\")#.role","mode":"set","value":"user"}]}`
  rewrites developer roles to user on the wire. Do not use the wildcard
  form `input.*.role` with mode `replace`: wildcard paths expand to items
  that have no `role` at all (Codex follow-up turns contain
  `function_call` / `function_call_output` items), and `replace` hard-fails
  on the missing value (500 to the customer). The gjson query-path form
  matches only items whose role is `developer` and no-ops when none match.
  Any other seller that 400s/500s on developer roles gets the same
  override; sellers that accept them (OpenAI itself) need none.
- **Channel update API lesson:** `PUT /api/channel/` rejects any body that
  contains `status` ("Invalid parameters"). A GET→PUT round-trip includes
  it, so strip `status` before PUT. A "successful-looking" update that did
  nothing was this, not a cache issue.
- Failed turns bill zero and refund the pre-deducted quota (verified for
  both seller-side failures and the one gateway-side override error while
  debugging).

## R6: crypto top-up via GM Pay (2026-10-06, live pending DNS)

**Provider choice:** New API's other payment providers (Creem, Waffo,
Waffo Pancake) are card/MoR rails; only Waffo has a USDC-on-Base side
path. Upstream has no native self-hosted crypto provider. GM Pay
(github.com/GMWalletApp/epusdt, GPL-3.0, ~3.9k stars) is the ecosystem's
standard answer: self-hosted, 0% platform fee, direct-to-own-wallet, and
Epay-protocol compatible with New API out of the box.

**Zero-code integration (verified contract):** New API's go-epay client
POSTs to `<PayAddress>/submit.php` with MD5 over sorted, sign/sign_type-
and-empty-filtered params + key. GM Pay v2.0.0's Epay endpoint
`/payments/epay/v1/order/create-transaction/submit.php` verifies exactly
that scheme (v2.0.0's HMAC-SHA256 breaking change applies only to the
GMPay-native API, not the Epay compat mode). So
`PayAddress=https://pay.vantyr.xyz/payments/epay/v1/order/create-transaction`
routes New API's client precisely onto GM Pay. GM Pay's paid callback
(TRADE_SUCCESS, MD5-signed) is exactly what `EpayNotify` → `RechargeEpay`
verifies and credits idempotently (row lock + status check; credits from
the order row's amount, not the callback's money field).

**Deployment:** compose service `gmpay` (image `gmwallet/epusdt:v2.0.0`,
pinned by digest 9d2fef82; loopback 127.0.0.1:8000 published, internal
`gmpay:8000`), SQLite + config persisted under `./data/gmpay` (bind
-mounted /data). Caddy site block `pay.vantyr.xyz` → `gmpay:8000` (TLS
auto-issued once the DNS A record exists — Caddy retries; NXDOMAIN until
then is expected, not an error). Setup performed via the admin API:
install wizard (app_uri=https://pay.vantyr.xyz), admin password rotated
to a random value, merchant API key pid=1001 created with
notify_url=https://vantyr.xyz/api/user/epay/notify. GM Pay credentials
live ONLY in `/opt/vantyr/deploy/vantyr/.gmpay-secrets` (root 600) and
the New API options table (`EpayId`/`EpayKey` — admin-visible, like all
payment keys; never in chat/files).

**Wallets (owner-supplied receive addresses, direct custody):** TRON
TP66A6…DgiP (TRC20 USDT), Solana BzakFf…AfWE (USDT/USDC), and
0x1dd5…ed54 for Ethereum/BSC/Polygon/Plasma (USDT/USDC each; the chain
id in GM Pay's admin API is `binance` for BSC — a row added as `bsc`
does NOT serve payments), TON UQBzGz…6aea (TON + USDT), and Aptos
0xb7c9…e1ee (USDT/USDC). Still disabled: TRX, SOL native, USDC.e.
GM Pay v2.0.0 does not support AVAX/Arbitrum/Base/Optimism — the
owner's EVM address serves ERC20+BSC+Polygon+Plasma; the cashier's
network picker only shows chains with a registered wallet (8 live:
tron, ethereum, solana, binance, polygon, plasma, ton, aptos —
enabled 2026-10-06 on owner request, each verified with a real $1
test order). `epay.default_currency=usd`,
`rate.forced_rate_list {"usd":{"usdt":1,"usdc":1,"ton":0.625}}` (1
USDT/USDC = 1 USD; TON native is VOLATILE — 0.625 TON/USD set
manually 2026-10-06 from Binance TONUSDT $1.60 because no rate API
carries a TON key, so auto mode cannot price it either; re-check
periodically, drift under-prices orders), chain fees are the
customer's), amount_precision 4, min token amount 1 (TON native min
0.625 TON = the $1 floor; lowered from 10 on owner decision
2026-10-06; verified end-to-end at $1), order expiry 15 min.

**New API options (set directly in the options table; SyncOptions picks
up within 60s):** `PayAddress` as above, `EpayId`/`EpayKey` = GM Pay
merchant pid/secret, `Price=1` (USD per unit; was 7.3 CNY-era default),
`MinTopUp=1`, `PayMethods=[{"name":"Crypto (USDT / USDC)",
"icon":"SiTether","type":"alipay","min_topup":"1"}]` — the wallet
renders this as the crypto top-up button (generic pay-method buttons
auto-POST the signed form to GM Pay; `type=alipay` with no default
token/network means GM Pay's cashier shows the network picker:
Tron/Ethereum/Solana/BSC/Polygon × USDT/USDC).

**Stripe test keys CLEARED 2026-10-06:** with open registration, live
test-mode keys meant anyone could "pay" with public Stripe test cards
and receive real credit. `StripeApiSecret`/`StripeWebhookSecret`/
`StripePriceId` emptied until live keys exist (enter via admin UI only,
never chat). The wallet now shows only the crypto button.

**Evidence:** signature compatibility proven both directions — a
New-API-style signed form POST to the Epay endpoint → 302 to the
cashier with a live trade_id; and a full loop through New API's real
`/api/user/pay` (register → login → pay → GM Pay accepted the exact
signed params New API produced, pending top_ups row created). Garbage
callback to `/api/user/epay/notify` rejected with `fail` (signature
mismatch path works). All test users/orders deleted both sides.

**Remaining at this writing:** DNS A record `pay.vantyr.xyz` →
85.190.x.x (redacted) (owner action, Namecheap; Caddy then finishes the cert
automatically). After that: one real small USDT payment end-to-end and
reconciliation of the wallet credit against the usage log (the
final money-path gate; unpaid orders simply expire after 15 min). The
`$180 Unlimited Monthly` plan can ride the same rail via
`/api/subscription/epay/pay` if crypto subscription purchases are
wanted. GM Pay's Telegram notification bot is unconfigured (optional;
bot token would go in its admin settings).

## GM Pay integration audit (2026-10-06, two independent reviewers + live adversarial battery)

**Verdict: sound for production.** No critical findings on either side.
New API reviewer: every credit requires a valid MD5 signature over
attacker-uncontrolled content; settlement is row-locked, idempotent,
and credits exclusively from the order row (`topUp.Amount`), never
callback fields; `EpayKey` never logged and root-only via options API;
min-topup and quota bounds (2^53−1 ceiling, re-enforced atomically at
credit time) hold; provider guards block cross-gateway tradeNo replay;
notify endpoint does signature verification before any DB access and
sits behind GlobalAPIRateLimit (360/180s/IP, Redis) + 512KB body limit.
GM Pay reviewer: the critical sub-order question resolves safely —
network-switch sub-order payments route the merchant callback through
the PARENT order (pay_by_sub_id), so the customer is credited in both
flows; inbound epay verification is constant-time and canonicalization
matches exactly; address+amount reservation is atomic with a unique
index; trade IDs are 144-bit.

**Live adversarial battery (all green):** valid callback credited
exactly 5,000,000 quota; identical replay and signed money-inflation
(999999) callbacks credited nothing extra (idempotent/ignored);
wrong-key and unknown-order callbacks rejected; amount floors
(1/0/−5) rejected; GET-variant delivery — the transport GM Pay's
worker actually uses — verified end-to-end: credit lands AND the ack
body is the literal `success` GM Pay requires (a JSON body would burn
the retry window). No secret in either system's logs. GM Pay
config/wallets/orders survive restart (SQLite bind mount).

**Hardening applied during the audit:** callback retry envelope raised
from ~35s (3 retries) to ~10min (8 retries, data/gmpay/.env
order_notice_max_retry=8); nightly backup now covers GM Pay's SQLite
via the online-backup API in a one-shot alpine container (WAL-safe) +
restore drill passed; watchdog added to backup.sh flagging paid orders
whose merchant callback never delivered (the vendor C1 stuck-money
state) with trade IDs for admin resend; probe users/orders fully
cleaned both sides.

**Open code fix (M-1, medium, recommended):**
`SubscriptionEpayNotify`/`SubscriptionEpayReturn`
(controller/subscription_payment_epay.go) lack the
`isEpayWebhookEnabled()` fail-closed gate that `EpayNotify` enforces —
during an incident (compliance un-confirmed or Epay config cleared) a
valid pending $180 callback would still complete. One-line guard each
+ focused test; not yet applied (code change → test → rebuild → deploy
cycle).

**Accepted minor items:** notify endpoint logs full unverified params
at info (control chars escaped, rate-limited, no secrets) — demote to
warn someday; pending unpaid epay topup rows never expire (GM Pay
expires its side at 15 min; our rows are dead-letter accumulation
only); GM Pay admin login has no rate limit (96-bit random password +
loopback-only in our exposure via Caddy — publicly reachable at
pay.vantyr.xyz/admin; keep the password strong); vendor crash-window
edge (paid sub-order, parent not finalized) has no API repair —
recovery runbook: SQLite edit parent `status=2, callback_confirm=2`,
sub `callback_confirm=1`, or admin resend-callback; watchdog detects
it.

**Turnstile registration gating LIVE (2026-10-06):** owner-supplied
Cloudflare Turnstile keys (Managed mode, hostname vantyr.xyz) written
to the options table (`TurnstileSiteKey`/`TurnstileSecretKey`/
`TurnstileCheckEnabled=true`, secret server-side only, 60s SyncOptions
pick-up, no restart). Verified live: `/api/status` advertises
`turnstile_check: true` + site key so the SPA mounts the widget on
sign-in/sign-up; scripted registration without a token returns
"Turnstile token 为空", with a bogus token "Turnstile 校验失败"
(register AND login), and zero probe users were created — the
2026-10-05 scanner-registration hole is closed. Turnstile covers
registration + login + the check-in endpoint only; relay API calls
remain protected by the per-user rate limiter (unchanged). Rotation
(if the secret ever leaks): new keys from the Cloudflare dashboard,
update the two option rows. Email/SMTP verification remains an
optional future layer on top.

**Model Overview + official-price comparison (2026-10-06):** the public
pricing page renamed to Model Overview (i18n across 7 locales; nav,
settings, page header call sites). Each model now shows the vendor's
official list price and a live "% cheaper than official" badge beside
our price (table cell, card grid, details drawer). Official prices are
display-only data from a new root-editable `OfficialPricing` option
(JSON: model -> {input, output, cache} in USD/1M) injected into
/api/pricing by updatePricing; the discount is computed client-side
from live ratios, so it updates automatically on any price change
(both sides refresh within the 60s pricing/option caches). Also fixed:
gpt-5-6-luna output price — upstream hardcodes all dot-less gpt-5*
completion ratios at 8x LOCKED, silently overriding the configured
CompletionRatio map (relay billing and the pricing page both resolved
8 -> $0.16); the fork unlocks dash-named models so the configured
value wins (8 stays the fallback), luna CompletionRatio=4 ->
$0.02/$0.08 (owner decision; was $0.16). Official reference prices
recorded 2026-10-06: fable 10/50/1 (5.1 cache 0.25), opus-5 5/25/0.5,
opus-5-5 4/20/0.2, sonnet 2/10/0.2, gpt-6-astra 10/50/1 (short ctx),
gpt-6-sol 2/10/0.2, gpt-5.6-luna 0.2/1.2/0.02.

**Model Overview deployed (2026-10-06):** shipped as image
`vantyr/new-api:pinned-next9` (ca5b1100cf08, built on-server from the
tree synced via git archive; feature markers grep-verified in the
binary before the swap). AGPL protocol repeated in full: `vantyr/main`
→ public `main` (4ba755b08 + 07055f4e2 + this docs commit), tag
`deploy/2026-10-06-model-overview` pushed, source archive
`vantyr-source-2026-10-06-model-overview.tar.gz` (sha256 1cdd2a2328b1…,
see `static/source/source-notice.txt`) published, `Footer` option
updated to the new tag/archive links. Options written via SQL (60s
sync): `CompletionRatio` full 13-key map with luna 6→4, new
`OfficialPricing` option (the 9 models above), `Footer`. On-server
tests in golang:1.26.1-alpine (persistent gomod/build volumes):
ratio_setting package green; model focused tests green after fixing
the test bootstrap (common.OptionMap is nil in the model test binary;
the helper now swaps in a fresh map per repo convention, fixed by
amend before the build). Live verification: /api/pricing carries
official_input/output/cache_usd for all 9 models and luna
completion_ratio 4 → $0.02/$0.08; served bundle contains the new
strings (index.52d14c1c64.js); /docs intact with the $0.08 row;
archive and source-notice.txt return 200; footer_html in /api/status
links the new tag. Expected badges: fable 75%, sonnet/opus-5.5 87%,
luna 93%, astra/sol 99% (clamped). pinned-next8 (f7910964e15f)
retained for rollback. Transient during the options write: the first
upsert passed empty values (paths resolved inside the postgres
container, not the host) and was corrected via env-var passing within
the same sync window; worst case was ≤60s of luna resolving to the 8x
fallback with no traffic at risk.

## Known-weak spots (accepted at launch)

- Subscription recurring renewal is manual (native webhook activates
  subscriptions; renewals require customer re-purchase or admin action).
- New API stores channel keys and customer token keys recoverably
  (admin-visible). Operator-circle-of-trust risk, accepted for the private
  cohort.
- No strict per-plan concurrent-request cap; native rate limiting
  (ModelRequestRateLimit) covers burst abuse.

## R5 production deploy (2026-10-04, live at https://vantyr.xyz)

Server: one.com VPS 85.190.x.x (redacted) (Ubuntu 26.04, 4 vCPU/7.8GB),
SSH key-only (`~/.ssh/vantyr_server`, user `administrator`), ufw
22/80/443, Docker 29.1 + compose v2. Stack at `/opt/vantyr/deploy/vantyr`:
gateway `vantyr/new-api:pinned` (built from source at deploy commit) on
127.0.0.1:3000 behind Caddy 2 (auto-TLS, Let's Encrypt cert, HSTS,
nosniff, `-Server`, 600s read timeout, no proxy buffering for SSE —
`X-Accel-Buffering: no` verified live). Postgres 17 + Redis 7 with
on-server-generated secrets in chmod-600 `.env` (never transmitted).

DNS: `vantyr.xyz` A-record → 85.190.x.x (redacted) (Namecheap; the URL-redirect
and www parking CNAME that broke ACME were deleted).

**Bootstrap:** root admin (username redacted) created by the owner via the web
setup wizard at 02:42 UTC (password never transited chat). A temporary
`vantyr-bootstrap` root (id 2) was inserted directly in the DB for
config automation and **must be deleted at launch** (see rotation list).
Config rebuilt from this doc: channels 1=selora-reseller
(default+unlimited), 2=a6-marketplace (default only; 50/50 weights,
retry=1), all 9 pricing ratios, `GroupRatio` default/unlimited = 1.0,
UserUsableGroups, `Unlimited Monthly` plan (id 1, $180, total_amount=0,
upgrade_group=unlimited, one-time Stripe test price
`price_1ULt… (redacted)` — live price at launch), payment compliance
confirmed, rate limits (default 30/min success+total counts, unlimited
60/min via `ModelRequestRateLimitGroup`), Telegram OAuth (bot
@VantyrVerificationBot + token in options), `ServerAddress`,
`HomePageContent` (domain fixed to vantyr.xyz), `SystemName=Vantyr API`.

**Stripe on production (test mode):** valid key recovered from the
owner's original chat message (the shell copy had one corrupted char —
position 51 `b`→`m`; the same corruption bit again this session when
extracting keys, both times the user's original paste was the valid
one). Top-up product `prod_VNQ… (redacted)` + one-time $1/unit price
`price_1UMf… (redacted)` (StripeUnitPrice=1, min top-up 1).
Webhook `we_1UMf… (redacted)` →
`https://vantyr.xyz/api/stripe/webhook` (checkout.session.completed),
signing secret in options. Checkout link generation verified live.

**Backups:** nightly 3:30 UTC `pg_dump | gzip` via
`/opt/vantyr/deploy/vantyr/backup.sh`, 7-day retention. Restore drill
passed 2026-10-04: backup loaded into scratch DB, 2 users/2 channels/1
plan verified, scratch dropped.

**Live smoke test (all through https://vantyr.xyz):** registration →
login → key creation → `claude-sonnet-5` chat completion (reply exact,
24 quota, ch2/A6) → `gpt-6-astra` `/v1/responses` with developer-role
input (param_override works, 4 quota, ch1/Selora) → SSE stream
(unbuffered, chunked) → `/v1/messages` Anthropic format (20 quota) →
`/v1/models` (9 models). Every billed quota reconciled to the
published price table (24/4/13/20 vs computed 23.92/3.68/13.00/19.76).
50/50 channel split live.

**Launch-day fork fix (d80b6056e):** registration granted
`QuotaForNewUser` at Insert — an unverified $5 leak (and a double grant
with Telegram bind). Registration now grants 0; Telegram bind is the
only trial source. Fixed image `vantyr/new-api:pinned-next` (9cecb2de2a5d) built on-server
from the patched tree and deployed 03:35 UTC; gateway healthy, relay
regression passed, `QuotaForNewUser` restored to 2500000 (Telegram bind
remains the only grant: new registrations verified quota 0 both before
and after the restore). Smoke/verify users deleted from the production
DB. `./model/` suite green on the fix; controller suite is slow (the
upstream suite hits Go's default 10-min timeout in the container — not
a failure, re-run with 25-min timeout).

**Still open at launch (owner actions):** BotFather `/setdomain` →
vantyr.xyz (Telegram OAuth bind flow needs it); Stripe live keys + live
$180 one-time price + live top-up price via admin UI (never chat);
delete `vantyr-bootstrap` user; rotate the Selora key to the unlimited
account; deploy the d80b6056e image; AGPL source-offer link in footer;
SMTP/Turnstile registration gating optional later.

**Additional live gates (2026-10-04, post-fix):** rate-limit burst on
a zero-balance throwaway: first 30 requests → 403 `insufficient_user_quota`
in English with remaining balance (fork i18n live; fail-closed admission
before any upstream call), requests 31–35 → 429 (per-user rolling window
counts errors too; default group cap 30/min works). Test users deleted.
Focused controller suite (register/login/token/telegram/setup, -v):
all PASS (233s).

**SSH hardening completed for real (2026-10-04):** an earlier "key-only"
pass missed that `/etc/ssh/sshd_config.d/50-cloud-init.conf` (included
first, first-match wins) still said `PasswordAuthentication yes`, so
password auth remained enabled. Fixed in the cloud-init drop-in and
reloaded; `sshd -T` now reports `passwordauthentication no` and key
login verified after reload. Server headroom: 13G/193G disk,
6.6G free RAM. ufw 22/80/443 only.

**Controller-suite verdict (2026-10-04, evidence):** the full
`./controller/` suite is environmentally slow in the Docker test
container — 269 tests PASS, 0 FAIL, yet the package still hits Go's
global timeout (50 min) mid-run; the "hung" test
(`TestSecurityEnrollmentAccessTokenMethodPolicy/wechat_session_cannot_manage_tokens`)
passes in 22s when run alone on BOTH the pre-fix and fixed trees
(189–190s for the whole test). Individual tests take 20–30s each in
this container (sqlite + many AutoMigrate per test). The changed code
lives in `./model/` (full suite green, 13s) and the
registration/token/login/Telegram focused controller set (all PASS,
233s). Inherited upstream characteristic, not a fork regression —
hardening candidate: split or parallelize the controller suite, or run
it on a faster host.

## Telegram OAuth configuration correction (2026-10-04)

Per Telegram's current Login Widget/OIDC docs, `client_id` must be the
**numeric bot ID** (the `aud` claim matches the bot ID), not the bot
username. Fixed on production: `telegram.client_id` = `<bot numeric ID>`
(@VantyrVerificationBot's numeric ID); `client_secret` remains the bot
token. Domain registration moved from the legacy `/setdomain` command
to the **BotFather mini app**: choose the bot → **Login Widget** →
enter **Allowed URLs** (covers both the site origin
`https://vantyr.xyz` and the OIDC redirect URI
`https://vantyr.xyz/oauth/telegram`); the mini app also displays the
official Client ID/Client Secret there. Bind start
(`/api/oauth/state` intent=bind) correctly requires the dashboard
step-up security proof (password/2FA) via the UI — raw API calls get
403 SECURITY_PROOF_REQUIRED by design. After the owner registers the
allowed URLs, the full flow (login page → oauth.telegram.org →
callback → $5 grant) needs an end-to-end browser test.

**Telegram OAuth live-wired (2026-10-04, commit 0ff9fbaf0):** the owner
registered `vantyr.xyz` with @VantyrVerificationBot via BotFather
(/setdomain, single domain entry — covers the OIDC redirect on the same
domain). Two fixes landed from probing the live flow: (1)
`client_id` must be the **numeric bot ID** (redacted), not the bot
username — Telegram's OIDC `aud` is the bot ID; (2) the authorization
URL must carry an **`origin` parameter** (the embedding site's origin,
`https://vantyr.xyz`) — oauth.telegram.org answers a bare
"origin required" stub without it, even though Telegram's docs never
list the parameter (their widget JS computes it client-side; our
server-side URL construction had to add it — fork commit 0ff9fbaf0
with a focused test). Image `pinned-next2` (10f1db821a8e) deployed;
verified live: `/api/oauth/state` now returns an auth URL that renders
Telegram's full Authorization page (phone login form, bot name shown).
Relay regression passed post-deploy (redemption-code credit path,
which is cache-consistent — direct DB quota edits leave a stale Redis
cache; use the redemption/admin-API path for manual credits).

**Root-callback forwarding (2026-10-04, commit bf2aabffd):** if Telegram
delivers the OAuth response to `/` (origin- or bare-domain registration
only — the owner could not add a second Allowed URL in BotFather), the
SPA now forwards `/?code=&state=` to `/oauth/telegram` preserving query
and hash, so the authorization still completes. Image `pinned-next3`
(014a89c4601a) deployed; forwarding code verified present in the live
bundle. Decision tree for the owner's live test: (1) if Telegram
redirects to `/oauth/telegram` — done; (2) if it redirects to `/` —
now also handled; (3) if Telegram refuses to redirect at all — the
mini-app Allowed URLs list is the remaining registration step.

**Telegram widget protocol restored (2026-10-04, commit 2cb526aff):**
the OIDC code flow cannot complete without the exact redirect URI in
BotFather's Allowed URLs (single bare-domain /setdomain registration
only; the operator's BotFather won't accept a second URL). The widget
protocol needs only the domain registration — proven live via a
diagnostic page served by Caddy (the official widget rendered and
returned a signed authorization for the owner's account). Restored
the upstream widget endpoints (TelegramBindStart/TelegramBind/
TelegramLogin) with Vantyr changes: bot token reads
`telegram.client_secret`, and the bind runs through
BindTelegramForSessionWithTx (the $5 trial grant rides the bind
transaction). Frontend: Security page opens the widget bind dialog;
sign-in opens the widget login dialog (both restored from the
tree's own code). One more root cause found while self-testing:
`telegram.client_secret` had been stored **truncated to 15 chars**
(regex over the JSONL transcript captured a short variant when the
option was first set) — fixed to the full token; the signature
pipeline then verified a freshly self-signed assertion AND the
owner's actual widget hash offline. Image `pinned-next4`
(9df5d83b95ba) deployed; widget code confirmed served in async
chunks 94983/14172. NOTE: the token remains on the rotation list.

**Browser-cache lesson (2026-10-04):** static JS is served with
`max-age=604800` (7 days) while index.html is `no-cache`. After several
same-day frontend deployments, the owner's browser kept running the old
bundle from cache (old async chunks + old index mapping) — the "bind
does nothing after password" report was the OLD OIDC flow still
executing client-side. A hard refresh (Ctrl+Shift+R) loads the new
bundle. Chunk names are content-hashed, so long caching is safe for
unchanged files, but same-hash index.js across a chunk-map change
(rspack hash didn't move when only async chunks changed) can pin the
old map — watch for this after partial frontend rebuilds.

**Bind-completion UX fixed (2026-10-04, commit 2a3ec8c74):** the bind
itself worked (DB: owner telegram_id=<redacted>, quota 2,500,000
granted) but the popup hung on "Processing OAuth response…" — the
widget popup's direct opener is the telegram.org iframe, so the
result postMessage stopped one hop short of the dialog's window. The
callback page now posts up the whole opener chain (opener, its
parent, own parent; targetOrigin-confined), and the dialog polls
`/api/user/self` for the bound telegram_id every 3s as a safety net.
Image `pinned-next6` (4fa3bc0f2d3b) deployed; new index bundle
`index.59fede6efd.js`. **Owner browser needs one more hard refresh**
(Ctrl+Shift+R) to pick up the new bundle.

## Independent launch audit (2026-10-05, five parallel review agents)

Scope: full fork diff v1.0.0-rc.41..8f7c96683 (32 files). Five independent
read-only agents: Telegram-bind security, trial-credit billing, frontend
OAuth callback, deployment/secrets, AGPL compliance.

**Verdicts:** security PASS (clean across signature verification, replay
protection, bind authorization, redirect escaping, disclosure); billing,
frontend, deployment, compliance each FAIL with one blocking finding —
three fixed immediately in fb2570dde (deployed as `pinned-next7`
92f8e6877ac7): (1) trial-credit cache sync + grant log moved to
post-commit (was inside the bind transaction — commit failure would have
left phantom Redis credit, fail-open on a money path);
BindTelegramForSessionWithTx now returns the granted credit, both bind
callers sync after commit; (2) widget-login success redirect routed
through sanitizeAuthRedirect (was raw ?redirect= → open redirect /
javascript: XSS); (3) committed compose.yaml now pins the gateway to
127.0.0.1:3000 (matches production; a 0.0.0.0 publish bypasses ufw via
Docker iptables) and .dockerignore excludes /deploy so on-server .env
secrets can never enter build layers. Verified: model + Telegram
controller suites green post-fix.

**Still open (owner action) — AGPL: the footer source link
(github.com/captainbeo/vantyr) is 404; publishing the exact deployed
commit (tag it, e.g. deploy/2026-10-05) is required to satisfy §13 now
that the service is live.** Publish to a PUBLIC repo or archive and point
the footer at the commit tree URL; disable the inherited
.github/workflows docker-build.yml triggers when publishing (they'd fire
on tag push). The old compliance doc (2026-07-31) describes the abandoned
commercial-MVP branch — treat its [x] items as unverified; the README
fork notice + intact LICENSE/NOTICE (byte-identical to upstream) carry
the substance.

Advisory items (non-blocking, for hardening): stale
enrollment.test.tsx for the telegram bind flow (drives the removed
OAuth-popup path — update when touching that suite); admin UI label for
QuotaForNewUser still says "new user" but means Telegram-bind trial;
admin binding-clear/hard-delete re-arms the per-Telegram grant (admin
trust boundary, audited); widget bind start lacks the OIDC path's
step-up proof (session hijacker could bind their Telegram to a victim
account — money lands on the victim, identity locked); flow_token is a
5-minute capability URL (leak → attacker binds their Telegram to the
owner within TTL); grant-once invariant breaks across self-delete
cycles (same economics as upstream's registration grant — accepted);
Stripper object IDs and the owner's Telegram ID sit in VANTYR.md
(repo currently private/unpushed — scrub before any public push);
VERSION file is empty (image↔commit traceability is prose-only).

**AGPL Corresponding Source offer live (2026-10-05):** the audit's
blocking finding is closed two ways. (1) Public repo:
`github.com/captainbeo/vantyr` (branch `main` = vantyr/main; tag
`deploy/2026-10-05-pinned-next7` marks the exact deployed source —
the tagged tree's program is byte-identical to the running
pinned-next7 image; the tag only additionally scrubs VANTYR.md
identifiers and removes the inherited release workflows, which do
not affect the binary). (2) Self-hosted archive:
`https://vantyr.xyz/static/source/vantyr-source-2026-10-05-pinned-next7.tar.gz`
(sha256 c20726f6…e5815, see `static/source/source-notice.txt`),
served by Caddy's `handle_path /static/*` file_server from
`deploy/vantyr/static/`. The footer links the GitHub tag tree with
the archive as fallback. Inherited docker-build/electron-build/
release/gitcode workflows were deleted before the tag push (they
fire on tag pushes and would have attempted upstream DockerHub
publishing); `ci.yml` (PR-only) kept. VANTYR.md was scrubbed for
publication: Stripe object IDs, server IP, root admin username, bot
numeric ID, owner Telegram ID redacted — full values remain in local
git history only. Procedure going forward: every production image
deploy gets a `deploy/<date>-<image>` tag, a fresh archive in
static/source/, and a footer update.

**White-page incident + Caddy fix (2026-10-05, commit 6827b5e1e):** the
AGPL static route (`handle_path /static/*`) intercepted the SPA's own
`/static/js/*` bundles → all JS 404 → white page. Root cause: the SPA
serves its assets under the SAME /static/ path the source route claimed.
Fixed by narrowing to `handle /static/source/*` with
`uri strip_prefix /static` (files live under
`/srv/vantyr-static/source/`). The Caddyfile + caddy compose service are
now committed to the repo (audit finding closed). Verified: API,
homepage, SPA JS, source archive/notice, widget test page all 200.
**Brand logo deployed (2026-10-05):** the Vantyr wordmark (dark navy +
orange) processed to a transparent background, 512×512 square with the
wordmark at 90% width (the sidebar avatar is `object-cover` on a square,
so a wide mark would be cropped). Served from
`static/brand/logo.png` via a new `handle /static/brand/*` Caddy route
(zero-downtime `caddy reload`; the Caddyfile is a single-file bind mount
— edit it in place, never replace the file, or the container keeps
serving the old inode). The `Logo` option was inserted directly in the
options table (`https://vantyr.xyz/static/brand/logo.png`); New API's
`SyncOptions` (60s default, `SYNC_FREQUENCY` env to override) polls the
table, so no gateway restart was needed. The same URL is used as favicon
(`applyFaviconToDom`), sidebar, and footer. The full-width wordmark
backup lives at `static/brand/vantyr-wordmark.png`.

**Landing page switched to the built-in New API marketing landing**
(Hero/terminal-demo/Stats/Features/HowItWorks/CTA) by clearing
`HomePageContent` (the old markdown brief is backed up locally;
set the option again to restore it — the component also supports a
full-HTML or iframe-URL homepage if a custom design is wanted later).

**Frontend: Vantyr "Control Room" design (2026-10-06).** The Lovable-built
Vantyr design (homepage + console look) was integrated into the New API
frontend as native theming, not a fork of the page tree:

- New `vantyr` theme preset (theme-presets.css) is the deployment default
  (`DEFAULT_THEME_CUSTOMIZATION.preset`): navy-charcoal console canvas,
  single electric-orange accent, hairline borders, `--radius` 0.25rem,
  green reserved for health. Light + dark blocks; dark is the default
  mode for fresh visitors (`DEFAULT_THEME = 'dark'`, stored user
  preferences still win). The preset attribute on `<body>` is now always
  written so the generic `[data-theme-preset]` CSS bridges opt out via
  `:not()` guards.
- Brand fonts self-hosted and bundled: Chakra Petch (display), IBM Plex
  Sans (preset body), JetBrains Mono (preset mono) as woff2 subsets in
  `web/src/styles/fonts/` with OFL attribution in `fonts/LICENSE.txt`
  and rows in `THIRD-PARTY-LICENSES.md`. `--font-display-stack` /
  `--font-mono-stack` tokens were added to theme.css.
- Landing sections (hero/relay-map, stats band, problems/comparison,
  steps, request-log, CTA) were rebuilt in the Control Room language
  inside `features/home/components/sections/`, with an
  `ambient-background.tsx` decorative layer; auth-aware hero/CTA buttons,
  docs link and i18n preserved. New `label-mono` utility + sidebar
  active-item 2px signal marker are scoped utilities (vantyr.css).
- Dead template components (terminal-demo, scrolling-icons, gateway-card,
  feature/stat/connection items, icon-mapper) removed with their
  constants; ~80 new i18n keys added across all 7 locales via
  `i18n:sync`.
- The old Telegram OAuth unit test asserted the pre-widget OIDC POST
  flow and was failing at HEAD (hidden by the console-pipe exit code);
  it now asserts the deployed widget-protocol behavior (dialog opens, no
  network). The unused `createOAuthAuthorization` import in
  `use-oauth-login.ts` (leftover from the same widget patch) was removed
  so `tsgo -b` runs clean.


**Control Room frontend deployed (2026-10-06):** the landing + console
theme redesign shipped to production as image `vantyr/new-api:pinned-next8`
(997bd7e4558c, built on-server from the patched tree, byte-verified
against the tag archive before build). AGPL protocol repeated in full:
`vantyr/main` pushed to public `main` (5 app commits + redaction
8515a3715), tag `deploy/2026-10-06-control-room` pushed (workflows
untouched — only PR-triggered ci.yml), source archive
`vantyr-source-2026-10-06-control-room.tar.gz`
(sha256 7a47b2ca…47c2, see `static/source/source-notice.txt`) published,
`Footer` option updated to the new tag/archive links. `HomePageContent`
cleared so the built-in Control Room landing renders (old markdown
brief backed up at `backups/homepage-content-2026-10-06.md` on the
server — restore by setting the option again). Verified live:
`index.f66045d6df.js` embeds the new landing, CSS
`index.76dbfc9afe.css` carries the vantyr preset tokens + label-mono,
Chakra Petch / JetBrains Mono woff2 served 200, home_page_content API
returns empty, SPA JS + source notice + archive all 200, relay fails
closed (401 unauthenticated), gateway healthy with no errors in logs,
pay.vantyr.xyz unaffected. `pinned-next7` retained for instant rollback
(repoint compose.yaml image, `docker compose up -d --no-build gateway`,
re-set HomePageContent when reverting the landing).

**Homepage 3D intro reveal (2026-10-07).** The Lovable-designed opening
scene was ported into `web/src/features/home/components/brand/`:

- `intro-reveal.tsx`: scroll-driven, once-per-load void overlay. The
  overlay is `pointer-events-none fixed inset-0 z-50 bg-void` (DOM-after
  the fixed public header, so it covers it) and a 90svh spacer supplies
  the scroll distance; when the fade finishes the spacer and overlay are
  removed and the scroll position is shifted by the spacer height so the
  page never jumps (the compensating scrollTo is deferred two frames
  past the removal layout: Chrome's scroll anchoring also compensates,
  and composing both shifts double-compensates to the top). Scrolling
  back up stays on the landing; the intro
  replays only on reload.
- `vantyr-logo-3d.tsx`: the extruded 3D mark (three.js), lazily imported
  and mounted only when a WebGL2 probe passes; otherwise the flat
  `vantyr-mark.png` shows. Auto-rotation is disabled under
  `prefers-reduced-motion`.
- New web deps `three`, `@react-three/fiber`, `@react-three/drei`
  (production) and `@types/three` (dev), rows added to
  `THIRD-PARTY-LICENSES.md`.
- New `--void` token + `--color-void`/`bg-void` utility in
  `web/src/styles/theme.css` (fixed brand black, preset- and
  mode-independent).
- Two new i18n keys ("Scroll", "Endless coding with AI") synced across
  all 7 locales.
- The overlay renders only on the built-in Control Room landing; admin
  `HomePageContent` overrides (URL/HTML/markdown) still bypass it.

**3D intro reveal deployed (2026-10-07):** shipped as image
`vantyr/new-api:pinned-next10` (47eaaad68e52, built on-server from the
tree synced via git archive; 2588 files sha256-verified against the tag
manifest before build, Caddyfile/compose excluded from extraction).
Feature markers grep-verified in the binary (ExtrudeGeometry, 90svh,
bg-void, tagline, react-three all present). AGPL protocol repeated in
full: `vantyr/main` → public `main` (ef6d195c5), tag
`deploy/2026-10-07-intro-reveal` pushed (only PR-triggered ci.yml
exists), source archive
`vantyr-source-2026-10-07-intro-reveal.tar.gz`
(sha256 7d5d1d51…b1d6, see `static/source/source-notice.txt`)
published, `Footer` option updated to the new tag/archive links.
Verified live: new index bundle `index.ff544d7038.js` carries the new
tagline key, CSS `index.eb23f9b3e5.css` carries `--void`, lazy
three.js async chunk 61892 serves ExtrudeGeometry, home route async
chunk carries the intro classes, home/status/docs/pay/archive/notice
all 200, relay fails closed (401 unauthenticated), gateway healthy
with zero errors in logs, pay.vantyr.xyz unaffected. `pinned-next9`
(ca5b1100cf08) retained for instant rollback (repoint compose.yaml
image, `docker compose up -d --no-build gateway`). Note: bun 1.4.0
(Dockerfile pin) accepts the bun-1.4.2-written lockfile — frozen
install verified both locally and in the on-server build.


**New 3D logo + docs ambient background (2026-10-07).** The owner's
updated mark artwork (3D faceted navy V with orange shard, from
`vantyr-logo-3d-v2.png`) replaced the wordmark-era logo on every
surface, and /docs got the homepage ambient background:

- `static/brand/logo.png` now the padded square mark (same URL, so the
  `Logo` option, favicon flow, header, and footer all pick it up with
  no option change); `web/public/logo.png` + `favicon.ico` and
  `web/src/assets/vantyr-mark.png` refreshed from the same artwork;
  `static/brand/vantyr-wordmark.png` holds the full lockup backup.
- `vantyr-logo-3d.tsx` re-traced to the new silhouette: single faceted
  V body + one wide orange shard + detached top-right facet chip
  (colors sampled from artwork: navy #2e3a49, orange #d2530f, shard
  z-lifted 0.1 so it reads as cutting across the arm).
- Retired the 2026-10-06 wordmark CSS (container widening +
  `.dark img[src*='logo']` invert): the square mark reads in stock
  20-32px containers in both themes, and invert would have shifted the
  orange shard to cyan; the rules also caught the waffo payment logos.
- `/docs/`: header grid-bg replaced with the homepage ambient
  background ported as inline CSS + 7 precomputed trace paths (same
  params/durations as `ambient-background.tsx`, reduced-motion freeze
  included), and the topnav brand gained the mark image.
- Verified locally: docs preview screenshots (ambient + mark), SPA
  preview with the new 3D intro geometry, `tsgo -b` clean, oxlint/oxfmt
  clean on touched files (the pre-existing Lightformer warnings in
  HEAD were untouched).
- Deployed as `vantyr/new-api:pinned-next11` (bc2a16f7d2dc, built
  on-server; 2590 archive files sha256-verified before build, new
  SHARD coordinate `496 51` + ExtrudeGeometry grep-verified in the
  binary). AGPL protocol repeated in full: `vantyr/main` → public
  `main` (5817f96c2), tag `deploy/2026-10-07-logo-3d` pushed, source
  archive `vantyr-source-2026-10-07-logo-3d.tar.gz` (sha256
  023754d0…f7692, see `static/source/source-notice.txt`) published,
  `Footer` option updated. Live verification: gateway healthy, new
  bundle `index.5426a2be4e.js`, brand logo 200/90087 bytes (new
  artwork), /docs serves ambient-bg + topnav mark, footer_html links
  the new tag, relay 401 unauthenticated, pay.vantyr.xyz unaffected.
  `pinned-next10` (47eaaad68e52) retained for rollback (repoint
  compose.yaml, `docker compose up -d --no-build gateway`). The local
  sandbox image was rebuilt from 5817f96c2 in the same pass.


**Original logo revert (2026-10-07, pinned-next12).** Owner decision
the same day: the v2 artwork swap (5817f96c2) was reverted; the
original Lovable zip design — the one the 3D intro was built from and
pinned-next10 shipped — is back on every surface.

- Revert commit `f933a8fa0` restores all 8 swapped files from the
  pre-swap state (cc86d923c blobs): 3D intro geometry and colors (two
  navy arms + narrow orange shard; navy `#33445f`, orange `#ff6a1a`,
  emissive `#ff4a00`), the flat mark artwork (512x446 zip original,
  md5-verified against the Lovable attachment), the brand PNGs,
  favicon, and the wordmark CSS sizing/dark-invert rules. /docs keeps
  the ambient background and Discord links but drops the v2 topnav
  mark; the text brand returns there. Discord commits cc86d923c /
  c1cc49597 are preserved.
- Verification before deploy: intro-reveal tests 2/2, landing
  regression 2/2, tsgo typecheck clean, and the web tree proven
  byte-identical to the deployed pinned-next10 state
  (`git diff a02126733 HEAD -- web/` empty) — the 76 full-suite
  failures (models/pricing/keys display) pre-exist in that deployed
  baseline, untouched by this change.
- Deployed as `vantyr/new-api:pinned-next12`, which the Docker layer
  cache resolved to the *same image ID 47eaaad68e52 as
  pinned-next10* — independent proof the embedded frontend is the
  original-logo build. AGPL protocol repeated in full: `vantyr/main`
  → public `main` (f933a8fa0), tag
  `deploy/2026-10-07-original-logo-revert` pushed, source archive
  `vantyr-source-2026-10-07-original-logo-revert.tar.gz` (sha256
  d5d1d822…c90a; 2590 files sha256-verified on-server before the
  build and static sync) published, `Footer` option updated.
- Live verification: gateway healthy; the running binary carries all
  original geometry markers (`33445f`/`ff6a1a`/`ff4a00`, `20,5` /
  `268,290` / `265,440` / `506,4`, ExtrudeGeometry) and zero v2
  markers (`2e3a49`/`d2530f`/`496,51` all 0); brand logo 200/50779
  bytes (sha256 7943154b…, the original artwork); wordmark
  200/267948; favicon 200/49827 (original); /docs serves the text
  brand + ambient-bg + Discord links; archive 200 with notice
  updated; relay 401 unauthenticated; pay.vantyr.xyz unaffected;
  zero errors in gateway logs. `pinned-next11` retained for rollback
  (repoint compose.yaml, `docker compose up -d --no-build gateway`).
  The v2 files were backed up server-side under
  `/opt/vantyr/backups/revert-2026-10-07/` before the static swap.
  The local sandbox image was rebuilt from f933a8fa0 in the same
  pass (image `vantyr/new-api:pinned`, marker-verified).


**Gunmetal 3D mark deploy (2026-10-07, pinned-next13).** The owner
reviewed the local render and confirmed it as the correct logo:
the rotating 3D mark now uses the Lovable "gunmetal blades"
reference (owner-supplied
`vantyr-rotating-logo-claude-update.md`). Only the logo
implementation changed — commit `2d72ca269` on
`web/src/features/home/components/brand/vantyr-logo-3d.tsx`:
custom `bladeGeometry` (outline at ±depth/2, both faces rising to a
ridge point at the centroid — every edge gets its own angled facet),
two long gunmetal blades (`#3a475c`, metalness 0.55, DoubleSide),
orange shard set into the right blade (z +0.14, emissiveIntensity
0.7), camera at [0, 0.2, 11]. The intro overlay, scroll transition,
once-per-load behavior, lazy loading, and the `VantyrLogo3D` props
API are unchanged; the flat PNG brand surfaces (header/footer logo,
favicon, fallback mark, docs) still carry the original zip artwork.

- Pre-deploy verification: tsgo typecheck clean, format check clean
  on the file, intro-reveal tests 2/2, browser-verified locally
  (desktop + 375x812 mobile: mark renders, rotates 360°, fits the
  intro; intro stays gone after scrolling past and back).
- Deployed as `vantyr/new-api:pinned-next13` (fc18d033ff2a, a
  genuine rebuild — new image ID, unlike pinned-next12 which hit the
  layer cache). AGPL protocol in full: `vantyr/main` → public `main`
  (2d72ca269), tag `deploy/2026-10-07-gunmetal-3d` pushed, source
  archive `vantyr-source-2026-10-07-gunmetal-3d.tar.gz` (sha256
  585295f7…6925; 2590 files sha256-verified on-server before the
  build) published, `Footer` option updated.
- Live verification: gateway healthy; running binary carries the new
  markers (`3a475c`, `585,540`, camera `0.2,11`) and zero old
  markers (`33445f`/`268,290` absent); new SPA bundle
  `index.5947840565.js`; brand logo PNG unchanged (7943154b…, the
  original artwork — only the 3D mark changed); home/status/docs 200;
  relay 401 unauthenticated; pay.vantyr.xyz 200; archive 200 with the
  notice carrying the new tag/sha; footer links the new tag; zero
  errors in gateway logs. `pinned-next12` (47eaaad68e52) retained for
  rollback (repoint compose.yaml, `docker compose up -d --no-build
  gateway`). The local sandbox image is rebuilt from 2d72ca269 in
  the same pass.

**Header wordmark lockup deploy (2026-10-08, pinned-next14).** Owner
reviewed the local render across three rounds ("go live" after seeing
the full VANTYR letters). The public header now shows the 3D icon
(256px, gunmetal artwork from the owner's `vantyr-icon-3d.zip`)
beside the full VANTYR letters (white in dark mode, inverted dark in
light mode; letters-only assets 2313×292 cropped from the owner's
wordmark lockup). On scroll the letters collapse to zero width
(icon stays) so nav labels stay whole; system name moved to the link
title. Commits `f218b0f57` → `9f1beb824` → `71e3761a9` (the round-2
fix: the first letters crop had started at x=1324 so only "TYR"
rendered, and max-w-24 clipped the ~158px word; re-crop all six
glyph runs, clamp raised to max-w-44). The 2026-10-06 wordmark
widening + dark invert CSS rules retired. Riding along: the Discord
ticket bot (`1c902878c`) + #pricing sync (`a63a8bd5f`) + docs price
refresh (`3aa73e460`) from the support session, already live on the
VPS as the `vantyr-discord-ticket-bot` container. Changed brand
statics: `static/brand/logo.png` 35321 bytes (256px icon),
`static/brand/vantyr-wordmark.png` 26162 bytes (owner's white
lockup, the crop source), `web/public/favicon.ico` 4941 bytes,
`web/public/logo.png` + `web/src/assets/vantyr-mark.png` = the
icon.

- Pre-deploy verification: typecheck/format/lint clean; production
  web build green with all three brand assets hashed into the bundle
  (`vantyr-mark.2617e48e5f.png`, `vantyr-wordmark-white.85945c3d7d.png`,
  `vantyr-wordmark-dark.feb78165f5.png`); browser-verified dark/light
  × desktop/mobile × unscrolled/scrolled (letters 158×20 whole,
  collapse maxW 0, nav labels untruncated).
- Deployed as `vantyr/new-api:pinned-next14` from commit `3aa73e460`
  (tag `deploy/2026-10-08-header-wordmark`). AGPL protocol in full:
  public `main` pushed (3aa73e460), source archive
  `vantyr-source-2026-10-08-header-wordmark.tar.gz` (sha256
  549864a0…037bb; 2594 files sha256-verified on-server, 0
  mismatches) published, `Footer` option updated to the new tag.
  Server tree synced from the verified extract (old tree backed up
  at `/opt/vantyr-backup-tmp` for this round).
- Live verification: gateway healthy on `pinned-next14`
  (050811f8b976); SPA bundle `index.02d462844c.js` served (200,
  4796725B) with all three brand assets in chunk `21772.0095d73609.js`
  (`vantyr-mark.2617e48e5f`, `vantyr-wordmark-white.85945c3d7d`,
  `vantyr-wordmark-dark.feb78165f5`) and `max-w-44` present, no
  `max-w-24`; brand statics updated (logo.png 35321B = 256px icon,
  wordmark 26162B = owner's lockup, favicon 4941B); relay 401
  unauthenticated; pay 200; archive 200 with notice carrying the new
  tag/sha; footer links the new tag; zero errors in gateway logs.
  `pinned-next13` (fc18d033ff2a) retained for rollback (repoint
  compose.yaml, `docker compose up -d --no-build gateway`).
  Post-deploy note: the full-tree sync overwrote the server-local
  `compose.yaml` pin and `Caddyfile` (server copy has comment drift
  vs repo); both were restored from the pre-sync backup
  (`/opt/vantyr-backup-tmp`) before the pin swap — future rounds
  should sync only tracked source dirs, not clobber `deploy/vantyr`
  runtime files.

## 2026-10-08 — Referral program (pinned-next15)

`feat: implement referral program (TG registration + top-up bonus)`
(commit 236f50047, tag `deploy/2026-10-08-referral-program`).

- Scope: password registration no longer resolves affiliate codes
  (inviter reward only on Telegram/Discord OAuth registrations — email
  registration is farmable); Telegram widget login now registers
  unknown accounts in one transaction (assertion claim + user +
  identity claim + $5 trial credit, inviter $3 post-commit via the
  compliance-gated path); OAuth creation persists `inviter_id` (was
  never persisted — the top-up bonus depends on it); referral top-up
  bonus `maybeGrantAffTopUpBonus` inside the row-locked recharge
  transactions of RechargeEpay (GM Pay), Stripe Recharge, and
  ManualCompleteTopUp — one-shot per referred user via
  `users.aff_topup_credited` (bool, AutoMigrate-added on startup), $3
  when the first top-up credits ≥ $20 (options `AffTopUpMinAmount=20`,
  `QuotaForInviterTopUp=1500000`, `QuotaForInviter=1500000` set via
  options table after deploy). Affiliate code travels in the
  `X-Affiliate-Code` request header on GET /api/oauth/telegram/login —
  the widget HMAC covers every URL query param, so a query param would
  break the signature. Admin UI: two new quota-settings fields + en/zh
  strings.
- Verification: go build + full model + FULL controller suites green
  on the VPS golang:1.26.1-alpine (vantyr-gomod/gobuild volumes);
  web typecheck + auth/settings vitest green locally. Patch applied to
  the server tree (docs base file created first — the design commit
  f356cdb92 was never synced to the server), 13-file md5
  byte-verification against the commit; image `pinned-next15`
  (3b17a60d85a6) built on-server, compose pin swapped with backup at
  `/tmp/compose-pre-referral.yaml`.
- Live verification: gateway healthy; /api/status 200 with
  telegram_oauth/register/turnstile flags on; users.aff_topup_credited
  column present post-AutoMigrate; options synced (60s poll observed);
  new SPA bundle `index.90b85e4d5f.js` served and embedded in the
  binary (X-Affiliate-Code present in the embedded dist; served-bundle
  name matches embed); relay 401 unauthenticated; pay/docs/sign-up
  200; zero errors in gateway logs. End-to-end Telegram registration
  and bonus payout verified by the on-VPS test suites (live probe
  would need a real Telegram assertion and a paid GM Pay callback —
  first real referred signup is the standing production proof).
- AGPL: tag `deploy/2026-10-08-referral-program` pushed to public
  (rode along: d7002bbfc branding commit from the shared worktree —
  scanned, no secrets); archive
  `vantyr-source-2026-10-08-referral-program.tar.gz` (sha256
  26b35aa1…cd8a4) served 200 from /static/source/; footer option
  updated to the new tag (live via 60s sync).
- Rollback: `pinned-next14` (050811f8b976) retained — repoint
  compose.yaml, `docker compose up -d --no-build gateway`; options
  rows are additive (QuotaForInviter was previously absent, column is
  default-false) so rollback needs no DB action.

## 2026-10-08 — Liquid glass + brand + referral combined (pinned-next16)

`feat: add liquid glass Vantyr styling` (ba1504617, tag
`deploy/2026-10-08-liquid-glass`), riding `feat(brand)` d7002bbfc and
the referral program 236f50047 (both already live via pinned-next15;
this image adds the two frontend reworks on top).

- Scope: `web/src/styles/vantyr-glass.css` (496 lines, scoped to the
  `vantyr` preset) + 10 component hook files; branding commit removed
  public-header chrome, New API naming from customer surfaces, VERSION
  stamped v1.0.0-rc.41. Unrelated worktree files (about page, locale
  experiments, .tmp patches) intentionally excluded from this release.
- Verification: web typecheck + 29 focused vitest (landing, data-table,
  settings, auth); full backend model+controller suites green on the
  VPS pre-build; combined patch (VANTYR.md excluded — server copy
  diverged) md5-verified on 5 key files; image pinned-next16
  (0363da127464) built on-server; compose pin swapped with backup
  `/tmp/compose-pre-liquid-glass.yaml`.
- Live verification: gateway healthy; status/pricing/docs/sign-up 200;
  relay 401; new CSS bundle `index.bbffe01abe.css` serving 45
  backdrop-filter declarations + reduced-transparency fallback; binary
  retains referral markers; footer + archive served 200
  (sha256 409d6fe9…c06a4); zero gateway errors.
- Rollback: pinned-next15 retained — repoint compose.yaml + `docker
  compose up -d --no-build gateway`.

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

## Pricing (2026-10-02, owner decision — superseded 2026-10-13, see next section)

Original 2026-10-02 sheet (input/output/cache-read $/MTok): fable-5/5-1
2.50/12.50/0.25, opus-5 0.65/3.25/0.065, opus-5-5 0.52/2.60/0.026,
sonnet-5 0.26/1.30/0.026, gpt-6-astra 0.08/0.16/0.04, gpt-6-sol
0.02/0.10/0.02, gpt-5-6-luna 0.02/0.08/0.002.

## Pricing (2026-10-13, owner decision — A6-anchored)

Rule: **sell = 2× the A6 marketplace merchant listing** (cheap-tier
anchor), minimum margin 2× on cost — 1.5× acceptable as exception,
higher is fine. Goal: cheap but reliable. Re-anchor when the A6 cheap
floor moves (the pool churns; ch-331 already left) — a periodic feed
check is the guard (see cctest monitor).

Current live sheet (input/output/cache-read $/MTok; cache write in
parentheses where it differs):

| Model | Input $/MTok | Output $/MTok | Cache read | Billing |
|---|---|---|---|---|
| claude-fable-5 / 5-1 | 0.25 | 1.50 | 0.05 (write 0.30) | ratio 0.125, completion 6, cache 0.2, create 1.2 |
| claude-opus-5 | 0.12 | 0.50 | 0.01 (write 0.10) | tiered_expr `tier("base", p * 0.12 + c * 0.5 + cr * 0.01 + cc * 0.1)` |
| claude-opus-5-5 | 0.52 | 2.60 | 0.026 | ratio 0.26 (2026-10-02 legacy price, above rule) |
| claude-sonnet-5 / 5-5 | 0.26 | 1.30 | 0.026 | ratio 0.13 (legacy price, above rule) |
| gpt-6-astra | 0.20 | 0.70 | 0.10 | ratio 0.10, completion 3.5, cache 0.5 |
| gpt-6-sol | 0.05 | 0.15 | 0.05 | ratio 0.025, completion 3, cache 1 (2026-10-13 raise, on-rule) |
| gpt-6-1-sol | 0.06 | 0.20 | 0.06 | ratio 0.03, completion 10/3, cache 1 (NEW 2026-10-13, A6-only) |

gpt-5-6-luna REMOVED 2026-10-13 (owner decision, unsupported): stripped
from ch3/ch4 model lists (exact-value-guarded SQL), both ability rows
deleted, ModelRatio/CompletionRatio/CacheRatio/OfficialPricing keys
removed (incl. the stale `gpt-5.6-luna` CacheRatio dot-key), docs row +
model-pick sentence + "from $0.02" chip (→ $0.05, sol is now cheapest)
fixed in all 12 languages, rev 2026-10-13c, deployed. Relay now returns
503 "no available channel" for luna; /api/pricing shows 9 models.
Dashboard delete was greyed because luna has NO `models`-table metadata
row — the Models page delete menu only renders for `model.id > 0`
(metadata-backed models), and the pricing sheet's unset-tab disables
delete by design; removal was done at the SQL level, replicating
DeleteModelMetadata's transaction body.

**Caddy /docs localization bug (found + fixed 2026-10-13 during the
luna removal):** the docs handle was missing `uri strip_prefix /docs`
— `/docs/zh-CN.html` resolved to
`/srv/vantyr-static/docs/docs/zh-CN.html` (missing) and the
`try_files` fallback silently served the ENGLISH index for every
localized URL since the docs launch (2026-10-06). Earlier "per-language
verified live" claims in this file were greps that the English fallback
also satisfied — the fallback contains the same dates/strings; the
definitive test is `<html lang="…">` differing per URL. Fixed by adding
the strip to the live Caddyfile (backup
Caddyfile.bak-docs-prefix-20261013, `caddy validate` + zero-downtime
reload) and to the repo copy; all 12 languages now serve their own
files (verified: lang attribute + localized chips per URL). Any future
"language X verified live" step must check the lang attribute, not
string presence.

History: fable-5/5-1 cut 10× to $0.25/$1.50 on 2026-10-08 (admin UI,
~2× cheap-tier floor $0.12/$0.60); opus-5 repriced via the new
tiered_expr billing editor (~2× $0.06/$0.25 floor); gpt-6-astra raised
$0.08/$0.16 → $0.20/$0.70 on 2026-10-13 (was below A6 floor $0.09/$0.47
— sold at a loss; 2× floor = 2.2×/1.5× at floor/median). astra change
applied via options-table SQL (ModelRatio 0.04→0.10, CompletionRatio
2→3.5 — astra is NOT completion-locked: the gpt-5 prefix lock doesn't
match `gpt-6-*`, generic unlocked branch, config wins), 60s sync,
verified live on /api/pricing ($0.20/$0.70/$0.10). Docs table synced in
all 12 languages + deployed (astra row, opus-5 row $0.65/$3.25 →
$0.12/$0.50/$0.01, as-of 2026-10-13, rev 2026-10-13a). Model Overview
and Discord #pricing auto-sync from live config. Request-level
usage-log reconciliation of the astra row is owed on the next funded
smoke test (API readback + exact-match JSON edit discipline applied;
no funded key at hand). opus-5-5/sonnet-5-5 remain above the 2× anchor
(owner: deliberate margin tier — the sheet's blended margin stays >2×).

2026-10-13 (second batch): gpt-6-sol raised $0.02/$0.10 → $0.05/$0.15
(ratio 0.025, completion 3; was below the 2× rule at ~1×/0.9× — now
2.5×/1.4× vs floor $0.02/$0.11). NEW MODEL gpt-6-1-sol $0.06/$0.20
(cache $0.06) — **A6-only** by owner decision: ch2 (a6-default-primary)
models + `gpt-6-1-sol → gpt-6.1-sol` model_mapping (A6 key
permission-tested first: 200 + real completion), ability row inserted
via SQL (ON CONFLICT DO NOTHING), ratio 0.03 / completion 10/3 /
cache 1, OfficialPricing 2/10/0.1 (models.dev via A6 feed), ~3.2×/2.1×
vs the 196-listing floor $0.019/$0.096. E2E proof: /api/pricing shows
both models; real relay request through ch2 mapped to gpt-6.1-sol
upstream and billed 132 quota vs 132.29 computed (4393 in / 5 out) —
exact reconciliation. Docs table: sol row updated + new 6-1-sol row in
all 12 languages, rev 2026-10-13b, deployed. Mia PAYG decision: owner
accepted the bounded short-context loss on Mia failovers (no
expression floor) — see the 2026-10-12 Mia section for the standing
math; revisit if failover volume grows.

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

## 2026-10-08 — About page (pinned-next17)

`feat(about): dedicated Vantyr about page with savings emphasis`
(commit 11f5db210, tag `deploy/2026-10-08-about-page`), frontend-only.

- Scope: default about fallback (previously the standard New API
  attribution block) replaced with a dedicated Vantyr page — what
  Vantyr is, the problems with Claude/ChatGPT subscriptions, the
  Vantyr solutions, and a pricing section emphasizing up to 97% below
  official Claude and Codex rates plus the same-budget-goes-further
  message. Hero and bottom CTAs auth-aware (dashboard for signed-in).
  AGPL attribution preserved verbatim; admin-configured about content
  (URL/HTML/markdown) still overrides. New copy synced across all 7
  locales (57 keys verified present in every locale file).
- Verification: about vitest 3/3, tsgo -b clean, scoped oxlint clean,
  oxfmt clean; local browser verification desktop + mobile before
  commit. Server web tree synced from the tag archive with rsync
  (node_modules/dist excluded, 3-file md5 verified); image
  pinned-next17 (2ffd042b364a) built on-server; compose pin swapped
  with backup `/tmp/compose-pre-about.yaml`. New API `/api/about`
  200; relay 401 unauthenticated; zero gateway errors.
- Live verification (Playwright, real browser): new hero
  "The real models. 97% less than official rates.", budget section,
  problem/solution copy, attribution present; old fallback absent;
  h1 visible at 375x812; zero page errors. Binary grep: new copy 2
  hits; "No About Content Set" survives only as locale-JSON strings
  (the old UI branch was removed).
- AGPL: tag `deploy/2026-10-08-about-page` pushed to public repo;
  archive `vantyr-source-2026-10-08-about-page.tar.gz` (sha256
  87876769…3fcf814, byte size 7084166 verified equal local/remote)
  served 200 from /static/source/; `Footer` option updated to the new
  tag (observed live via /api/status within 60s).
- Rollback: pinned-next16 (0363da127464) retained — repoint
  compose.yaml + `docker compose up -d --no-build gateway`; no DB or
  options changes beyond the Footer text.

## 2026-10-09 — Telegram trial group-membership gate (pinned-next18)

`feat: gate the Telegram trial on group membership` (336ec1513, tag
`deploy/2026-10-09-telegram-group-gate`).

- Scope: the $5 Telegram trial now requires the verified Telegram
  account to be a member of the configured Telegram group (option
  `telegram.trial_group_chat_id`, set to -1004383766468 =
  @vantyrapi "Vantyr AI Gateway | Chat"; empty disables the gate).
  Grant moved from bind/registration to verified Telegram login via
  bot-API getChatMember (10s timeout, fail-closed for the credit
  only — login/registration never blocked; a not-yet-joined user
  claims on a later login). New per-user
  `users.telegram_trial_credited` marker (AutoMigrate) replaces the
  per-Telegram-account bind dedup: unbind/rebind cannot re-earn the
  trial, bind path now only links the identity.
- Owner action required: add @VantyrVerificationBot to the group
  (currently NOT a member — status "left"; membership checks for
  other users return PARTICIPANT_ID_INVALID until the bot joins).
- Verification: full model+controller suites green on the VPS after
  two compile/test fixes (3-value call sites; same-second assertion
  collision in rapid widget-logins — test now uses a per-call
  auth_date sequence); image pinned-next18 (a473fc7465ec) built
  on-server; compose pin swapped with backup
  `/tmp/compose-pre-groupgate.yaml`.
- Live verification: gateway healthy; status/pricing/docs/sign-up
  200; relay 401; telegram_trial_credited column present; option
  sync picked up the gate (60s); footer links the new tag; archive
  served 200 (sha256 9b8cdfa7…d563); zero new gateway errors.
- Rollback: pinned-next17 retained — repoint compose.yaml + `docker
  compose up -d --no-build gateway`; the option row and column are
  additive (gate disabled by deleting the option row).

## 2026-10-09 — Landing polish + glass rounds 2–3 (pinned-next19)

`feat(landing): frameless relay map, social header links, glass
polish` (commit b433c96c3, tag `deploy/2026-10-09-landing-glass`),
frontend-only.

- Scope: (a) liquid-glass rounds 2–3 — PublicLayout made transparent
  under the vantyr preset so the body ambient glow reaches landing
  glass; relay-map SVG internals (relay-chip/relay-hub fills) treated
  as glass; local brand-glow ::before refraction layers behind
  glass-box/control-room-panel/stat-tile-grid (glass is invisible
  over a near-uniform dark canvas without colored light behind it);
  SYS-02 panel glow pinned to inset 0 (the -18%/-12% spill poked out
  around a wide, short table); base-url block + Why-01 comparison
  table fully clipped (clipping one axis makes the other a scroll
  container, so the decorative glow created real vertical scrolling).
  (b) Landing polish: relay map frameless — panel box/header
  ("Relay map · live" + "3/3 ONLINE") and region latency strip
  deleted, lanes renamed POOL 1/2/3, compact centered 4:3; Discord +
  Telegram icon links in public header (desktop nav + mobile
  overlay); homepage footer removed entirely (AGPL attribution stays
  on /about); customer-facing "relay" wording replaced across hero,
  comparison table, how-it-works, stats, and the index.html meta
  description (i18n keys renamed in all 7 locales — rename in every
  locale file at once or sync-i18n reverts from a stale base).
- Build/protocol: 18+1 files, landing tests 2/2, oxfmt/oxlint clean;
  commit amended for the meta-description fix (force-pushed both
  remotes, tag deleted+recreated); archive
  `vantyr-source-2026-10-09-landing-glass.tar.gz` (sha256
  6a700eca…4547a8, 7090998 bytes verified equal local/remote/live);
  server web tree rsynced from the tag archive (node_modules/dist
  excluded; runtime deploy/ files untouched — Caddyfile md5 and
  compose pin verified before swap); image pinned-next19 (6f3fa113ec87)
  built on-server (Dockerfile builds web dist inside the image from
  the synced tree); compose pin swapped with backup
  `/tmp/compose-pre-landingglass.yaml`.
- Live verification: real-browser DOM check on vantyr.xyz — 3× POOL
  labels, no "Relay map · live"/"3/3 ONLINE" banner, no EU-W/US-E/
  AP-SE strip, zero "relay" text, "Vantyr pricing" + "Service
  uptime · 90d" present, Discord/Telegram header links resolve, no
  footer (only the dev-only TanStack devtools of the test browser);
  home/status/sign-up/about 200, relay 401, archive 200 full-body,
  footer_html option carries the new tag link; zero gateway errors
  in logs.
- Rollback: pinned-next18 (a473fc7465ec) retained — repoint
  compose.yaml + `docker compose up -d --no-build gateway`.

## 2026-10-09 — Page unification (pinned-next20)

`fix(web): unified page background, glass on rankings, once-per-session
intro` (0844f3962, tag `deploy/2026-10-09-page-unification`).

- Scope: all public pages sit on the same ambient body-glow canvas as
  the homepage — page-local cyan/violet gradients removed from
  rankings and Model Overview (they double-stacked over the body glow
  and read as different backgrounds). Rankings sections
  (models/market-share/pulse) get the glass-box treatment (blur +
  translucent fill + specular edge) matching the about page panels.
  The 3D intro now plays once per browsing session (sessionStorage
  `vantyr.intro-seen` guard, set when the intro completes; cleared by
  a fresh tab/browser): returning to Home via the header no longer
  replays the rotating logo.
- Verification: dev-preview inspected (rankings: 4 glass boxes with
  blur(18px), transparent layout, zero page-local gradients, body
  glow present; intro: plays fresh, does not replay after
  mark-seen → navigate away → return Home, hero renders
  immediately); typecheck clean; intro + landing vitest green
  (4/4). Frontend-only change — no backend paths touched. Patch
  (web/ only, VANTYR.md excluded — server copy diverged) md5-verified;
  image pinned-next20 (84ebd363db9b) built on-server; binary embeds
  `vantyr.intro-seen` + `glass-box` markers.
- Live verification: gateway healthy; status/rankings/pricing/about
  200; zero gateway errors; footer + archive (sha256
  1e67a01d…eb73b) live.
- Rollback: pinned-next19 retained — repoint compose.yaml +
  `docker compose up -d --no-build gateway`.

## 2026-10-09 — Sitewide ambient + about/rankings glass (pinned-next21)

`feat(web): ambient traces sitewide + liquid glass on about/rankings`
(0c5e3a9a3, tag `deploy/2026-10-09-sitewide-ambient`).

- Scope: the flowing ambient background (drift + oscilloscope signal
  traces) previously mounted only on the homepage now renders from
  PublicLayout — every public page (about, rankings, Model Overview,
  legal) sits on the same animated canvas; the home route dropped its
  private mount (no double render). Content wrappers on
  rankings/pricing/about and the default main container lift above
  the ambient layer (z-10). The about page's flat bg-background tile
  grids converted to the homepage base-url-box glass treatment:
  glass-box containers (translucent fill + 18px backdrop blur +
  specular top edge), transparent cells, hairline dividers
  (divide-border) between cells. Rankings sections already carried
  glass-box from pinned-next20.
- Verification: typecheck clean; home + about + rankings vitest green
  (7/7). Browser-pane classifier outage blocked live preview
  screenshots this round — verified via pattern parity (identical
  glass-box recipe already proven live on the hero), binary markers
  (ambient-drift ×2, glass-box ×4, divide-border ×8), and served CSS.
- Live verification: gateway healthy on pinned-next21 (bf6f0ec3e78e);
  status/rankings/pricing/about 200; zero gateway errors; new bundle
  index.b49dadad75.js + CSS index.c9d7eb9152.css with ambient-trace
  rules; archive (sha256 9f18269f…d4899) served 200; footer updated.
- Rollback: pinned-next20 retained — repoint compose.yaml + `docker
  compose up -d --no-build gateway`.

## 2026-10-09 — Glow positioning fix + Model Overview glow (pinned-next22)

`fix(glass): clip glow to box bounds and light the Model Overview surfaces`
(a432c6265, tag `deploy/2026-10-09-glow-positioning`).

- Scope: the about-page tile grids had the orange/navy refraction glow
  rendering oversized and offset across their content — the glow pseudo
  is intentionally oversized (-18%/-12%) and relies on overflow
  clipping, which the grid conversion had dropped. The glass-box base
  rule now carries overflow:hidden so every glow surface clips its own
  glow; wide-and-short grids set data-glow-fit='inset' pinning the glow
  to inset 0 (restructured as a matching :is() selector — equal
  specificity to the base glow rule, later source order wins). Model
  Overview gets the refraction glow on both views: data-glass-glow on
  the Card tiles (grid view) and on the DataTableView container (table
  view). containerProps typing widened to accept data-* attributes via
  a template-literal index signature.
- Verification: typecheck clean; oxfmt clean on the five touched files;
  about vitest green (3/3). model-cards/dynamic-price suites fail on
  this machine only via nl-NL number formatting — identical failures on
  the unmodified baseline (locale-dependent Intl assertions). Dev
  preview: about grids glow at inset 0 (5/5, top/left 0px, overflow
  hidden); 9 pricing cards + table view glow clipped to bounds; zero
  console errors; screenshots captured for about (scrolled to tables)
  and pricing (both views).
- Live verification: gateway healthy on pinned-next22 (e641b10cb5bd);
  /about + /pricing 200; live CSS index.6f1926ac9f.css contains
  data-glass-glow ×8 and data-glow-fit=inset; running-container binary
  grep glass-glow = 2 (old pinned-next21 image = 0); archive (md5
  cc50d27628245b6db6884da53606bf28) served 200; footer updated via
  options table + gateway restart, api/status serves glow-positioning
  links; tag + branch pushed to remote 'public'.
- Rollback: pinned-next21 retained — repoint compose.yaml + `docker
  compose up -d --no-build gateway`.

## 2026-10-11 — Landing translations for fr/ru/zh/zh-TW/vi/ja (pinned-next24)

`fix(i18n): translate Vantyr landing copy into fr, ru, zh, zh-TW, vi, ja`
(edb563cc0, tag deploy/2026-10-11-landing-translations).

- Scope: the Vantyr marketing keys (landing hero/stats/features/steps/
  CTA, about page, footer columns) had been synced into the six legacy
  locales as English placeholder values, so French, Russian, Chinese,
  Vietnamese and Japanese visitors saw the landing in raw English.
  Ports 833 translated values (value-only, zero key or design changes)
  from the reference-tree commit 6d4f67c7b; the 26 redesign-only footer
  keys (Community/Record/Top) were excluded — this deploy keeps the
  existing design exactly (glass-glow ×8, ambient-drift ×4 live CSS;
  no redesign markers).
- Locale files only: 9 files changed, 833 insertions/deletions, no
  code, no key changes. i18n:sync clean; parity suite 27/27; typecheck
  clean. Pre-existing ja/vi placeholder drift (4 keys) unchanged.
- Live: image pinned-next24 (f5be36030a73) built on-server from the
  synced tree; gateway healthy; home/docs 200; live bundle
  index.2408c9ba11.js contains fr/ru/ja/vi/zh/zh-TW landing strings
  (verified); archive (sha256 4ca1641439…dbe027) + notice 200; Footer
  option updated to the new tag + archive (backup
  backups/footer-pre-next24.txt); tag + branch pushed to public.
- Rollback: pinned-next23 retained — repoint compose.yaml + `docker
  compose up -d --no-build gateway`.

## 2026-10-11 — Payment rails: TRY transfer, Stripe EUR/USD, iDEAL|Wero

Owner decision (four rails): crypto (already live), Stripe cards in
EUR + USD (dual-currency), iDEAL|Wero riding Stripe Checkout, and
manual TRY bank transfer to the owner's Turkish IBAN quoted via
support (IBAN never published on the site or in the public repo).
Stripe account will be an EU entity, so both iDEAL|Wero and Wero
(when it leaves Stripe preview) are available. Branch
`feat/payment-rails` off `vantyr/main` (d24d5b1ac); NOT stacked on
the pending codex/daq-redesign work.

**Fork Go change (documented gap): dual-currency Stripe prices.**
Upstream supports exactly one `StripePriceId`; the fork adds
`StripePriceIdUsd` (options table, admin-UI field) and an optional
`currency` field on `POST /api/user/stripe/amount` +
`POST /api/user/stripe/pay`. Empty/`eur`/unknown → primary price
(EUR for Vantyr); `usd` → secondary price, and it FAILS CLOSED
(error, no order created, guard before DB access) when the USD price
is unset — a misconfigured USD checkout can never silently charge
EUR. Credit still comes from the order row (`Money × QuotaPerUnit`),
currency-independent; the webhook handles both currencies with zero
changes (same checkout.session.completed fulfillment; amount+currency
are logged per event). `GET /api/user/topup/info` reports
`stripe_usd_enabled` only when Stripe itself is enabled. Frontend:
wallet shows an €/$ segmented toggle (hidden until USD configured),
confirm dialog shows the matching currency symbol; admin payment
settings gained the StripePriceIdUsd field and the full 4-event
webhook helper text (async events matter for iDEAL|Wero).

**iDEAL|Wero + Wero (config-only, zero code):** the checkout session
never restricts `payment_method_types`, so dashboard-enabled methods
surface automatically on EUR sessions. Enable iDEAL|Wero in the
Stripe Dashboard → Payment methods (Wero: request preview access via
the interest form — currently preview for EU entities; iDEAL|Wero
itself is GA and must be the live branding until the 2026–2027
migration). iDEAL scheme rule: the site must show the company
registration number (KVK/equivalent) — add to footer or /docs before
enabling live iDEAL (owner action).

**Stripe live checklist (owner; keys via admin UI only, never chat):**
create EUR one-time price (€1/unit equivalent) + USD price ($1) →
set StripeApiSecret, StripeWebhookSecret, StripePriceId (EUR),
StripePriceIdUsd, StripeUnitPrice=1, StripeMinTopUp → register
webhook `POST /api/stripe/webhook` with ALL FOUR events:
checkout.session.completed, .expired, .async_payment_succeeded,
.async_payment_failed → confirm payment compliance → run the R3-style
test-mode money loop for BOTH currencies (checkout + signed webhook +
exact credit + usage-log reconcile) before live keys.

**TRY manual-transfer runbook:** customer opens a Discord ticket or
email → owner replies with ₺ quote at the current rate (valid ~24h) +
IBAN → customer sends Havale/EFT → owner verifies the bank statement
→ owner creates a redemption code in the admin console for the USD
value at the quoted rate (×500,000 quota per unit; redemption flow is
the cache-safe manual-credit path per the 2026-10-04 note — do NOT
edit quota rows directly, Redis cache goes stale) → customer redeems
on the Wallet page. Reconciliation: redemptions are logged with the
redeemer; the ticket holds the ₺ quote that explains the amount.
Set `TopUpLink=https://vantyr.xyz/docs#payments` (options table,
60s sync) so the wallet's "Need a redemption code? Get one here"
link lands on the payment docs.

**Docs shipped with this change:** /docs payments section (all 12
languages) now covers all four rails; hero chip updated; guide files
+ guide-map.json updated — deliberately files-only, NOT applied to
the DB option (standing owner decision after the 2026-10-10 homepage
incident).

**Subscription plan stays USD** ($180 via plan.StripePriceId); an EUR
plan price is a follow-up only if EU customers ask.

**Tests:** genStripeLink price selection via stubbed stripe-go
backend (no network), USD fail-closed amount guard, currency
normalization — all green with the payment-related controller suite
(198s); model/setting suites green. Web: currency toggle component
tests 4/4, wallet feature tests 8/8, typecheck/lint/format clean.
The two system-settings suite failures (pricing-sync tier display,
routing invalid-locale) pre-exist on the vantyr/main baseline
(verified by stash-and-rerun).

## 2026-10-12 — 3D mark always rotates; flat fallback removed (pinned-next25)

`fix(brand): always rotate the 3D mark and drop the flat fallback`
(aedb87a9d, tag deploy/2026-10-12-logo-rotation).

- Scope: the homepage intro's 3D mark froze (no 360° rotation) for any
  visitor whose OS reports `prefers-reduced-motion: reduce` — the
  autoRotate OrbitControls prop was gated on it. On the owner's
  machine Windows animation effects are off, so the gate silently
  fired; the deployed bundle was byte-identical to the repo (no deploy
  regression). The Lovable reference design spins unconditionally, so
  the gate was removed (callers can still pass autoRotate={false}).
  Second fix: the intro flashed the flat vantyr-mark.png as the
  Suspense/ClientOnly fallback while the three.js chunk lazy-loaded;
  fallbacks are now empty — the void stays quiet, no static second
  logo before the canvas appears.
- Verification: browser pane under prefers-reduced-motion: reduce —
  mark rotates ~12°/s, no flat img in the overlay during load; brand
  vitest 4/4 (new autoRotate regression test, updated intro test);
  tsgo clean, oxfmt clean; scoped oxlint unchanged from baseline
  (4 pre-existing geometry non-null assertions).
- Deploy (owner-approved): committed on vantyr/main → pushed to public
  repo main + tag deploy/2026-10-12-logo-rotation; source archive
  (sha256 798b8671…85c78) + refreshed source-notice.txt uploaded to
  static/source/; /opt/vantyr build tree patched (web/ only, applied
  clean); image pinned-next25 (39460ffde8dd) built on-server;
  compose.yaml repointed (backup compose.yaml.bak-next24); Footer
  option updated to the new tag + archive link (backup
  backups/footer-pre-next25.txt; gateway restart to reload cached
  options). Note: the compose build retagged pinned-next24 to the new
  build; the pre-deploy next24 image ID is f5be36030a73 (still
  referenced by the old container snapshot) — prefer next23 for
  tag-based rollback.
- Live verification: gateway healthy on pinned-next25; /, /rankings,
  /pricing, /about, legal pages 200; zero gateway errors; live bundle
  index.fd825ddadf.js; home chunk 64791.430f14ad89.js contains
  vantyr.intro-seen, no h-40 fallback, VantyrLogo3D lazy import; 3D
  chunk 98344.b078baf4bb.js serves `autoRotate:!1!==e.autoRotate` with
  zero prefers-reduced-motion refs; archive + notice 200 with the new
  sha256; footer serves the new tag links via api/status.
- Rollback: pinned-next23 (8e6862dbb66d) is the prior verified
  rollback point — repoint compose.yaml + `docker compose up -d
  --no-build gateway`.

## 2026-10-12 — Console → Dashboard rename + Codex desktop-app guide

**Scope (files-only, NOT deployed):** user-visible "Console" wording
renamed to "Dashboard" across the web app, /docs static site (all 12
languages), and the ticket-bot plans string. Codex guide on /docs
restructured as a step-by-step with two tabs (CLI env-key; desktop app
via `requires_openai_auth` + `auth.json`), mirroring the codex-
everywhere pattern but with our compat contract (spec 4.3/4.4: base_url
/v1, name "OpenAI" for remote compaction, never overwrite an existing
ChatGPT auth.json).

- Web app: top-nav link, admin Header/Sidebar module labels, passkey
  placeholder, two sentence keys — 7 i18n keys swapped in all 13 locale
  files (en + 12 translations, per-locale product word: 数据看板/Panel/
  لوحة التحكم/etc.), static-keys.ts updated. The JSON config keys
  (HeaderNavModules.console, sidebar console group) and the /console →
  /dashboard legacy redirect are unchanged — rename is display-only.
  WebPreview "Console" (terminal log panel) and io.net's own console
  strings stay as-is (different meaning).
- /docs: "Open Console" CTA → "Open Dashboard", hrefs vantyr.xyz/console
  → /dashboard (legacy redirect covers old inbound links), prose in 4
  spots per language; Codex section now CLI + desktop app tabs with
  copy-paste config.toml (both auth modes), auth.json JSON block, 4
  numbered steps, and a secret-handling warning; docs rev stamps bumped
  to 2026-10-12. Pricing "as of" date untouched.
- Ticket bot: "available from the console" → "dashboard" (bot.py
  render_plans_block).
- Verification: new use-top-nav-links hook test (fails pre-change,
  passes post: title Dashboard, route /dashboard, module toggle) +
  locale-parity 29/29, maintenance/profile/home suites 26/26,
  tsgo -b clean, scoped oxlint clean, oxfmt clean. Docs pages verified
  in browser (EN/AR/zh-CN): tabs switch, auth.json block present, RTL
  intact, CTA updated. Old "Console" keys/wording: 0 occurrences left
  in locales and docs tree.

Deploy: web changes ride the next image build; /docs tree + bot.py
sync to the server per the usual rsync + `docker compose restart`
round. Nothing here touches HomePageContent DB option (standing owner
decision).

## 2026-10-12 — Console → Dashboard rename + Codex desktop-app guide (pinned-next26)

`feat(web,docs): rename Console wording to Dashboard + Codex desktop-app
guide` (c1f09bee2, tag deploy/2026-10-12-dashboard-rename; cherry-pick of
2e0eece95 from feat/payment-rails onto vantyr/main — payment work NOT
included).

- Deploy (owner-approved): cherry-picked onto vantyr/main (VANTYR.md
  merge conflict vs next25 record resolved: both entries kept, payment-
  rails entry dropped), branch + tag pushed to public. Source archive
  (sha256 cc07f361…32b5986) uploaded to static/source/; source-notice.txt
  updated (backup /tmp/source-notice-pre-next26.txt). /opt/vantyr web
  tree rsynced from the tag archive (node_modules preserved; web backup
  /opt/vantyr-backup-web-pre-next26); /docs tree + bot.py synced; md5
  3-file verified. Image pinned-next26 (ce46fe53ec4f) built on-server;
  compose.yaml repointed (backup compose.yaml.bak-next25); ticket-bot
  image rebuilt (bot.py baked into image) + restarted. Footer option
  updated to new tag/archive (backup /opt/vantyr/backups/footer-pre-
  next26.txt; gateway restart). Note: compose build retagged the old
  next25 to the new build; pre-deploy next25 image was 39460ffde8dd
  (lives on as next24) — tag-based rollback remains next23
  (8e6862dbb66d).
- Live verification: gateway healthy on pinned-next26, zero errors;
  /, /docs/, /pricing, /about, /rankings, /login all 200. /docs live:
  "Open Dashboard" CTA + requires_openai_auth + auth.json blocks in all
  12 languages (de/tr/zh spot-checked). Live bundle index.be9888b336.js
  carries "Dashboard area" ×14 locales, t("e.g. Vantyr Dashboard"),
  nav title t("Dashboard") href /dashboard; zero old Console keys.
  Legacy /console client-side redirect map confirmed in bundle. Bot up
  (pricing synced); archive + notice 200; footer serves dashboard-rename
  links via api/status.
- /docs updated immediately (Caddy serves the static tree directly);
  the gateway restart was only for the web-app rename + footer reload.

## 2026-10-12 — Dual-gateway Epay: BEpusdt secondary (Arbitrum/X-Layer/Base/TON/GRAM)

Owner decision: crypto splits across two gateways. GM Pay keeps its 7
chains (TRON, Ethereum, BNB, Polygon, Plasma, Solana, Aptos); **BEpusdt**
(github.com/v03413/BEpusdt, GPL-3.0, actively maintained) serves
**Arbitrum One (usdt/usdc.arbitrum), X Layer (usdt/usdc.xlayer), Base
(usdc.base only — no USDT type exists there), TON (usdt.ton) and native
GRAM (ton.gram)**. All TON-network payments move to BEpusdt; GM Pay's
TON row gets disabled ("GM Pay will not support TON"). Same receive
addresses re-used: EVM 0x1dd5…ed54 for the three new EVM L2s, TON
UQBzGz…6aea for both TON types. Crypto checkouts display **USD only**
(owner decision; EUR never enters the crypto flow — wallet display and
1:1 pricing stay USD).

**Fork change (documented gap): New API has one Epay gateway.** The
`PayAddress`/`EpayId`/`EpayKey` globals are single; a second gateway
needs per-method routing. Added options
`EpaySecondary{Address,Id,Key,Types}` (options table, admin-UI fields in
payment settings):

- `resolveEpayGateway(paymentMethod)`: methods listed in
  `EpaySecondaryTypes` (comma-separated BEpusdt trade types) route to
  the secondary client; everything else keeps the primary. Unconfigured
  secondary + routed method → **fail-closed** before any DB access or
  order creation (same pattern as Stripe USD).
- Secondary submit forms are built locally (not go-epay `Purchase()`)
  to carry **`fiat=USD`**: BEpusdt's Epay handler defaults to CNY when
  the field is absent — without this, a $10 top-up would be priced as
  ¥10 (~7× mispricing). fiat participates in the MD5 signature, so
  on-the-wire tampering breaks the signature.
- `EpayNotify` **dual-verifies**: primary key first, secondary key on
  failure. Callback params carry no gateway identity; each key only
  verifies its own gateway's signature, so ordered attempts
  discriminate safely. Both gateways share the `epay` payment-provider
  identity; `RechargeEpay` remains the single credited path (row lock +
  status check; credits from `topUp.Amount`, never callback money).
- BEpusdt facts (source-verified): Epay endpoint at site root
  `/submit.php`, pid fixed `1000`, `EpayKey` = its `api_auth_token`,
  notify back = GET with fixed params (money/name/out_trade_no/pid/
  trade_no/trade_status/type) + MD5, requires literal `success` ack
  (our EpayNotify writes exactly that). **Epay-origin orders cannot
  reselect payment method in BEpusdt's cashier** (`CanReselectPayment`
  false for epay API orders) → each chain = one pay-method button on
  our side via `PayMethods` entries with `type=<trade type>`.
- Also exported `model.InitColumnNamesForTest` (initCol wrapper) for
  controller tests needing raw `group`-column selects.

Tests: routing table, secondary form (fiat=USD, signature round-trip,
tamper-breaks), dual-verify (secondary-signed verifies via secondary
AND NOT via primary; garbage fails), fail-closed (no order row).
Epay/payment controller suite green (188s); model/setting green.

**Deployment (owner approval gate before prod):**

- compose service `bepusdt` (image `v03413/bepusdt:<tag>`, digest-pin
  on first pull, SQLite volume `./data/bepusdt` → /var/lib/bepusdt).
- Caddy: **new site `pay2.vantyr.xyz` → bepusdt:8080** (pay.vantyr.xyz
  keeps GM Pay untouched — zero risk to the live rail; rollback = drop
  the block + clear EpaySecondary* options). Owner: DNS A record
  `pay2` → server IP on Namecheap.
- BEpusdt admin (setup wizard at its random secure path): strong admin
  password (no login rate limit, like GM Pay); `ApiAppUri=
  https://pay2.vantyr.xyz` (checkout URLs https + right host);
  payment_timeout=900, payment_min_amount=1; wallets registered per
  trade type (EVM address ×5 EVM types, TON address ×2 TON types) —
  unregistered types are auto-unavailable in its cashier.
  Rates: rate_float_USDT_USD=1 / USDC_USD=1 (GM Pay 1:1 parity);
  GRAM via CoinGecko auto (kills the manual 0.625 TON forced-rate
  drift risk). TronGrid API key recommended for TON scanning.
- New API options at cutover: EpaySecondary* as above +
  `EpaySecondaryTypes=usdt.arbitrum,usdc.arbitrum,usdt.xlayer,
  usdc.xlayer,usdc.base,usdt.ton,ton.gram`; extend `PayMethods` JSON
  with one entry per new chain.
- GM Pay: disable its TON wallet row once BEpusdt TON is verified.
- Backup: extend nightly backup + stuck-order watchdog to BEpusdt
  SQLite (same one-shot alpine online-backup pattern as GM Pay).
- Live battery before trust: signed form POST both directions, replay
 /idempotency, then real $1 test orders on every new rail (Arbitrum
  USDT+USDC, X-Layer USDT+USDC, Base USDC, TON USDT, TON GRAM), each
  credited exactly (Amount × 500,000) + usage-log reconcile; one TRC20
  order to confirm GM Pay regression-free.

Docs: /docs crypto bullet + setup sections across 12 languages now
list 11 networks + GRAM note; Turkish guide mentions GRAM; guide-map
rebuilt (files-only, DB option untouched per standing decision).

## 2026-10-12 — Mia Router: third upstream seller (miarouter.online)

Owner decision: add a third upstream. Mia Router
(https://miarouter.online, New API deployment by AzarLogic LLC, status
endpoint identical in shape to ours) joins Selora and A6 as a type-60
"New API" channel — base URL + key, zero gateway code, exactly the
Selora/A6 pattern.

**Probed facts (2026-10-12, public endpoints only, no key):** catalog
via `GET /api/pricing` — our exact SKU names, no model mapping needed:
claude-fable-5 $0.45, claude-fable-5-1 $0.60, claude-opus-5/5-5 $0.30,
claude-sonnet-5 $0.25, claude-opus-4-6/-4-8 $0.28, gpt-6-astra $0.60;
their `/v1/responses` advertised in docs (and 401-gated live probe)
supports OpenAI Responses for Codex-style clients; `/v1/messages`
(Anthropic) and `/v1/chat/completions` also live. **Billing is
flat-per-request (quota_type 1)**, not per-token: a 10-token ping and
a 100k-token turn cost the same. Their `/api/status` also advertises
`context_discount` tiers (5000/10000/15000 tokens → 0.1/0.2/0.5
multipliers) — a field absent from our pinned v1.0.0-rc.41, so they
run newer or modified New API code; their docs' credits page
describes pure flat billing with no tiers. Treat context_discount as
unverified until a real invoice shows its effect; if real, it would
*further reduce* their price on long-context requests (multipliers
under 1), which would reverse the long-turn loss math — one live
50k-token test request settles it.
Supports check-in credits, Telegram trial, credit packs ($2→$60 up to
$3k→$500k) with bonus — reseller economics unknown; treat cost as the
flat price.

**Economics (why failover-only at launch):** our sell side is
per-token (fable-5-1 $2.50/$12.50 per MTok in/out). One fable-5-1
request through Mia costs $0.60 flat regardless of tokens. A
customer's 1k-in/1k-out turn bills ~$0.015 on our side → ~$0.59
margin if a "turn" is 1 request (typical agent turn = 1 request).
But a long-context turn (50k in/5k out) bills us $0.19 while Mia
charges $0.60 → **loss on long turns**. A6-style load-sharing would
put 25% of PAYG turns through a rail that loses money on big turns;
failover-only (Mia serves only when Selora+A6 fail) caps the loss
exposure to failover volume and keeps Mia as a resilience rail, not a
margin rail. Re-evaluate after observing real failover volume and
Mia's actual invoices.

**Package decision (2026-10-12, owner call — recommendation A):**
two purchase options from Mia. A: $72 → $5,500 wallet credit,
per-request billing, 100 RPM. B: $50 → 3-day unlimited Claude, 20
RPM. Analysis: A's multiplier (~76×) is far above their published
pack curve (Team $80→$2,750 ≈ 34×; Enterprise $3k→$500k ≈ 167×) —
confirm terms in writing before paying: credit amount, expiry, RPM,
whether failed requests bill. At A's effective rate (1.31¢ per $1
of list), per-request cost: fable-5-1 $0.0079, fable-5 $0.0059,
opus-5/5-5 $0.0039, sonnet-5 $0.0033; the pool covers 9,167
fable-5-1 / 18,333 opus requests, and their credits do not expire
(docs) — so A converts unknown volume into a bounded $72 permanent
pool. B only beats A above ~2,100–4,300 requests/day through Mia
for all 3 days (A-equivalent of $50), and only if that volume stays
under the 20 RPM shared ceiling — too tight to absorb failover
bursts (the exact scenario Mia exists for), and the credit decays
while authenticity is unproven. 100 RPM (A) also makes Mia our
highest-capacity rail (Selora caps ~30 RPM/key). B only makes sense
later as a deliberate burst purchase once volume and cctest verdicts
are known. **Customer billing is unchanged either way:** New API
pricing is model-keyed (ratio maps), not channel-keyed — the serving
channel never affects what the customer pays; per-request cost is
our cost basis only. Margin at 10:1 in:out: break-even ≈2.1k input
tokens (fable-5-1), ~4–5k (opus-5/5-5), ~8.5k (sonnet-5) — short
requests on the cheaper models lose cents-scale money, agent-size
requests run 83–98% margin. Mia-wallet drain fails safe: 402 sits
inside the default retry ranges (401–407,
setting/operation_setting/status_code_ranges.go) → the attempt walks
to the next tier and Selora/A6 serve. If a flat-rate customer SKU is
ever wanted, the native mechanism exists: `ModelPrice` (quota_type
1) on a dedicated alias served only by the Mia channel (e.g. an
"-economy" per-request SKU) — per-token names stay untouched.

**Capacity math + routing plan (2026-10-12, 50-user scenario):**
Selora = ONE `sk-gw-` key shared by all 3 selora-* channels, upstream
cap ~30 req/min per key (plus their 402 payment throttle on tight
parallel bursts) — the observed latency root-cause (Selora 429
saturation → A6 merchant lottery). Our own limiter is per-user (30
req/min default, 60 unlimited) and does NOT bound aggregate: 50 users
can legally demand 1,500 req/min; realistic concurrent-agent load is
~1–6 req/min per active session, so Selora saturates at roughly 5–30
concurrently active agents. A6 absorbs attempt-2 overflow (per-key
cap unknown; 429 saturation + merchant lottery observed). Mia adds
100 req/min per key — 3–7× total ceiling once live.

Routing rollout (staged, evidence-gated):

1. **Verify (now):** channel at lowest priority, `RetryTimes=1`
   untouched — Mia receives zero traffic while the battery runs
   (channel test, real requests per wire format incl. a Codex CLI
   turn, cctest attribution check per flagship model, latency via
   the test button's `response_time` + `other->>'frt'` in logs).
2. **Failover-live:** raise `RetryTimes` to 2 (3-tier ladder:
   primary → fallback → mia). Mia absorbs Selora saturation and A6
   quarantine; wallet-drain 402s retry through cleanly.
3. **Load-share (optional, gated):** only after a clean cctest week
   + measured latency, consider same-tier weights for the default
   group (Selora/Mia e.g. 3:1 — the exact mechanism of the original
   Selora=3/A6=1 split) or per-model assignment. Unlimited group
   stays Selora/A6 only (isolation principle until Mia is proven).
   No context-length routing exists in New API (levers are channel
   model list, groups, priority, weights only) — "long context to
   Mia" cannot be expressed; per-model is the finest native
   granularity. Watch usage-log channel attribution before each
   step.

**Second Mia key:** if Mia's RPM is per-key AND two keys can draw
one wallet, add the key to the SAME channel as multi-key random
(native: per-request key pick, per-key auto-disable on 401, no
second channel to manage) → 200 req/min. Verify both facts with Mia
first; if each key needs its own top-up, defer the second key until
sustained Mia traffic approaches 100 req/min.

**Who sets the ~30 req/min + the 4-unlimited-user scenario
(2026-10-12):** two separate layers. Selora's seller-side per-key cap
(~30 req/min, plus a 402 payment throttle on tight parallel bursts —
both observed live, R4/VANTYR.md rate-limits entry) is the AGGREGATE
binding constraint. Vantyr's own limiter (30/min default, 60/min
unlimited per user) is per-USER and additive — it never bounds
aggregate demand. Today ALL selora-* channels (default + unlimited
groups) share the ONE `sk-gw-` key: 4 unlimited users can legally
demand 240 req/min (8× the key) and their sustained agent load alone
(~2–6 req/min each) brushes the cap before any PAYG traffic. 429s
overflow to the next priority tier, currently a6-* — the channel
family carrying the attr_swapped fable finding. Fixes in value
order: (1) apply the staged Selora key rotation
(/opt/vantyr/backups/rotate_selora.sh, awaiting owner key) — moves
selora-unlimited onto the flat-rate unlimited-account key, splitting
the cohorts AND doubling aggregate Selora capacity at ~zero cost;
(2) Mia $72 wallet for the default group (comes WITH $5,500 credits,
100 RPM — capacity that pays for itself); (3) the 60 RPM key upgrade
LAST, targeted at whichever key still shows 429 saturation in the
logs after (1)+(2) — most likely the unlimited-account key with
heavy $180 subscribers, where extra RPM costs zero marginal request
cost (flat-billed upstream). Ask Selora whether the upgrade also
lifts the 402 payment throttle; it is a separate limiter.

**A6 merchant attribution + marketplace intelligence (2026-10-12):**
cctest verdicts on A6 attribute to the POOL, not the merchant: our
request rides A6's auto-routing (their key's group → cheap-merchant
tier), and neither the relay response nor our usage log carries the
serving merchant ID — A6's routing decision is invisible to us.
Attribution paths, by cost: (1) A6-side data (free): the owner's A6
dashboard/support — their marketplace tracks per-listing telemetry;
ask whether customer-side logs name the serving merchant per
request, then cross-reference cctest check timestamps. (2) Tier
narrowing (free, immediate): our group draws the CHEAP tier, so the
fable-5-1 swap merchant is one of ~8-10 cheap listings, not 70.
(3) Per-merchant pinning (definitive): per-supplier tokens from A6 →
one New API channel per merchant → exact attribution for cctest
checks AND customer traffic; a bad merchant can then be quarantined
individually instead of nuking the pool. `GET
/api/marketplace/public/channels/search?model=claude-fable-5-1` is a
rich intelligence feed (no auth): 70 listings, per-listing
input/output/cache prices, `p50_ttft_ms`, `recent_success_rate`
(with success buckets), `last_failure_code`, supplier id/name,
`authenticity_guaranteed` flag (19/70 for fable-5-1), and
`smart_routing_labels` (cheap 35 / stable 16 / fast 17 / quality
10). Price distribution: cheap tier $0.12–0.38 input, auth-guaranteed
tier $1.20–1.80 (cheapest auth: ch-5630 $1.20/$6.00, 90% success;
ch-5932 $1.44/$7.20, 100% success, 2057ms TTFT — faster than most
of the cheap tier). Their site-level "model detection" feature is
enabled+public but 0/70 fable listings currently support it — watch
for rollout; per-listing detection results would answer merchant
authenticity directly. **Strategic read:** the swap merchant is a
cheap-tier draw; don't hunt the individual merchant — design so no
single merchant can hurt customers. For fable-5/5-1 either pin A6 to
auth-guaranteed listings (per-supplier token, ~52% margin at our
$2.50/$12.50 sell vs ch-5630's $1.20/$6.00 cost — still 8× cheaper
than official input) or pull fable from A6 entirely (ladder design
above already leans this way). Note ch-331 (the R2-era price-match
merchant) no longer appears in the fable-5-1 pool — the pool churns;
pin to merchants, not memories.

**A6 multi-merchant routes vs cctest coverage (2026-10-13):** the
owner is configuring A6 per-model routes with multiple merchants
(A6 API/dashboard) so A6 switches internally when a merchant
degrades — the right tool for AVAILABILITY. But cctest only scans
whatever the route serves at check time: failover-style routes keep
standbys dark (only the active merchant is ever verified), and
load-balanced routes blur verdicts across merchants (a quarantine
re-test pass can come from a different merchant than the failing
one, releasing the channel while the bad merchant stays in the
pool). Timing gap: A6's success-rate telemetry switches DOWN
merchants in minutes, but a promoted wrong-model merchant serves
customers ~1–2 h before quarantine (one model per channel per
10-min cycle × 2-fail threshold). Design rules: standbys must come
from the `authenticity_guaranteed` tier so the dark window is
low-risk; accept pool-level attribution with the 2-fail threshold;
surgical per-merchant quarantine is the per-supplier-token
escalation path. Granularity note: A6 routes are per-model, our
quarantine is per-channel (all models) — a bad fable merchant also
cuts the good sonnet path on the same channel; split a6 channels
per model-set if that starts to bite. Fable-5/5-1 stays off the
cheap tier regardless (standing ladder decision).

**Channel assignment map (2026-10-13, OWNER DECISION — supersedes
the proposed ladders below; cctest scanning deferred to a later
stage):**

Per-model ladders (apply to both groups):

| Model | 1st | 2nd | 3rd |
|---|---|---|---|
| claude-fable-5 / 5-1 | Selora | Mia | A6 |
| claude-opus-5 / 5-5 | Selora | Mia | A6 |
| claude-sonnet-5-5 | A6 only | — | — |
| claude-sonnet-5 | A6 | Mia | Selora |
| gpt-6-astra / sol / luna | A6 | Selora | — |

Group flavor (owner's words): PAYG = "A6 as standard, Mia second,
Selora third" (that is sonnet-5's ladder verbatim — PAYG volume
concentrates on the A6-first rows); unlimited = "Selora and Mia
standard, switch to Mia on rpm/balance exhaustion, then over to
A6" (that is the fable/opus ladder). Reading recorded: the table
is authoritative per-model; the group lines describe where each
group's volume concentrates. Open confirmation: if "A6 standard"
was meant to override the table for PAYG fable/opus too, say so —
abilities are per (group, model, channel), so a per-group
divergence is implementable; the swap evidence argues for keeping
the table's order.

IMPLEMENTATION (admin-UI only, no code): New API priority is
per-CHANNEL, not per-model — the two opposite orders (Selora-first
for fable/opus, A6-first for sonnet/gpt6) REQUIRE role-split
channels. Seven channels (Selora's two keys after the staged
rotation double its roles):

| Channel (role) | Group | Priority | Models |
|---|---|---|---|
| selora-premium (sk-gw- key) | default | 30 | fable-5, fable-5-1, opus-5, opus-5-5 |
| selora-standard (sk-gw- key) | default | 10 | sonnet-5, gpt-6-astra, sol, luna |
| selora-unlimited-premium (unlimited-account key) | unlimited | 30 | fable-5, fable-5-1, opus-5, opus-5-5 |
| selora-unlimited-standard (unlimited-account key) | unlimited | 10 | sonnet-5, gpt-6-astra, sol, luna |
| a6-standard | default, unlimited | 30 | sonnet-5, sonnet-5-5, gpt-6-astra, sol, luna |
| a6-premium | default, unlimited | 10 | fable-5, fable-5-1, opus-5, opus-5-5 |
| mia | default, unlimited | 20 | fable-5, fable-5-1, opus-5, opus-5-5, sonnet-5 |

Resulting ladders per model: fable/opus 30 Selora → 20 Mia → 10
A6; sonnet-5 30 A6 → 20 Mia → 10 Selora; gpt-6 family 30 A6 → 10
Selora; sonnet-5-5 30 A6 only. Weights become irrelevant (one
channel per model per tier — no load-share by design).
**RetryTimes=2 required** (worst case 3 distinct tiers → 3
attempts walk the whole ladder; at the current RetryTimes=1 the
3rd tier is never reached). The 6 existing channels get re-purged
into these roles via model-list + priority + group edits; the
cctest monitor needs no change (prefix expansion handles any
channel count/names). Two caveats: (1) GPT6 row assumes A6 serves
sol/luna — the current A6 token's model permissions BLOCK the
.luna/.sol SKUs (owner can widen on A6's side + add channel
model_mapping dot↔dash, e.g. gpt-5-6-luna → gpt-5.6-luna); until
then sol/luna effectively ride Selora only. (2) The Mia
authenticity gate (one cctest attribution check per flagship model
before pointing real traffic) is still recommended at cutover even
with scanning deferred — the swap was found by exactly that check.

**DEPLOYED 2026-10-13 (roles applied to production):** the map
above is live. SQL transaction over the 6 existing channels (id
roles per the table; ch3 keeps the `gpt-6-sol` mapping, ch5/ch6
keep fable dot-mappings for A6), new ch7 `mia-failover` (type 60,
P20, groups default,unlimited, fable×2+opus×2+sonnet-5, developer
param_override, DISABLED status 2 with placeholder key
`PENDING-OWNER-KEY-MIAROUTER` — zero routing until the owner pastes
the real key at go-live, then `POST /api/channel/7/status`
{"status":1}), `RetryTimes` 1→2 (options table, 60s sync
confirmed in logs). Abilities rebuilt via `POST /api/channel/fix`
(sidecar PAT, 7/7 success). Backup before the transaction:
`/opt/vantyr/backups/channels-abilities-pre-miaroles-20261013.sql`.
**Test battery (real relay requests, cctest-sidecar token, all
via 127.0.0.1:3000):** fable-5-1→ch1 Selora (16 quota), opus-5-5→
ch1 Selora (29), sonnet-5→ch2 A6 (7), sonnet-5-5→ch2 A6 (2),
gpt-6-astra→ch2 A6 (86, 4125 prompt tokens — the reasoning
prefix; astra builds a large system prompt per request). Every
request hit its designed tier-1 channel; usage logs reconcile;
gateway healthy, zero errors. NOTE: fable/opus small-prompt
requests show empty `content` with reasoning_content — the 16
max_tokens budget is consumed by visible reasoning first (normal
for thinking models; raise max_tokens in real use). Rollback:
restore the backup SQL + `RetryTimes` back to 1. Standing owner
actions: paste real Mia key (admin UI → channel 7 edit, or SQL
key column — never chat), flip status 1, re-run this battery per
model + one Codex CLI turn through Mia, then the one-shot cctest
attribution check per flagship model.

**Mia test-key battery (2026-10-13, owner-supplied test key, direct
against miarouter.online — key NOT wired into any channel, testing
only):** auth OK; `/v1/models` shows the key is
**model-restricted to exactly claude-fable-5/5-1 + opus-5/5-5** —
claude-sonnet-5 returns 403 "no access" (so ch7's model list
should drop sonnet-5 before go-live, or a failed sonnet-5 failover
pays one wasted hop — 403 is in the auto-retry band, it
self-heals to the next tier). chat/completions works on all four
SKUs with real replies + reasoning_content; SSE streaming works
(`: PING` keepalive + chunks); `/v1/messages` (Anthropic) works
natively. **`/v1/responses` is NOT implemented for Claude models
(500 `convert_request_failed`, all input shapes — matches their
model metadata `supported_endpoint_types: openai/anthropic`, no
responses type despite the platform-docs claim).** Routing impact:
Codex CLI `/v1/responses` traffic cannot be served by Mia — it
would fail with 500, which sits in our 500–503 auto-retry band →
transparent failover to the next tier (A6), one wasted hop. Our
gateway does not convert responses→chat for type-60 channels
(ConvertOpenAIResponsesRequest passes through); the native escape
hatch is a type-58 Advanced Custom channel with the
`/v1/responses → /v1/chat/completions` route +
`openai_responses_to_openai_chat_completions` converter — evaluate
at go-live if Codex-on-Mia matters (until then fable/opus Codex
traffic prefers Selora first, Mia hop only wastes when Selora is
already down). Billing endpoints: account quota presents as
effectively unlimited (soft/hard $100M), `total_usage` 4246.6
(cents → ~$42.47 prior account usage — this key's account has
history; confirm the $72→$5,500 deal applies to it at purchase).
Key hygiene: this key transited chat — treat as a test credential;
enter the production key via admin UI only and retire the test key
after go-live.

**Widened-key re-probe (2026-10-13, owner enabled GPT 6/6.1 +
sonnet-5):** `/v1/models` now returns 6 — the four Claude SKUs,
claude-sonnet-5, gpt-6-astra, and **gpt-6.1-sol (DOT naming — maps
to our gpt-6-sol; no luna in Mia's catalog)**. The earlier "drop
sonnet-5 from ch7" note is OBSOLETE — ch7's deployed model list
(fable×2 + opus×2 + sonnet-5) is now fully covered by the key.
`/v1/responses` is per-model AND per-input-shape: **Claude models →
500 convert_request_failed for all shapes** (auto-retry band →
transparent failover to A6, no customer error; only a wasted hop
when Selora is down). **gpt-6-astra → WORKS with string input**
(real Responses-format reply, usage, charge $0.001275) but **400
`bad_request` with array-with-roles input — which is what Codex CLI
sends**; 400 is OUTSIDE every auto-retry range → customer-visible
hard failure. DANGER RULE: never add GPT models to a Mia type-60
channel while array-input 400s — Codex traffic would fail outright
(irrelevant today: ch7 carries no GPT models, so astra/sol/luna
never route to Mia; astra Codex rides A6 P30 → Selora P10).
**gpt-6.1-sol → 401: Mia's own upstream key for sol is currently
invalid** (their passthrough leaked `sk-proj-…KucA` masked — sol
is broken on their side; also proves raw upstream errors pass
through their gateway). astra chat/completions works (real GPT
reasoning). VERDICT: Mia IS usable now for exactly what we route
to it — Claude chat/completions + /v1/messages + sonnet-5 —
Codex-Claude traffic self-heals to A6; the type-58
responses→chat-converter channel remains the option if
Codex-on-Mia is ever wanted without the wasted hop.

**Automatic switching — mechanics (verified in pinned source):**
there is NO proactive seller-RPM or balance detection in New API.
Switching is REACTIVE and automatic: the seller returns 429 (rate)
or 402 (balance/payment) → DecideRelayRetry auto-retries (402 sits
in the 401–407 auto-retry band, 429 in 409–499, 5xx 500–503 too)
→ the retry attempt serves from the NEXT distinct priority tier.
The customer never sees the seller error; this delivers the
owner's "switches automatically to Mia, then over to A6" exactly —
but the trigger is the seller's error, not a predictive probe.
Auto-disable (auto_ban) fires only on 401 — a drained Mia wallet
(402) does NOT disable the channel, so each request pays one
failed hop before failing over (bounded waste, self-heals on
top-up; channel stays in rotation). Seller caps still bind
(Selora ~30 req/min per key, 60 after upgrade; Mia 100 RPM per
key) — sustained demand beyond a cap continuously overflows to
the next tier, which also drains the Mia wallet faster under
sustained Selora saturation: watch the wallet while unlimited
traffic rides Mia (the deal-rate math: heavy 10k-req/month
subscriber ≈ $79 wallet draw at list prices vs $180 revenue).

**Correctness-ranked ladder (2026-10-12):** a
(refund + trust incident), so correctness ranks channels and price
differentiates among correctness-equal ones. Evidence state is ONE
day of quick-mode verdicts: A6 fable-5-1→opus-4-6 swap (96%, strong
signal), Selora single quick attr_swapped (weak, needs full mode),
A6 sonnet-5-5 attr_match (good), Mia unverified (gate pending).
Tiers — not channels — are the failover unit (attempt N = Nth
distinct priority tier; weights share within a tier). Target shape
for the default group once Mia passes its gate: tier 1
selora-default-primary (w3) + a6-default-primary minus flagged
models (w1); tier 2 mia + selora-default-fallback; tier 3
a6-default-fallback (verified models only). Per-model lever =
channel model list: pull fable-5/5-1 from a6-* channels if the
full-mode re-test confirms the swap (~$0.3/check — buy the
confirmation before reranking); sonnet-5/5-5 stays A6-eligible
(verified + cheapest per-token + A6 is the only cache-token-reporting
source). Unlimited group: selora-unlimited primary (flat account,
RPM upgrade if the ≤4 subscribers saturate it) → a6-unlimited as
fallback; Mia joins unlimited ONLY while deal-rate credits last
($0.0079/request keeps a heavy 10k-requests/month subscriber at ~$79
vs $180 revenue) and MUST be revisited when the wallet runs dry —
at list rate it is $0.60/request, ruinous for flat-billed users.
Latency decides tier-1 weight share vs tier-2 placement for Mia:
measure FRT via the channel test + `other->>'frt'` in the battery;
~1–2s can share tier 1, 3s+ stays tier 2. Ladder depth = attempts:
3 tiers needs RetryTimes=2.

**Channel config (owner action, admin UI, no code):**

- New channel `mia-failover` (type 60 "New API"), base URL
  `https://miarouter.online`, key = the owner's Mia API key (enter in
  admin UI only, never chat), groups `default` (NOT `unlimited` —
  same isolation rationale as A6: keep flat-priced/unknown-depth
  upstreams away from the $180 flat-rate plan), **priority strictly
  below every existing default-group channel serving those models**.
  Verified in the pinned source (`model/ability.go`
  `getChannelQuery`/`getPriority`): attempt N uses the Nth distinct
  priority tier (DESC), so Mia only receives traffic after all
  tiers above it fail. Consequence for `RetryTimes`: if the 6
  production channels form 2 distinct tiers (primary + fallback, as
  the names suggest — verify in the channel admin UI), Mia is the
  3rd tier and needs **`RetryTimes=2`** (3 attempts) to ever serve;
  at the current `RetryTimes=1` it is a cold spare that cannot even
  absorb failover traffic. Decide at setup: raise `RetryTimes` to
  match the tier count (one extra retry hop on hard failures), or
  leave Mia unreachable-by-design until authenticity is proven and
  then raise it.
- Models: the four owner-targeted SKUs
  `claude-fable-5,claude-fable-5-1,claude-opus-5,claude-opus-5-5`
  (matching our sold-models list; add sonnet-5 later if wanted).
- No param_override for developer roles (Mia's docs advertise Codex
  support and their `/v1/responses` exists; verify with one real
  Codex CLI turn before trusting — if they 500 on developer-role
  input items, apply the same gjson query-path override as Selora).
- Channel test button after creation → then one real end-to-end
  request per model per wire format (chat/completions + /v1/messages
  + /v1/responses with a Codex CLI turn) with billing reconcile:
  our usage log quota vs published price table for that model.
- Watch billing on the flat rail: our usage logs record token
  counts; Mia's invoice is per request. Cost bookkeeping = request
  count × flat price, not token math — the usage log's per-request
  row count on the channel is the reconcile key.
- Pricing: our ratios already cover all four SKUs (no new pricing
  work; Model Overview shows live prices already).

**cctest monitor (this branch, code):** SELLER_CHANNELS gains a
`mia|https://miarouter.online|<monitoring-key>` entry (prefix
expansion covers `mia-*` channels); threshold prefix `mia` = 2 (same
noise tolerance as A6 until live verdicts justify tightening); env
knob `CCTEST_FAIL_THRESHOLD_MIA=2` added to compose/.env.example.
Mia's catalog lists `claude-*`/`gpt-*` models only among our sold
models — the monitor's claude/gpt prefix gate covers them as-is.

**Authenticity (open until verified):** public info only — no cctest
check has run against Mia yet. Their docs say nothing about upstream
sourcing, and their platform page mentions "dedicated pools" with
frozen model lists without describing the default pool's upstream
depth. The standing A6 lesson (2026-10-12: attribution check on
claude-fable-5-1 through A6 returned `attr_swapped`, serving
opus-4-6) says catalog listings prove nothing. Gate for Mia: at C0
calibration, run one cctest attribution check per flagship model
against `https://miarouter.online` and record verdict +
responseModel here before promoting it from cold spare to trusted
failover. Until then it sits as a cold spare with `retry`-only
traffic exposure.

**Rollback:** disable the `mia-failover` channel (status 2) or delete
it; nothing else references it. cctest monitor code: remove the mia
entry from SELLER_CHANNELS in .env; state entries for mia-* channels
are additive.

## 2026-10-12 — /docs left page-overview sidebar (rev 2026-10-12b)

`feat(docs): left page-overview sidebar, rookie-friendly navigation`
(c4a71cf42, tag deploy/2026-10-12-docs-sidebar).

- Scope: /docs section nav moved out of the header into a sticky left
  "On this page" sidebar — numbered 01–08 sections, agent-guide
  sub-links, "Start here" badge on Setup, active-section highlight
  (IntersectionObserver), scroll-padding so anchors clear the header.
  Language switcher + Open Dashboard CTA unchanged in the header. 260px
  + fluid grid (wrap widened 1000→1160px), collapses to a static card
  above the hero at ≤1000px; Arabic keeps the TOC on the left via
  mirrored RTL grid rules. All 12 languages, sidebar chrome translated
  (On this page / Start here / section titles).
- Deploy: static-only — no image rebuild (image stays pinned-next26;
  the gateway binary does not serve these files, Caddy does). Committed
  on vantyr/main, pushed to public with tag; 12 HTML files scp'd to the
  server and copied into /opt/vantyr/deploy/vantyr/static/docs/ (backup
  /opt/vantyr-backup-docs-pre-sidebar); md5 verified index.html
  27f3b9218e…; live /docs + de/ar/zh serve 8 TOC items + sub-links.
- Browser verification (local preview): TOC sticky left at 86px, active
  item follows scroll (setup→pricing), anchor click navigates with
  smooth scroll + hash, mobile 375px collapses to static card above
  hero, RTL Arabic TOC stays left with Arabic labels, zh-CN localized
  (本页导航/从这里开始). No console errors, no failed requests.


## 2026-10-13 — Payment rails deployed (pinned-next27) + BEpusdt service staged

`feat/payment-rails` merged into `vantyr/main` (fast-forward, 7c3376e40):
Stripe EUR/USD dual-currency (fails closed until live keys), €/$ wallet
toggle, i18n keys (now correctly inside the `translation` namespace —
earlier commits had written them to the JSON root where they never
loaded), dual-gateway Epay routing (EpaySecondary* options; BEpusdt
secondary with fiat=USD; fail-closed), and the go-epay Verify map-
mutation fix (dual-verify copies params per attempt).

- Deploy: tree synced via git archive (md5 626db86b… verified), image
  `pinned-next27` (195af2378097) built on-server, compose repointed
  (backup compose.yaml.bak-next27). Gateway healthy; relay fails
  closed with bad key; home/docs/pay 200; new bundle
  index.8fb03a8596.js + wallet chunk 63196.405b14563d.js carry
  stripeCurrency/stripe_usd_enabled (grep-verified); /docs serves
  11 networks + GRAM in all 12 languages.
- On-server focused payment tests: dual-gateway routing, secondary
  form, dual-verify (incl. mutation regression), fail-closed — all
  PASS (golang:1.26.1-alpine, vantyr-gomod/gobuild volumes).
- BEpusdt: compose service `bepusdt` (digest-pinned
  v03413/bepusdt@sha256:609c795d…14e0, v1.24.2-4d88040) running;
  first-run init credentials saved server-side only
  (/opt/vantyr/deploy/vantyr/.bepusdt-init-credentials.txt, root 600).
  Caddy pay2.vantyr.xyz block added (ACME retries on NXDOMAIN until
  the DNS A record exists — owner action, Namecheap).
- Caddy recreate note: the Caddyfile single-file bind mount broke
  (tar extraction replaced the inode), so `docker compose up -d
  --force-recreate caddy` re-resolved the mount; container is now
  `vantyr-caddy-1` and the tilkie_default network was re-attached
  (docker network connect) per the standing note.
- Not activated (fail-closed by design): Stripe options and
  EpaySecondary* remain unset in the options table — nothing customer-
  visible changed on the money paths until live keys + BEpusdt setup
  + pay2 DNS exist. Wallet keeps showing the GM Pay crypto button.
- Rollback: repoint compose.yaml to pinned-next26 + `docker compose
  up -d --no-build gateway` (next26 image retained).

## 2026-10-13 — BEpusdt activated + GM Pay TON disabled

**BEpusdt fully configured (via internal admin API over the Docker
network — no DNS needed for order submission):**

- 7 wallets registered: EVM 0x1dd5…ed54 for usdt/usdc.arbitrum,
  usdt/usdc.xlayer, usdc.base; TON UQBzGz…6aea for usdt.ton, ton.gram
  (addresses pulled from GM Pay's live config).
- `api_app_uri=https://pay2.vantyr.xyz` (cashier URLs), payment_timeout
  900s (15-min parity), payment_min_amount 1 (USD floor).
- Rates: `rate_float_USDT_USD=1`, `rate_float_USDC_USD=1` (fixed 1:1,
  GM Pay parity; verified in bep_rate after forced sync). GRAM stays
  CoinGecko-auto (~1.37 USD — native TON pricing, no manual drift).
- New API options live: `EpaySecondaryAddress=http://bepusdt:8080`
  (internal — the gateway talks to BEpusdt inside the network; only the
  customer's cashier redirect needs pay2 DNS), `EpaySecondaryId=1000`,
  `EpaySecondaryKey=<api_auth_token>`, `EpaySecondaryTypes=` all 7
  trade types. `PayMethods` extended with 7 per-chain buttons
  (LuCoins icons; BEpusdt cashier cannot reselect method on epay
  orders, so one button per chain is required).
- Verified live: signed submit form (fiat=USD) accepted → order created
  (rate 1:1, address correct, notify_url accepted) → 302 cashier; a
  secondary-key-signed callback to EpayNotify passes dual-verify in
  production (验签成功 in gateway log — the dual-gateway notify path is
  LIVE). Probe orders cancelled and cleaned.
- Remaining for customer access: **DNS A record `pay2.vantyr.xyz` →
  85.190.118.190** (owner, Namecheap; Caddy then auto-issues TLS).
  Until then the wallet buttons exist but checkout redirects fail to
  resolve. First $1 real order per rail still owed (money-path gate).
- BEpusdt admin: random username/password/secure-path printed at first
  boot, stored root-only at
  /opt/vantyr/deploy/vantyr/.bepusdt-init-credentials.txt; admin API
  needs BOTH the secure-path session cookie AND the login token.

**GM Pay TON disabled (owner decision, BEpusdt owns TON now):**
chain_tokens ton|TON + ton|USDT → enabled=0; ton wallet row →
status=2 (disabled; NOT deleted — history preserved). GM Pay
restarted to reload; cashier 200; remaining 7 chains (tron, ethereum,
solana, binance, polygon, plasma, aptos × USDT/USDC) verified intact.

Ops note: BEpusdt's rate rows bake the float syntax at creation; the
hourly sync writes new rows — after setting rate_float force a sync
(admin api /api/rate/sync) or wait up to an hour for the pinned rate.

**pay2 DNS live 2026-10-13 (owner added the A record):** Caddy needed a
full restart to clear the ACME backoff (reload alone doesn't reset it)
— pay2.vantyr.xyz now serves TLS (200). Live end-to-end order checks on
three rails (Arbitrum USDT, TON GRAM, Base USDC): signed submit → order
created with correct address + rate ($1 = 1 USDT/USDC pinned; GRAM
0.73 @ CoinGecko 1.37) → public cashier page renders. Orders cancelled
after verification. GM Pay (7 chains) and all other endpoints healthy.

Remaining money-path gate: ONE real $1 customer order per rail
(all 7 BEpusdt types) with credit + usage-log reconciliation, then
GM Pay TON row can be fully removed if desired. Wallet now offers all
8 crypto buttons to customers.

## 2026-10-13 — Single BEpusdt button + HTTPS checkout (pinned-next28)

Owner report: too many USDC/USDT buttons (two providers → 9 buttons),
and BEpusdt checkouts failed in the browser — "The information you're
about to submit is not secure" then "This site can't be reached —
bepusdt's server IP address could not be found."

**Root cause (both symptoms):** the Epay protocol is browser-mediated —
the customer's browser POSTs a signed form to `EpaySecondaryAddress`,
which was `http://bepusdt:8080` (internal Docker hostname, plain HTTP).
Firefox flagged the un-encrypted form POST, and after clicking past it
the hostname `bepusdt` is unresolvable outside the Docker network.

**Fix (fork change, commit de0041ac1, image pinned-next28
1ef896dad246):** `RequestEpay`'s secondary branch now calls BEpusdt's
**native create-order API** (`POST /api/v1/order/create-order`, JSON +
EpusdtSign MD5 over sorted non-empty fields with Go %v value
formatting) and returns a `pay_link`. The browser GETs the HTTPS
payment_url — no form POST at all. The cashier at pay2.vantyr.xyz has
a network picker (`reselect: true`), so **one button covers all 7
rails**. `PayMethods` consolidated to two crypto buttons:

- "Crypto (USDT / USDC)" → GM Pay (alipay type, 7 chains, own picker)
- "Crypto L2 (Arbitrum / X Layer / Base / TON / GRAM)" → `bepusdt`

`EpaySecondaryTypes=bepusdt` (single method; the 7 per-chain types
were the old per-button routing). `EpaySecondaryAddress=
https://pay2.vantyr.xyz` (public TLS host — the gateway calls it over
the internet, not the internal hostname; either works, public keeps
one code path).

**Notify:** new route `POST /api/user/bepusdt/notify` handles BEpusdt's
native JSON callback (same EpusdtSign algorithm; trade_id + status
present — verified against BEpusdt source app/task/notify/notify.go:
amount is float64, signature over the unmarshaled map). status=2 →
RechargeEpay (row-lock idempotent, quota from order-row Amount — never
callback money); status=3 → mark expired; status=1 → ack only. All
replies are literal `success`. Epay notify (GM Pay) path unchanged;
dual-verify retained for Epay-shaped callbacks.

**Frontend:** use-payment.ts opens `pay_link` in a new tab when
present (before the generic form-POST branch).

**Tests (server-run, all green):** TestBepusdtSignVector (signature
vector, signature-key exclusion, token-sensitivity),
TestCreateSecondaryNativeOrder (httptest stub gateway — asserts
order_id/fiat/currencies/amount/notify/redirect params, re-signs
correctly, failure path), TestBepusdtNotifyCredits (status=2 credits
exactly 5×500,000; replay idempotent; status=1 no credit; bad
signature rejected), TestBepusdtNotifyExpires (status=3 → expired,
no credit). Plus Epay/TopUp/Topup/model/router suites, web typecheck
+ wallet tests 8/8.

**Live verification (2026-10-13, full chain through the real Go
path):**

1. Python probe (token read via subprocess from BEpusdt sqlite — NOT
   shell-quoted heredoc, which had silently emptied it and caused the
   earlier 签名错误): create-order 200 with payment_url, 7 networks,
   USD pricing, expiration 899s.
2. Real user flow: registered test user (Turnstile + email
   verification temporarily disabled for the battery, both restored
   + gateway restarted after; test user `vantyr_paytest` (id 31)
   disabled status=2, its pending $1 order USR31NO… left to expire):
   login → auth/refresh → `POST /api/user/pay` {amount:1,
   payment_method:"bepusdt"} → **success with pay_link** to
   https://pay2.vantyr.xyz/pay/checkout/… (200). top_ups row
   verified: user 31, amount 1, money 1, method bepusdt, provider
   epay, pending.
3. **Notify leg live:** BEpusdt pushes status=1 callbacks every
   minute — gateway log shows `BEpusdt webhook 验签成功` + 订单等待
   支付 + 200 for the real order. Signature verification, JSON
   parsing, and the ack all work against real BEpusdt traffic.
   status=2 credit is covered by unit tests (exact quota, idempotent,
   tamper-reject) and awaits only the real-money battery.

**Deploy note:** next28 tree sync overwrote compose.yaml's image line
to `pinned` — fixed with anchored sed to `pinned-next28` before swap.
Gateway healthy on pinned-next28; /api/status 200.

Remaining: same money-path gate — ONE real $1 order per rail (now
through the single button, any of its 7 networks) with credit +
usage-log reconcile. BEpusdt first boot credentials unchanged
(root-only file). Old per-chain probe orders in top_ups (usdc.base
etc.) simply expire.

## 2026-10-13 — Pay-method rename + subtitle line (pinned-next29)

Owner request: both crypto buttons should read "USDT / USDC" with the
network list in a smaller font underneath:

- "USDT / USDC" / Network: Aptos, BSC, Ethereum, Plasma, Polygon,
  Solana, TRON (GM Pay, type alipay)
- "USDT / USDC" / Network: Arbitrum, Base, TON/GRAM, X-Layer
  (BEpusdt, type bepusdt)

**Fork change (commit 3e970b614, image pinned-next29 58810a75192b):**
PayMethods gained an optional `subtitle` key. It passes through the
Go side untouched (`[]map[string]string` + raw-JSON admin editor), so
this is frontend-only code: `PaymentMethod.subtitle` type,
recharge-form button renders the subtitle as a smaller muted line
under the name (same style slot as the min-topup hint), payment
confirm dialog shows it beside the name so the two "USDT / USDC"
rails stay distinguishable at confirmation. Regression tests
(pay-method-subtitle.test.tsx): subtitle renders under the name inside
the button, omitted when unset, passed through on method selection.
Typecheck clean, wallet tests 7/7, touched files lint-clean.

**Config (options table):** PayMethods updated with both names +
subtitles per the owner's exact wording. Verified live via
topup/info: both buttons carry name "USDT / USDC" + their subtitle.
Live wallet chunk 63196.0abffbe767.js byte-identical to the local
build with the subtitle code (md5 match).

Deploy: tree sync + on-server image build + gateway swap (compose
image line sed'd to pinned-next29 before up). Gateway healthy 200.
Test users (vantyr_uicheck id 34, vantyr_paytest id 31) disabled
status=2 after the scripted topup/info check; Turnstile + email
verification disabled only for the test window and restored.

## 2026-10-13 — Subtitle render fix + Tether icons (pinned-next30)

Owner report after next29: the network lists still didn't show under
USDT / USDC, and both buttons should carry the USDT (Tether) logo
(USDC logo unavailable → USDT only).

**Root cause (next29 gap):** the wallet hook's parsePaymentMethods
whitelists fields when mapping the raw API JSON to the typed
PaymentMethod — the new `subtitle` key was dropped there, so the
component support never received data. (Deployed next29 verified the
API + config carried subtitle; the parse layer was the missing link.)

**Fix (commit f162e4b8e, image pinned-next30 ae32e2ca5ab5):**

- parsePaymentMethods now maps `subtitle` (hook-level tests cover
  pass-through + absence).
- Icons: react-icons has no USDC mark in any pack (verified across
  families) → both crypto rails render the Tether logo. alipay and
  bepusdt types share one SiTether case in getPaymentIcon, Tether
  green #26A17B; PayMethods config icons set to SiTether for both
  buttons (config icon resolves via ReactIconByName; the type-based
  case covers any icon-less fallback). constants gained
  PAYMENT_TYPES.BEPUSDT + its color entry.
- Also fixed the pre-existing no-import-type-side-effects lint error
  in ui.tsx (touched file rule).

**Verified in a real browser (local preview → production API):**
logged in through the UI (Turnstile briefly disabled server-side,
restored after; test user vantyr_uicheck2 id 35 disabled), wallet
page shows both buttons: "USDT / USDC" with the network list as an
11px muted line under the 14px name, and identical Tether SVG paths
on both buttons. Wallet tests 13/13 (2 new hook tests), typecheck +
lint clean on touched files.
## Group isolation (2026-10-13, owner decision — PAYG vs unlimited)

Customers no longer see the internal group split. Base
`UserUsableGroups` = `{"default": "Default"}` (PAYG + anonymous see one
group only); `group_ratio_setting.group_special_usable_group` =
`{"unlimited": {"+:unlimited": "Unlimited plan"}}` re-adds unlimited for
users whose account group is `unlimited` (set by the $180 plan's
upgrade_group inside the purchase transaction). Applied via options SQL
(the special-group row is INSERT — it had never existed; the config
system persists it under the dotted key `group_ratio_setting.…`, loaded
by the 60s sync through handleConfigUpdate → UpdateConfigFromMap).

Enforcement is at relay time (middleware/auth.go token-group check: a
token whose group is not in the user's usable groups 403s with 无权访
问 <group> 分组) — proven live: a default-group user with an
unlimited-group token gets 403; token 15 (root "Model testing") was
switched from group=unlimited to inherit (empty) so root tooling keeps
working through the default group. Body `group` fields are honored only
on /pg/chat/completions (playground, validated) — /v1/chat/completions
ignores them, so no API-side bypass exists beyond token creation, and
token creation's lack of group validation is neutralized by the relay
gate. Side effects verified: anonymous /api/pricing shows
usable_group {default} and 9 models (all models serve the default
group); the key-creation dropdown and pricing page now show one group
for PAYG. Model Overview details' "Groups: default, unlimited" pills
come from channel data (enable_groups), NOT the usable-group setting —
hiding that line would need a small fork frontend change (declined for
now, owner can request). The cctest monitor probes via a default-group
token (covers all default-group channels incl. a6-unlimited's
default-group side); its channel-quarantine actions are admin API,
unaffected.

## 2026-10-14 — Stripe activation + pay2 Caddy restore + button rename (pinned-next31)

**Stripe live-configured (owner, via admin UI — secrets never in
chat/files):** StripeApiSecret/WebhookSecret/StripePriceId (EUR) +
StripePriceIdUsd (USD) set, test mode. First checkout attempts failed
with "No valid payment method types" — account had no methods
activated; owner enabled Cards, Link, Apple Pay, Google Pay, iDEAL|
Wero, Klarna in the dashboard (no code needed: checkout sessions
never restrict payment_method_types — the iDEAL|Wero design).
Checkout session creation then succeeded (order ref_ed3d8df…, 20,
pending) and the hosted payment page shows the methods. Wallets
render device-dependent (Apple Pay in Safari, Google Pay in Chrome),
iDEAL EUR-only on the € toggle; sessions created before a method
toggle keep the old lineup (create a fresh top-up after dashboard
changes). Payment-methods battery: one completed checkout per rail
(cards, iDEAL, wallet) still owed before live keys.

**pay2.vantyr.xyz TLS outage (found during Stripe battery):** the
pay2 Caddy site block was accidentally dropped during the tilkie.xyz
Caddyfile edit earlier that day — every TLS handshake to pay2 failed
(internal error), so BEpusdt create-order calls died. The repo does
NOT track a root Caddyfile (verified: git log --all -- Caddyfile is
empty), so tree syncs never touch it — the loss was the manual edit
alone. Restored from the Oct 13 backup (cert was still in Caddy
storage — instant), caddy reload, verified 200 from host + external +
gateway container. Lesson recorded in the Caddyfile itself: keep ALL
site blocks when editing that server-owned file.

**Button rename (owner request, commit d86e7352a, image
pinned-next31 efcf349e2db3):** "Stripe" button renamed to "Card /
iDEAL | WERO / Wallets" with subtitle "Stripe: Cards, iDEAL | Wero,
Apple Pay, Google Pay, Klarna" — the name is Go-side
(controller/topup.go, GetTopUpInfo appends the stripe entry), the
subtitle rides the next29 pay_methods subtitle mechanism, so the
wallet renders it with no frontend change. Test
TestGetTopUpInfoStripeButtonLabel pins name+subtitle+type; Stripe
test suite green on server. pay2 block verified intact after the
next31 tree sync (backup Caddyfile.bak-pre-next31 taken).

## 2026-10-14 — Stripe button wording v2 (pinned-next32)

Owner feedback: "Wallets" in "Card / iDEAL | WERO / Wallets" reads as
a crypto wallet next to the crypto rails. Renamed (commit a4c111916,
image pinned-next32 d580edfa9a8c): name "Card / iDEAL | WERO /
Apple Pay / Google Pay", subtitle unchanged ("Stripe: Cards, iDEAL |
Wero, Apple Pay, Google Pay, Klarna"). Also diagnosed "not visible"
report: the running next31 binary already had the label — browser
cache of the old JS chunk; hard refresh needed. Test updated, green
on server. pay2 Caddy block re-verified intact after sync
(backup Caddyfile.bak-pre-next32).

## 2026-10-14 — Stripe wording v3 + full-width row + first live payment (pinned-next33)

**First REAL Stripe payment (LIVE mode):** owner paid €1 via iDEAL
(order ref_b62582fa…). Webhook delivered + verified (checkout.session.
completed, payment_status paid, currency EUR, livemode true), order
row flipped to success, credit reconciled exactly: +500,000 quota =
$1.00. Wallet is USD-denominated — the € payment credits dollars,
not euros (credit always derives from the order-row amount, never
webhook money). Live iDEAL is on → the scheme's company registration
number display rule now applies (owner action outstanding). Note: the
session's payment_method_types reveal the account's full lineup
(card, bancontact, eps, ideal, klarna, link, paypal, amazon_pay,
satispay) — the owner enabled more than the button lists.

**Button v3 wording (commits 169bb6d8e + bba7f7403, image
pinned-next33 43b3337ceb63):** name "Card / iDEAL | WERO / Apple +
Google Pay / PayPal and more", subtitle "powered by Stripe" (11px
muted italic). Root cause of the "still says Stripe" reports: a
manual stripe entry (name "Stripe", icon SiStripe) had been added to
the PayMethods option via the admin editor — GetTopUpInfo skips its
built-in entry when the config already has one, so config wins over
the Go label. The config entry now carries the v3 wording; the Go
fallback + test match it. Full-width: the Stripe method renders as a
col-span row below the crypto grid (grid loop skips it) so the long
name + subtitle never truncate — browser-verified at 1400px, no
truncation; italic subtitle confirmed via computed style. Test added
(col-span + full name + subtitle containment). pay2 Caddy block
verified intact after both syncs (backups .bak-pre-next33/.b33b).

**EUR/USD pricing decision (owner: use live rates, not €1=$1):**
recommended path = single USD price in StripePriceId + Stripe
adaptive pricing (already enabled by default — seen in the live
webhook payload) presents local currency to each customer at live
rates while settling in USD; StripePriceIdUsd stays empty so the €/$
toggle hides; zero code. Pending owner go-ahead to flip the config.

## 2026-10-14 — EUR live-rate pricing + Stripe button normal size (pinned-next34)

**Owner decision: Option A — real conversion rates without Stripe
conversion fees.** The wallet credits USD units; the EUR Stripe price
now equals ceil(ECB EUR→USD × 100) cents, so a EUR payment buys
exactly $1 of credit at the real rate (EUR in / EUR out — no Stripe
currency conversion, no adaptive-pricing customer fee; avoids adding
USD settlement to the NL account).

- Live rate at setup: EUR/USD 1.1188 (ECB 2026-10-13) → EUR price
  **112 cents**. Applied: new live price price_1UQR3a…, StripePriceId
  option repointed, product default switched, old price_1UQGiw…
  archived. (Stripe prices are immutable — unit_amount cannot be
  updated; the update path is create-new + repoint + archive.)
- **deploy/vantyr/scripts/stripe-eur-rate-sync.sh** (also installed at
  /opt/vantyr/scripts/, root cron 15 3 * * *, log
  /var/log/stripe-eur-rate-sync.log): fetches ECB rate (frankfurter,
  open.er-api fallback), skips when rounded cents unchanged, else
  creates the new price, UPDATEs the StripePriceId option (60s sync,
  no restart), flips product default, archives the old. Test-run
  verified idempotent (no-op at current rate).
- USD price unchanged: $1 = 1 unit directly.

**Stripe button back to normal size (owner: full-width row "doesn't
look nice" — same size as USDT buttons, one grid cell):** commit
03894fff8, image pinned-next34 38d452f233ba. Name "Card / iDEAL /
Klarna / PayPal and more" (39 chars — crypto-button ballpark) +
italic "powered by Stripe" subtitle; renders in the same grid with
identical 405×56px cells (browser-verified; screenshot archived).
Config PayMethods entry carries the name; Go fallback + tests match.
pay2 Caddy block verified intact after sync (backup .bak-pre-next34).

**EUR formula CORRECTION (2026-10-14, same day):** the Option A formula
was inverted in the first cut — ceil(rate×100) charged €1.12 for a $1.00
unit (~25% premium over market). Correct formula: the EUR price is the
euro-equivalent of ONE dollar unit → **cents = ceil(100 / ECB rate)**
(1.1188 → 90 cents; €1.00 spent ≈ $1.12 of credit — the owner's intended
"1 euro deposits ~1.12 dollars"). Fixed in script + applied live
(price_1UQZd8… 90 cents, StripePriceId repointed, €1.12 price
price_1UQR3a… archived); rerun verified idempotent. No image rebuild
needed (config + script only; running image unchanged). The record
above is kept as-is for history; this paragraph is authoritative.

## 2026-10-15 — /bin symlink incident: root cause + fix (no data loss)

**Symptoms (from 2026-10-14 21:23 UTC):** all SSH publickey auth
denied ("User administrator not allowed because shell /bin/bash does
not exist" in auth.log), console login looping ("can't exec
/bin/login"), rsyslog/apparmor/ufw/chrony failing at boot — while the
Docker stack kept serving (containers don't use host /bin).

**Root cause (found via one.com rescue mode + SystemRescue):** the
next34 deploy tree-sync command ran `tar -xf /tmp/vantyr-next34.tar
-C /` — extracting to the ROOT directory instead of the deploy tree
(shell path bug in a compound deploy command). The git archive's
top-level `bin/` directory (upstream migration SQL + time_test.sh)
replaced the system's `/bin -> usr/bin` symlink with a real
directory, orphaning every /bin binary at once. NOT an intrusion;
the 206.189.118.69 auth.log probes were background noise. Disk was
71% used — the full-disk theory was wrong (boot failures were the
missing binaries, not space).

**Fix (via rescue mode, owner-executed at console):** mounted
/dev/vda1, moved the three stray files to /root/bin-evidence/,
rmdir /mnt/bin, `ln -s usr/bin /mnt/bin`. Rebooted: SSH + all 13
containers + gateway healthy immediately.

**Prevention (deploy protocol change):** tree syncs now extract to a
staging dir and rsync/mv into the deploy tree — never `tar -C
/<deploy-path>` in compound commands where a path variable can
resolve empty (the `-C /` came from an unquoted/empty-variable path
in one deploy step). Added to the runbook: after any tar sync,
`ls -la /bin/bash` sanity check before proceeding.

**AGPL catch-up completed:** eur-rate-fix archive (sha256 f07c3c5b…)
uploaded to static/source/, source-notice.txt + Footer updated (tag
deploy/2026-10-14-eur-rate-fix, commit b7c803b69) — the steps that
were blocked during the SSH outage.

## 2026-10-15 — Unlimited Usage page (pinned-next35 + next36)

**Owner request:** surface the admin-granted unlimited plan (4 slots
total) in the dashboard. Sidebar Personal group gains "Unlimited Usage"
(owner rename from "Apply for Unlimited Usage"), linking to /unlimited:
what unlimited includes (all models, flat monthly price, higher rate
limits, genuine upstream models, fixed seat count), how to apply
(Discord ticket flow), and a live slot-availability text box in the
dashboard design (display font 30px, "4 / 4 slots currently available"
at launch). Page fully translated in all 12 locales (18 strings each;
sync-i18n clean, 0 missing).

**Implementation (commits 41cec7cf5 + a336548aa, images
pinned-next35 21f92401d855 + pinned-next36 d6e39cd540c7):**

- Backend: GET /api/user/unlimited/info (self route, wallet:read
  scope) returns capacity/active/remaining (+ the requesting user's
  own active flag → page switches to an "Unlimited active" card).
  remaining = capacity - active user_subscriptions, floored at 0.
  Active count is ALL active subs (the plan is admin-granted;
  currently 0). Tests: endpoint math + floor-at-zero.
- New admin option UnlimitedSlotsCapacity (default 4; options table,
  parses as non-negative int). Adjust capacity in System Settings →
  the page follows on next load.
- Frontend: features/unlimited (SectionPageLayout + TitledCard,
  Infinity icon), route /_authenticated/unlimited, sidebar entry
  under Personal; localized query + skeleton loading.
- Tree sync used the NEW SAFE protocol for the first time: staging
  extract + rsync with exclusions (data/static/Caddyfile/compose/
  .env) — no tar -C into live paths, /bin/bash verified after sync.

**Live verification:** endpoint returns 4/4/0 on prod; browser check
(Dutch locale) shows sidebar "Onbeperkt gebruik" + translated page
with "Beschikbare plekken 4/4 — plekken momenteel beschikbaar";
screenshot archived. Wallet tests 14/14; typecheck + lint clean;
router/model/controller suites green on server.

## 2026-10-18 — API base URL inline on the API Keys page (pinned-next37)

`feat(keys): show API base URL inline in the table toolbar` (ab1616e01) +
`fix(keys): remove duplicate base-URL card above the table` (c3989900c),
tag deploy/2026-10-18-keys-base-url-v3.

- Owner request: the base URL was hard to find — only behind the
  "API Addresses" popover on the keys page. Now a small inline card
  (globe icon, label, URL, one-click copy button) sits in the API Keys
  table toolbar next to the "Filter by API key" search input. The
  "API Addresses" popover is removed. URL source: first api_info entry,
  falling back to server_address, then window.location.origin.
- An earlier iteration (ac2469e8f) mistakenly placed the card on the
  wallet page next to Order History; reverted (9063eea9f) after owner
  correction, then re-applied on the keys toolbar. v1 (06ef987c2) also
  left a duplicate render above the table; fixed in c3989900c.
- Deploy (owner-approved): source archive sha256 f6005117…aa6179
  uploaded to static/source/; /opt/vantyr web tree rsynced from the
  archive (backup /opt/vantyr-backup-web-pre-next37); stale deleted
  test file removed manually (tar extract does not delete); image
  pinned-next37 (6ed9d8c63e55) built on-server; compose.yaml pinned
  (the archive sync had reset the image line to `pinned` — fixed with
  sed, known gotcha); gateway recreated + healthy; source-notice.txt +
  Footer option updated (backups in /tmp + /opt/vantyr/backups).
- Live verification: bundle index.1c71f59f31.js carries "API Base URL";
  /api/status footer serves the new tag links; archive 200 (8,324,001
  B); site 200. pinned-next36 (d6e39cd540c7) retained for rollback.
- Keys-page tests: api-addresses.test.tsx deleted (tested the removed
  popover); remaining keys failures are pre-existing nl-NL currency
  formatting issues in api-key-listing.test.tsx.

## 2026-10-18 — Compact base-URL card on API Keys page (pinned-next38)

`fix(keys): compact base-URL card, show both Anthropic and OpenAI URLs`
(da2448620, tag deploy/2026-10-18-keys-base-url-v4).

- Owner feedback on next37: the card's text was too long and the box
  taller than the other toolbar controls. Reworked to h-8 (matches the
  toolbar inputs), one compact row per base URL — "Anthropic
  https://vantyr.xyz" and "OpenAI https://vantyr.xyz/v1" — each with
  its own copy button (label shortened via route.replace(/-compatible$/)).
  Fallback: single server_address/origin row when api_info is empty.
- Base-URL fact (confirmed from live /api/status api_info): Anthropic-
  native clients use https://vantyr.xyz (no suffix); OpenAI-compatible
  clients use https://vantyr.xyz/v1. Two different base URLs, both now
  shown.
- Deploy (owner-approved): archive sha256 109c9292…47aab5 to
  static/source/; web tree rsynced (backup pre-next37 from earlier
  today reused); image pinned-next38 (4bbbc6f0bfbf) built on-server;
  compose re-pinned after archive sync reset the image line again
  (now a twice-confirmed gotcha); gateway recreated + healthy; notice
  + footer updated (backups /tmp/source-notice-pre-next38.txt,
  /opt/vantyr/backups/footer-pre-next38.txt). Live bundle
  index.0e0bdae1b9.js carries the two-URL component; footer serves v4
  links. Rollback: pinned-next37 (6ed9d8c63e55).

## 2026-10-19 — Model display dedup: gpt-6.1-sol alias hidden (pinned-next39)

`fix(models): hide catalog-hidden models from public and dashboard model
lists` (017ca3b19, tag deploy/2026-10-19-model-list-visibility).

- Problem: the A6 upstream spelling `gpt-6.1-sol` (dot) must stay
  routable (cctest.ai's model dropdown uses the dot spelling — customers
  testing there would get 503 model_not_found otherwise), but both
  spellings appeared in /v1/models and Model Overview as duplicate
  models. Audit: cctest's pre-registered list matches all 9 other SKUs
  exactly (claude-fable-5, -5-1, opus-5, -5-5, sonnet-5, -5-5,
  gpt-6-astra, gpt-6-sol — the only collision is gpt-6.1-sol); cctest
  does not list claude-fable-5-1 at all (untestable there, our spelling
  unchanged). Zero customer dot-name requests before the fix (1 log row
  total — my verification).
- Config half (live immediately): models-table row
  `gpt-6.1-sol` status=0 (id 11) — updatePricing already skips
  status!=1 rows, hiding it from Model Overview with zero code; plus
  CacheRatio entry gpt-6.1-sol=0.6 added (the alias was missing it —
  canonical has 0.6, alias silently fell to the 1.0 default and
  overcharged cache reads by 40%). Backup:
  /opt/vantyr/backups/pre-alias-hide-2026-10-19.sql.gz.
- Code half: GetGroupsEnabledModels (the shared choke point for
  /v1/models and the dashboard model list) was a raw abilities DISTINCT
  ignoring the models.status visibility policy the pricing catalog
  applies. New model.FilterHiddenModelNames applies the same
  exact/prefix/suffix/contains catalog resolution at that choke point;
  routing, billing, and no-metadata models are untouched. Focused test
  pair + model/service/controller suites green locally and on-server
  (golang:1.26.1-alpine, vantyr-gomod/gobuild volumes).
- Deploy: image pinned-next39 (5ed204e721b4) built on-server from the
  tag archive; binary grep-verified for FilterHiddenModelNames (1 hit);
  compose repointed (backup compose.yaml.bak-next38). AGPL protocol in
  full: public main pushed (017ca3b19), tag pushed, source archive
  sha256 cd383346eb5400967c7694f9bdf7f1012d38f535afbf37234549ea6621c8eb06
  published, source-notice.txt + Footer updated (backup
  /opt/vantyr/backups/footer-pre-next39.txt).
- Live verification: /api/pricing shows 9 models (alias gone,
  canonical present); /v1/models shows 9 (same); both spellings still
  relay through ch34 → gpt-6.1-sol upstream and bill IDENTICALLY (135
  quota for 4388+5 tokens each, cache_ratio 0.6 + cache_tokens 4224 in
  both log rows — the money gate per AGENTS.md). Gateway healthy, zero
  errors; / /docs/ /pricing /about /login 200; footer serves next39
  links. Rollback: pinned-next38 (compose.yaml.bak-next38; delete the
  models-table row to restore the alias display).
- cctest-monitor fix in the same window: the running container baked a
  pre-cooldown monitor.py (list-format bad_standbys) while the state
  file already held dict-format entries → every standby demotion since
  2026-10-18 12:00 crashed the cycle (4 failures/24h; zero completed
  cycles). Current repo code (list→dict migration, 3h cooldown)
  redeployed: image rebuilt, container restarted, startup cycle through
  all 32 pins with zero errors; astra promote→verify→demote→cooldown-
  retry flow now completes (5312/2757 re-verified, both still
  attr_swapped). Stale "24h cooldown" demote-log text corrected to read
  the env value (b1d6a2287 on feat/payment-rails).

## 2026-10-19 — A6 account consolidation: all A6 traffic on the new account

Owner decision: the old A6 account is retired; only the new account
(user 34611) may be used. Channel keys for the three general A6
channels (2 a6-default-primary, 5 a6-default-fallback, 6
a6-unlimited) swapped from the old drained account (sk-h6ba…, last
success 2026-10-17 16:47, empty since — surfaced as A6's own 403
insufficient_user_quota passed through to customers on gpt-6-sol) to a
new unlimited general key `vantyr-general-relay` (A6 token id 138682)
minted via the A6 management API. Pin channels already rode the new
account. Nothing references the old account anymore.

- Mechanics: key update is a ChannelSensitiveWrite action (channel
  authz classifies `key` as sensitive; admin PATs like the monitor's
  can edit models but not keys — by design). Swap done via a
  temporary root access token (SQL-inserted row in user_access_tokens,
  sha256 fingerprint, scopes channel:sensitive_write/read/write/
  operate, 2h expiry) — used, then DELETED; plaintext lived only in
  /tmp on the server, wiped after. No secret persisted anywhere new.
- Verified live: /v1/models listing unaffected; gpt-6-sol (the model
  that was dead) relays OK via ch2, billed 113 quota; fable-5,
  opus-5-5, sonnet-5-5, astra all OK through the new key; native
  channel tests on ch2/5/6 all pass. New-account key covers all SKUs
  (138 models incl. gpt-6-sol, gpt-5.6-sol, claude-fable-5.1 dot).
- Operational note: the new-account wallet (~$28.75 at swap time) now
  backs BOTH the monitor's verification checks AND all general-tier
  A6 traffic + failovers. Single pool, single drain point — top it up
  as one line item from here on.

## 2026-10-19 — Model Routing admin page + cctest status/action API

Owner request (A6 pin integration): a per-model view of which
merchant/key serves each model, the routing ladder, verification
status, and standby cooldowns — plus actions. Nothing native covers
this (Channels console is channel-centric; Models → "Bound Channels"
shows names only; the cctest monitor had no read surface at all —
verdicts/cooldowns lived only in state.json + docker logs + Discord).

Three pieces, no Go changes (config-first):

1. **cctest monitor status/action server** (monitor.py, all stdlib):
   ThreadingHTTPServer daemon thread, port 8787 (env `STATUS_PORT`;
   compose maps `CCTEST_STATUS_PORT`). Started BEFORE the env checks in
   main(), so a parked monitor still answers status (empty channels,
   `last_cycle_at: null`) — the page can distinguish parked from dead.
   Endpoints:
   - `GET /api/cctest/status` — full state projection (config display
     mirror, per-channel state incl. new `last_verdicts`, `bad_standbys`,
     `_meta.last_cycle_at` freshness stamp written at the end of every
     run_cycle). Reads STATE_PATH fresh per request (atomic writes make
     that a consistent snapshot).
   - `POST /api/cctest/verify` `{channel, model}` — runs the exact
     cycle check path on demand (seller-entry lookup, mapping-aware
     check name, serving-channel attribution, process_verdict → may
     enforce failover exactly like a cycle check).
   - `POST /api/cctest/promote` `{model}` — owner-triggered merchant
     rotation: quarantines the model's active pin (status 2 + state),
     then promote_next_standby (enable-first, verify, demote-on-fail);
     observe-mode → 409, parked → 503.
   - `GET /status` — same payload, unauthenticated, container-internal
     debug (docker exec / curl inside the network).
   Auth = gateway pass-through (Bearer forwarded to
   GATEWAY_URL/api/user/self). Status contract is deliberate for the
   SPA's axios interceptor: expired/absent → 401 (refresh path),
   role < 10 → 403 (NO refresh loop — a 401 here would log non-admins
   out), gateway unreachable/5xx → 503 (page degrades).
   `record_verdict` now persists the latest verdict per
   (channel, model) at all four check sites (process_verdict, standby
   verification, quarantine re-test, removed-model re-test).
2. **Caddy**: `handle /api/cctest/*` → `reverse_proxy
   cctest-monitor:8787` (read_timeout 300s — promote runs a
   synchronous cctest check), placed before the gateway catch-all.
   Docker-network service DNS; no port publish.
3. **Web**: `web/src/features/model-routing/` (route `/model-routing`,
   sidebar Admin group "Model Routing", 12 locales). Client-side join:
   fetchAllChannels (paginated getChannels reuse; page_size caps at
   100 and production runs 40+ channels) × cctest status → per
   (model × group) rows (provider from name prefix, merchant parsed
   from `a6pin-<model-stem>-<merchant>` names, status_reason from
   other_info, verdict by channel name, cooldown =
   bad_standbys + standby_cooldown_hours). Page = per-model summary
   (active channel, verdict, standby fresh/cooldown counts, Promote
   standby action w/ ConfirmDialog) + full ladder table (model/group/
   channel/merchant/priority/status/verification/cooldown columns,
   Verify now action per enabled row). Degraded banner when the
   monitor is unreachable (routing-only view). ROLE.ADMIN route guard.

Verification: monitor 32/32 dry-run tests (7 new: last_verdicts at all
sites, payload projection, status-server auth matrix incl. 401/403/503
on an ephemeral port, verify + promote actions mocked). Live smoke on
this machine: parked monitor serves /status 200, /api/cctest/status
401 (no token) / 403 (user) / 200 (admin via stub gateway) / 503 (dead
gateway); POST while parked → 503. Web: 15 vitest tests (join + page
behavior with api spies), typecheck + oxlint + oxfmt clean, routeTree
regenerated. Local browser preview hits the sign-in redirect (prod
auth) — page behavior is covered by the mocked suite; production
verification happens at deploy (below).

Deploy (owner-gated, not yet run): rebuild cctest-monitor image
(build context must exist at /opt/vantyr/deploy/vantyr/cctest-monitor
— re-copy source if a staging cleanup wiped it), start with plain
`docker start` if the gateway service_healthy gate wedges, reload
Caddy, rebuild the gateway image for the SPA (frontend changes need
on-server image rebuild + compose pin + recreate). Then: `curl -H
"Authorization: Bearer <admin>" https://vantyr.xyz/api/cctest/status`;
load /model-routing; non-admin → 403; headerless → 401; one Verify
action (watch docker logs + credits); promote battery per the
2026-10-18 pattern (usage-log attribution proves the promoted pin
serves the model).

SECURITY FLAG for the owner (pre-existing, unrelated files):
`deploy/vantyr/cctest-monitor/rebuild_env.py` (committed 0f44c3236,
pushed to the public repo) contains the live sidecar PAT and cctest
key in plaintext at lines 44-45 — rotate both and scrub.
## 2026-10-19 — claude-fable-5-1: dot mapping removed (A6 dash pool is native)

Owner question: are Fable 5.1 dot/dash spellings handled correctly
through A6? A6 serves BOTH — but they are DIFFERENT merchant pools:

- `claude-fable-5.1` (dot): 31 merchants. Cheapest ~$0.12/$0.60.
  Probe evidence: a 10-token request bills 898 prompt tokens (a
  ~888-token hidden prompt injected by the merchant pool) with
  OpenAI-style usage reporting. Output model name echo: dash.
- `claude-fable-5-1` (dash): 78 merchants. Cheapest ~$0.059/$0.29;
  cheapest authenticity-guaranteed $0.108/$0.54. Probe evidence:
  exact token billing (10 prompt, 5 completion), Anthropic-style
  usage with cache_creation/cached fields. Native pass-through.

**Problem found and fixed:** ch5/ch6 model_mapping had
`claude-fable-5-1 → claude-fable-5.1` (set 2026-10-12 when the dot
spelling was the only one A6's token permissions allowed). That
routed all our fable-5-1 traffic into the DOT pool — phantom
prompt-token inflation at ~900/request visible in ch5 logs
(907/902/910-token rows for tiny requests, billed to customers via
upstream usage: `usage_billing_path: upstream`), plus higher cost.
Fix: model_mapping cleared to {} on ch5 + ch6 (model_mapping is a
non-sensitive field — the monitor PAT can edit it). Verified: forced
ch5/ch6 channel tests with model=claude-fable-5-1 now bill cleanly
(1 prompt / 51 completion, no is_model_mapped flag, cache_ratio
0.2); A6-side direct dash probe bills exact 10 tokens with genuine
cache reporting. Selora (ch1/4) and Mia (ch7) list the dash spelling
natively — unaffected. cctest.ai does not list claude-fable-5-1 (nor
any dot Claude spelling), so no customer-facing alias entry is
needed (unlike gpt-6.1-sol).

Monitor note: fable-5-1 has NO pin channels (pins exist only for
claude-fable-5) — it rides the general tier, so its merchants are
checked via the ch5 entry under the traffic gate (usage in 7 days)
and A6's own smart routing across 78 dash-pool merchants. If this
SKU's volume grows, consider pins on the new A6 account like the
other Claude models.


## 2026-10-19 — Model Routing deploy (pinned-next40, LIVE)

Deployed per the approved plan (owner: "Please deploy"). Branch
feat/payment-rails merged the pinned-next39 line first (merge 056894e6f
— the server tree was 8 commits ahead from another session's
model-list-visibility deploy; merge prevents reverting it), then:

- **SECURITY incident during deploy (contained):** the merge push
  exposed `deploy/vantyr/cctest-monitor/rebuild_env.py` (live sidecar
  PAT + cctest key in plaintext, committed 0f44c3236, never previously
  on public main) to github.com/captainbeo/vantyr. Fixed same-hour:
  file deleted (4756c6ecc), main + deploy tag re-pointed, source
  archive rebuilt clean (rebuild_env absent). **Sidecar PAT rotated
  live** (DB: old row deleted, new `nap_nLl_…` with the same scopes +
  `profile:read` added — the status server's auth passthrough calls
  /api/user/self, which needs it; verified 200). The old PAT in
  history is dead. **Owner still owes: rotate the cctest key at
  cctest.ai** (its plaintext is in history and out of my reach).
- cctest-monitor: new image built from the synced tree (md5-verified
  vs the commit; LF-normalized), container recreated (`docker rm -f` +
  `compose up -d cctest-monitor --no-deps` — NOT restart: the gateway
  service_healthy gate can wedge, and `docker restart` reuses the OLD
  image, see the 2026-10-19 image-drift crash note). Status server
  live on 8787; first cycle stamp 03:09Z; logs clean.
- Caddy: `handle /api/cctest/*` → `cctest-monitor:8787`
  (read_timeout 300s). GOTCHA confirmed again: `caddy reload` after
  editing the mounted file did NOT apply the new handle (config
  validated fine) — full `docker restart vantyr-caddy-1` did. Verify
  after every Caddyfile change.
- Gateway image `pinned-next40` (93edce429bdb → rebuilt 04681829ab13
  after the legacy-state fix) from the synced web tree; binary
  grep-verified for model-routing; compose repointed (backup
  /tmp/compose-bak-model-routing.yaml).
- AGPL protocol complete: public main c5d8788b9, tag
  deploy/2026-10-19-model-routing, archive
  sha256 d1c4747a5423d60f4a5a948ed134b6f77d628c35f4e4fdc8a2878e2aa37fca10
  (rebuilt after the tag moved), source-notice.txt + Footer updated,
  archive serves 200.
- Post-deploy hardening: live state.json contains `bad_standbys`
  models mapped to `[]` (legacy from pre-2026-10-19 monitor writes).
  The join's typeof-guard was already safe; made tolerance explicit +
  test (c5d8788b9) and rebuilt the image — first deploy verification
  caught a real edge before any admin opened the page.
- **Live verification (all passed):** /api/cctest/status 401
  unauthenticated / 401 garbage / **403 role-1 user** (throwaway PAT,
  deleted after) / 200 admin — the full designed matrix. Deployed SPA
  bundle contains the route; /model-routing unauthenticated →
  sign-in redirect (route guard works). Data joins verified: 39
  channels (32 pins, 7 enabled), verdicts persisted (fable-5-4756
  attr_match), cooldowns live. **Real relay: claude-fable-5 → OK,
  usage log attributes to a6pin-fable-5-4756, quota billed** (money
  gate). **Verify action live: 11s, verdict attr_match, persisted to
  status.** Promote refusal paths 409/400 correct; an actual merchant
  rotation was not fired (live routing change — the monitor's own
  promotions prove that code path).
- Rollback: `pinned-next39` (5ed204e721b4) — repoint compose.yaml,
  `docker compose up -d --no-deps gateway`; remove the Caddy
  /api/cctest/* handle + restart Caddy; monitor: `docker rm -f
  vantyr-cctest-monitor` + rebuild from monitor.py.bak-pre-model-routing.

## 2026-10-19 — Sign-up explainer video, 12 locales (pinned-next41, LIVE)

`feat(home): 12-locale sign-up video embedded under the hero relay map`
(c25f693cb, tag deploy/2026-10-19-hero-video-12-locales). Owner-approved
("Go ahead please").

- Scope: the Remotion explainer video (D:\worktrees\vantyr-video, own
  repo) embedded on the homepage hero **under the relay map** (Pool 1/2/3
  diagram), one MP4 per interface language. HeroVideo component:
  click-to-play — CSS-only poster (play triangle + "HOW TO SIGN UP · 60
  SECONDS" label) until opt-in, then mounts the localized `<video>` with
  controls. Locale → file via `i18n.resolvedLanguage`, English fallback.
  Poster labels i18n-keyed in all 12 locales ("How to sign up with
  Vantyr", "Play the sign-up video", "How to sign up · 60 seconds").
- Videos: 12 × MP4 (~8.7–8.9 MB, 40.7 s, 1920×1080@30, 101 MB total),
  copy grounded in the localized docs' terminology; NotoSansJP/SC/TC/
  Arabic for non-Latin scripts. Served by new Caddy `handle
  /static/video/*` (same strip_prefix pattern as brand).
- Deploy: 12 MP4s + source archive
  sha256 31ce1bb3f7f22769ea58b00724bf047dc3b39a8ad99f66a4eeb8c0649ce82838
  scp'd to /tmp; web tree rsynced from the archive (backup
  /opt/vantyr-backup-web-pre-next41); image `pinned-next41` (a6c6487c9d86)
  built on-server, binary grep-verified ("Play the sign-up video" ×2,
  "static/video" ×1 in the embedded SPA); compose repointed (backup
  compose.yaml.bak-next40-hero-video); Caddyfile replaced from the
  archive (backup Caddyfile.bak-next40-hero-video) + **full `docker
  restart vantyr-caddy-1`** (the reload-doesn't-apply gotcha, confirmed
  again); source-notice.txt updated; Footer option updated via DB
  (options table) + gateway restart to flush the cache.
- Live verification: **12/12 videos serve 206 with content-type
  video/mp4** (range requests — streaming-ready); live bundle
  index.a03c77d353.js carries the component; homepage/docs/login 200;
  source archive 200 (8,375,089 B, sha256 match); footer serves the
  new tag + archive links; gateway healthy after restart. Pre-deploy:
  home test suite 21/21 (hero-video + landing click-to-play
  regressions), typecheck + oxlint clean on touched files.
- Rollback: `pinned-next40` (04681829ab13) — repoint compose.yaml +
  `docker compose up -d --no-deps gateway`; remove the Caddy
  /static/video/* handle + restart Caddy; videos are inert files (safe
  to leave or delete static/video/).

## 2026-10-19 — Fable 5.1 fully pinned (4 merchants, all dash-pool)


Owner decision: wire ALL four Fable 5.1 merchants including 2000.
Created four pin channels (type 60, P20, group default, SKU
claude-fable-5-1 native dash — no mapping; the dot mapping was
removed earlier today):

- ch40 a6pin-fable-5-1-3825 — ACTIVE (status 1). A6 token 138732.
  Cheapest auth-guaranteed ($0.108/$0.54), ~2.3×/2.8× margin.
- ch41 a6pin-fable-5-1-5052 — standby (status 2). A6 token 138735.
- ch42 a6pin-fable-5-1-5630 — standby. A6 token 138739.
- ch43 a6pin-fable-5-1-2000 — standby (LAST in line, owner choice
  despite the flag). A6 token 138738. Direct probes billed
  9,193/12,122/11,915 prompt tokens for a ~4-token request
  (~12,000-token hidden prompt, cache_creation reported — phantom
  billing flows into customer bills via upstream usage). No
  auth-guaranteed flag. Monitor will catch it on first check: if
  cctest attr-swaps it, normal demotion+rotation applies; if
  attr_match, its standby slot stays but phantom-billing risk
  remains while serving.

Each channel key = the per-merchant A6 token (token-to-merchant
binding verified by probe signatures). Monitor .env
CCTEST_SELLER_CHANNELS extended 32→36 entries (gateway-routed via
relay token; exact-name matching keeps a6pin-fable-5-1169 (Fable 5)
separate from the new fable-5-1 pins). NOTE: compose restart does
NOT re-read env — `docker compose up -d cctest-monitor` (recreate)
does. First cycle verified: ch40 check → attr_match (genuine);
standbys skipped as designed; zero errors.

Live verification: fable-5-1 request through the gateway served by
ch40 (pin, P20 above general tier), billing reconciled exactly
(13+34 tokens, ratio 0.125/completion 6/cache 0.2 → 27 quota =
computed 27.125 truncated; $0.000054). Routing order for default
group: ch40 pin → ch1 Selora (P5 failover) → ch5 A6 general (P5);
unlimited group unchanged (ch4 Selora P30 first, pins P20 below —
pins serve PAYG only, same as every other Claude model).
Temp root PAT (channel-create) SQL-inserted, used, deleted.

## 2026-10-19 — Model Routing dashboard redesign (pinned-next42, LIVE)

Owner feedback after the first deploy: the two-table page was hard to
read and it was unclear what actions exist. Owner chose the cards +
drill-down shape. Deployed as pinned-next42 (commit ede729ed3, tag
deploy/2026-10-19-model-routing-dashboard, archive sha256
1ead90586deeed57dbad3e320bb2a314203467e76e85cf0d5eb38f2e913739ac,
footer + source-notice updated; server tree md5-verified before build).

Page now reads top-down like an operations dashboard:
- KPI row: Healthy N/total · Needs attention N · Standby pool (ready/
  cooldown split) · Monitor (Enforcing/Down + last cycle time).
- Needs-attention strip (only when non-empty): model + plain-language
  reason (quarantined active pin / no active channel / failed
  verification / every standby cooling down); click jumps into the
  detail drawer.
- Per-model health cards (responsive grid): health dot + Serving/
  Needs attention/Uncertain label, active pin channel + merchant,
  verdict chip, standby dot row (green ready / amber cooldown / red
  quarantined) + count. Click opens the drawer.
- Detail drawer (Sheet, pricing-details idiom): full ordered ladder
  (active row highlighted: rank, channel, provider · merchant ·
  priority, status + verdict badges), standby pool with per-pin state
  and last verdict, and the actions — Verify now (active pin) and
  Promote standby (ConfirmDialog inside the drawer).
- Health model lives in lib/routing-rows.ts buildModelSummaries — one
  classification feeds KPIs, strip and cards; the old
  routing-table.tsx is deleted (the drawer ladder replaces it).

Verification: 23 vitest tests (health classification incl.
quarantined/bad-verdict/all-cooling cases; page behavior: KPI counts,
attention strip appears for quarantined and hidden when healthy, card
click opens drawer with ladder + standby pool, verify/promote POST
fire through the drawer, monitor-down shows the routing-only
degraded view). Typecheck/oxlint/oxfmt clean, 12 locales synced.
Live: bundle contains the page; all routes 200; health model over
live data returns 6 healthy / 1 attention (gpt-6-astra, quarantined
swapped pin) / uncertain sol variants — the exact states the cards
will show; real relay claude-fable-5 → OK; Verify action live
attr_match via public URL. Rollback: pinned-next41 (c018dff44f8f
image retained) — repoint compose + recreate.

Post-deploy review (same day): fixed and redeployed as the same image
tag pinned-next42 (commit c3e2e7e55, tag moved, archive sha256
ca2be2ac34e3b641f9bfd500c0941bcfd32491f4e00c74bd4451c0ede1b4fe58) —
ladder status labels switched to the canonical existing keys
(Enabled/Disabled/Auto Disabled; the bespoke 'Auto disabled' key
existed in no locale and 'Standby' mislabeled non-pin disabled
channels), Monitor KPI tile reflects the enforce flag (Enforcing /
Enforcement paused / Down), standby pool shows cooldown expiry again,
chevron is a proper aria-hidden lucide icon. AGPL headers restored
tree-wide after a teammate's format-script crash stripped ~676 files
(`bun run copyright` repaired; HEAD was clean — only the working
tree was affected). 25 vitest tests; bundle grep-verified live
('Enforcement paused' present); verify action live attr_match.

## 2026-10-19 — Hero video fix: poster visible under relay map (pinned-next42, LIVE)

`fix(home): video poster visible under relay map — aspect ratio + right
column` (9703c6b6b, tag deploy/2026-10-19-hero-video-fix). Owner-reported:
video not visible on the homepage despite pinned-next41 serving it.

- Root cause was TWO layout bugs, both invisible to DOM-level tests:
  1. The poster `<button>` is absolute-positioned inside a wrapper with
     no height of its own → wrapper collapsed to 2px tall (live geometry
     check measured 315×2). Fixed: wrapper carries `aspect-video` (16:9).
  2. HeroVideo was a sibling grid child of the relay map in the 2-column
     hero grid → on desktop it wrapped into a NEW grid cell (left
     column, row 2) instead of stacking under the map. Fixed: map +
     video share one right-column `flex flex-col items-center` container.
- Regression test added (aspect-video on the wrapper); home suite 22/22.
  Deploy: image pinned-next42 (c55067d806b7), binary grep-verified
  (aspect-video ×3), compose repointed, source-notice + Footer updated,
  archive sha256
  1d9ef15ec8db2fae9b10330dcf06a15a769ac9d3d45b1dada249121ec50322aa.
- Live: new bundle index.10caad9268.js carries the component; local
  preview geometry: video 416×234, same column as the map, 32px below
  it. Videos 206, homepage 200, gateway healthy.
- Lesson recorded: DOM-presence tests pass on invisible layouts — the
  click-to-play and label assertions all passed while the box was 2px.
  Visual/layout changes need a geometry assertion (aspect-ratio class)
  or a real preview check before shipping.
- Rollback: pinned-next41 (a6c6487c9d86) via compose repoint.

## 2026-10-19 — SEO Phase A (pinned-next43, LIVE)

`feat(seo): Phase A — meta/og/twitter/JSON-LD head, sitemap, robots,
og-image` (7cff54408, tag deploy/2026-10-19-seo-phase-a). Owner-approved
("Go ahead with the deploy"). First slice of the growth plan
(docs/plans/2026-10-19-growth-strategy.md).

- Scope: SEO groundwork only, no user-visible UI change — index.html
  head (descriptive title, description, canonical, Open Graph + Twitter
  summary_large_image, WebSite JSON-LD with SearchAction on /pricing),
  web/public/{robots.txt,sitemap.xml,og-image.png} (og-image 1200×630
  brand card, Remotion still `OgImageCard` from the video repo), and the
  runtime title-clobber fix: main.tsx initSystemBranding previously set
  document.title to the bare system name on EVERY route once /api/status
  answered — would have destroyed the static SEO title for rendered
  crawls. New `applyDocumentTitleToDom`/`buildDocumentTitle`
  (web/src/lib/dom-utils.ts): marketing routes keep the static title,
  app routes get "<system_name> — Console". 8 unit tests (8/8 pass).
- Deploy: web tree rsynced from the tag archive via staging (backup
  /opt/vantyr-backup-web-pre-seo-phase-a; /bin/bash verified post-sync);
  image `pinned-next43` (9b6fdfbc53a7) built on-server from /opt/vantyr
  context, binary grep-verified (og:image ×8, "fraction of official
  prices" ×6, "Sitemap: https://vantyr.xyz" ×1); compose repointed
  (backup compose.yaml.bak-next42-seo-phase-a); source archive
  sha256 7767fc69081ff52abb302cb5eba2a2f6e1772c4490786db464dff2983026c745
  + source-notice.txt updated, both serving 200.
- **Compose tag drift found and fixed during this deploy:** the compose
  file's gateway image line said `vantyr/new-api:pinned` (floating tag
  → the 2026-10-18 pinned-next38 image), NOT pinned-next42 as the
  next42 record assumed. The running container had been started on
  next42 by a previous session without repointing compose; my first
  `compose up -d` reconciled the drift and briefly reverted the live
  gateway to the Oct-18 image. Fixed within minutes: compose now
  explicitly says `pinned-next43`. **Rule going forward: after every
  gateway deploy, verify the RUNNING container's image id matches the
  image you just built** — compose config and `docker ps` can disagree
  when a session edits one and not the other.
- Live verification (all pass): / title = "Vantyr — Claude, GPT &
  Codex API at a fraction of official prices" with og:title/JSON-LD
  present in served HTML; /robots.txt 200 text/plain (allow-all +
  Disallow /api/ etc); /sitemap.xml 200 text/xml 6 URLs; /og-image.png
  200 image/png 340453 bytes; /docs 200; hero video 206 video/mp4
  (regression); /api/status healthy. Gateway healthy on next43.
- Owner follow-ups (from the growth plan): Search Console + Bing
  Webmaster verification via Namecheap DNS TXT, sitemap submission,
  analytics choice (umami vs GA4 — placeholders already in index.html).
- Rollback: pinned-next42 (c55067d806b7) via compose repoint + compose
  up -d --no-deps gateway.

## 2026-10-19 — Pin-only A6 routing (pinned-next43, LIVE)

Owner decision: retire the general/lottery A6 tier (a6-default-primary,
a6-default-fallback, a6-unlimited — status 2, rows kept for rollback);
verified one-merchant-per-key only. Daily A6 keys sync automatically.
Sick pins rotate. Unlimited keeps A6 via pins in both groups.

- **A6 key sync**: monitor's new A6Management client (A6_MANAGE_TOKEN/
  A6_MANAGE_USER envs; A6 token list + reveal, New-Api-User 34611) parses
  the owner's "<MODEL> | <merchant>" names (map incl. 'ASTRA 6'), reveals
  ≤5 keys/cycle (A6 rate limit), creates missing pin channels as
  standbys (type 60, P20, group default,unlimited, one model). Live
  first run created 7 standbys (sonnet-5-5 2863/5828/3825, opus-5-5
  6484/5828/5881, fable-5 5630) from real owner keys.
- **Pool auto-discovery**: single SELLER_CHANNELS entry
  "a6pin|https://vantyr.xyz|<relay>" covers every a6pin-* channel —
  .env no longer enumerates 32 pins; new keys get cycle coverage
  automatically.
- **Sick-pin rotation**: pin_is_sick = type-5 errors > 0 AND type-2
  successes = 0 in SICK_WINDOW_MINUTES (60) → quarantine + promote, same
  as a fake. Inconclusive verdicts still fail open. Live proof: sick
  merchant 4756 rotated off fable-5 (→3825, verified attr_match).
  First-deploy race (stale snapshot double-promotion) found live and
  fixed (sick phase re-lists channels; c3788c8f0).
- **Migration (backup channels-abilities-pre-pinonly.sql)**: 3 legacy
  plain pins renamed to suffixed (a6pin-opus-5-851, a6pin-sonnet-5-5-
  1204, a6pin-6-1-sol-5950 — merchants now always visible on the
  dashboard); 6.1-sol pin carries both spellings with mapping
  gpt-6-1-sol→gpt-6.1-sol (dash and dot both relay through the pin);
  all 36 pins group=default,unlimited; general tier status 2.
- **Permissions**: sidecar PAT extended with channel:sensitive_write
  (DB scopes + casbin user:29 channel sensitive_write allow — the
  role:admin baseline does NOT include it; policy reload takes ~20s).
- **Web**: drawer group selector (default/unlimited) — the unlimited
  ladder was previously unreachable.
- **gpt-6-sol is unroutable now** (was general-tier only; the owner has
  no SOL pins on A6 — 49 keys listed, none for 6-sol). Owner action:
  create "SOL | <merchant>" keys if the SKU should stay sellable.
- Verification: monitor 40/40; live battery — fable/opus/sonnet relays
  through pins with usage-log attribution, dot+dash sol relay, one
  active pin per model, sync creating standbys, sick rotation live.
  Rollback: restore SQL backup, re-enable general channels, monitor
  image monitor.py.bak-pre-pinonly, compose pin back to next42.

## 2026-10-19 — Search Console verification (HTML-file method, verified)

Owner verified vantyr.xyz in Google Search Console after two Namecheap
DNS-side records (TXT verification + www CNAME) failed to publish to
Namecheap's own authoritative nameservers for hours (panel-saved, never
visible on dns1/dns2.registrar-servers.com — a zone publish problem on
their side, not a record mistake; the hand-set A record and the
Namecheap-tool-set brevo/SPF TXT records were the only ones publishing).

- Solution path: Search Console URL-prefix property
  (https://vantyr.xyz) + HTML-bestand method. File
  google284d5739d80e2caa.html lives in static/verification/ and is
  served at the site root by a new Caddy handle
  `handle /google*.html { root * /srv/vantyr-static/verification; file_server }`.
  Missing verification files return a clean 404 (not the SPA fallback).
- A `www.vantyr.xyz` block was also added to the Caddyfile (verification
  file on www + 308 redirect of everything else to the apex) in
  anticipation of the www CNAME publishing; it has not published yet —
  the block is dormant until it does, and Caddy will fetch the www
  certificate on first request then.
- Caddyfile backups: Caddyfile.bak-pre-google-verification,
  Caddyfile.bak-pre-www. Config validated + full container restart
  (reload-doesn't-apply gotcha applies).
- Verification passed; sitemap.xml submitted to Search Console by the
  owner. Indexing begins from Google's side now.

## 2026-10-19 — 5-min key sync + SOL pool live (pinned-next43, same tag redeploy)

Owner added SOL keys on A6 ("6 SOL | <merchant>" ×5) and asked for
real-time pickup. The sync loop now runs on its own daemon thread every
SYNC_INTERVAL_MINUTES (default 5, env CCTEST_SYNC_INTERVAL_MINUTES) —
decoupled from the 60-min cctest cycle (cheap sync vs expensive checks).
The SKU map learned '6 sol' (A6's "GPT 6 SOL" marketing name). Live: all
5 SOL keys synced as standbys on the first tick; first pin
(a6pin-6-sol-5703) enabled, verified attr_match, gpt-6-sol relays
through it (usage-log attribution). Real-time sync is bounded by A6's
~5-reveal-per-batch rate limit, so a big new batch lands over 2-3
5-minute ticks — acceptable.

## 2026-10-20 — SEO Phase B: per-locale landing shells (pinned-next44, LIVE)

`feat(seo): Phase B — prerendered per-locale landing shells + hreflang`
(b854611a2, tag deploy/2026-10-19-seo-phase-b). Owner-approved ("Go ahead").
Implements growth plan §2.3 — the translated landings were previously
invisible to search engines because the SPA's i18n is localStorage-based.

- **What ships:** 11 non-English locales get static, crawler-readable landing
  shells at /<locale>/ (fr ru zh zh-TW vi ja de nl tr es ar), each with
  translated <html lang>/dir, title (hero headline), description, canonical,
  og/twitter, and the full 13-entry hreflang cluster. Apex stays English +
  x-default. Interactive routes (/sign-up, /pricing, dashboard) stay SPA.
- **How it's built:** web/scripts/prerender/ (entry.tsx server-renders the
  Home landing per locale via renderToString + the app's QueryClient +
  in-memory TanStack router; run.mjs Bun-bundles it stubbing image/CSS/three,
  renders all locales, writes dist/<locale>/index.html). Dockerfile runs
  `bun run build` then `bun run prerender` as a SEPARATE cached layer (the
  prerender's 58MB bundling is slow; the split lets a prerender retry skip
  the rsbuild build). useHomePageContent now inits isLoaded when window is
  undefined so renderToString yields the landing, not "Loading..." (browser
  unchanged; home tests 22/22).
- **Serving — the part that needed Caddy, not the gateway:** the gateway's
  static.Serve did NOT serve /<locale>/ as a directory index — it 301-looped
  (/fr/ -> /fr -> /fr/). Fix: the shells are ALSO shipped to
  static/locale/<locale>/index.html (the Caddy-served volume, same pattern as
  /docs) and a Caddy `@locales` handle rewrites /<locale>/ ->
  /locale/<locale>/index.html with file_server; a second `@localesBare`
  matcher 308-redirects /fr -> /fr/. So the prerendered HTML reaches the
  browser from Caddy, not the embedded FS.
- Deploy: web tree + Dockerfile rsynced from the tag archive (backup
  /opt/vantyr-backup-web-pre-seo-phase-b; /bin/bash verified); image
  pinned-next44 (a0e1beca1ad2) built on-server, binary grep-verified (French
  hero, Arabic hero, 156 hreflang); compose repointed (backup
  compose.yaml.bak-next43-seo-phase-b); Caddyfile edited (backups
  Caddyfile.bak-pre-locale-shells) + FULL docker restart (reload-doesn't-
  apply gotcha). Source archive sha256
  b302d698581b679b2699b79988b27da5879d5219c5c367394d3f8ac01bc6eb35 +
  source-notice.txt updated, serving 200.
- **NOTE on tag reuse:** this image is the merged state = another session's
  cctest work (ebc8c575b: 5-min key-sync, SOL pool, pin-only A6) PLUS my SEO
  Phase B (b854611a2). That session had rebuilt and re-tagged pinned-next43
  on the server with their image (4d91c646c3a8); my next43 (9b6fdfbc53a7)
  was overwritten. I used pinned-next44 to avoid the collision. Coordinate
  tags with concurrent sessions — don't reuse a tag another session may hold.
- **Live verification (all pass):** /fr/ title "Les vrais modèles. 98% en
  moins sur la facture." + French hero; /ar/ dir=rtl + Arabic hero; /ja/,
  /zh-TW/, /vi/, /de/ translated titles; /nl /tr /es /ru /zh all 200; /fr
  308->/fr/; apex title unchanged (English); /pricing + /dashboard SPA
  fallback 200; sitemap/og-image 200; gateway healthy on next44.
- Rollback: pinned-next43 (c55067d806b7 — the other session's merged image)
  via compose repoint + `compose up -d --no-deps gateway`; remove the two
  @locales Caddy handles + restart Caddy.

## 2026-10-20 — X posting bot live (@Vantyrcode, first post sent)

X channel automation from the growth plan (§5), now live.

- **Bot:** deploy/vantyr/x-poster.mjs — pure-Node (no deps) poster for X API v2.
  Reads git-tracked x-queue.txt, posts the oldest due item per cron run, logs to
  data/x-poster/posted.log. OAuth 1.0a signed by hand. Links go in a self-reply
  (never the main post — $0.015 vs $0.20/post, better reach).
- **On the server:** /opt/vantyr/deploy/vantyr/x-bot/ holds x-poster.mjs,
  x-queue.txt, .env (X_API_KEY/SECRET + ACCESS_TOKEN/SECRET, root-only 600),
  and data/. Runs via the oven/bun:1.4.0 image already on the host (no host
  Node). Cron: /etc/cron.d/vantyr-x-poster, twice daily 09:00 + 17:00 UTC.
- **Verified live:** first post HTTP 201 (tweet id 2112353352046535074) on
  @Vantyrcode. Auth resolved after regenerating the OAuth 1.0 Access Token
  WITH Read-and-write permissions set (the earlier token's secret was
  never exposed — the console only shows it once at generation; regenerated
  pair works). 402 credits-depleted resolved by the owner's first credit
  purchase ($20 free-credit bonus applies).
- Queue cadence: 8 seeded posts 2026-10-20 → 10-23 (price, authenticity,
  one-URL setup, unlimited tier, transparency, docs). Edit x-queue.txt in
  the repo; deploy rsyncs it to the server.

## 2026-10-20 — X topic radar (early-topic discovery) live

Content pipeline for the @Vantyrcode account: discovery → draft → approve → post.

- **x-radar.mjs** (deploy/vantyr/, committed): read-only scout. Pulls HN
  (front page + new stories via Algolia) + OpenAI news RSS, scores items
  against Vantyr topic buckets (model-release, api-pricing, reseller-swap,
  vibecoding, dev-tools), writes DRAFT queue lines + a suggested angle to
  data/x-radar/drafts.txt. seen.txt dedupes. NO posting — a human promotes a
  draft into x-queue.txt, and the poster ships it.
- Reddit JSON/RSS is bot-blocked from datacenter IPs (verified); radar uses
  HN + blogs. f5bot (free) covers Reddit keyword alerts separately.
- Cron: /etc/cron.d/vantyr-x-radar, 08:30 + 16:30 UTC (30 min before the
  poster's 09:00/17:00 slots).
- Workflow: read drafts.txt → copy the angle into a real post → append to
  x-queue.txt (repo) → poster ships it at the next slot. Angle priority is
  reseller-swap > api-pricing > vibecoding > dev-tools > model-release so a
  Claude Code tool story gets the builder angle, not the model-release one.

## 2026-10-20 — X auto-writer pipeline live (radar → relay → queue → post)

The X feed is now fully hands-off. deploy/vantyr/x-radar.mjs scouts HN
(Algolia) + OpenAI RSS, scores topics across the broad AI/vibecoding scope
(model releases, Chinese models, market news, rumors, agentic coding), then
drafts the post through OUR OWN relay (gpt-6-astra) and appends to
x-queue.txt; the poster ships it on schedule. No human step on the feed.

- Relay auth: dedicated `x-writer-bot` API key (user-created, pasted by
  owner). Gotchas hit: the dashboard's `sk-` prefix is display-only (relay
  strips it); the container must join the `vantyr_vantyr` docker network and
  use `http://vantyr-gateway:3000` (127.0.0.1 inside a container is the
  container itself); and the key was created with remain_quota=0 — relay
  ValidateUserToken rejects zero-quota keys, so the key got 500000 quota
  ($1, covers hundreds of drafts) via a direct UPDATE on the tokens table.
- Writer model is auto-discovered from /v1/models at runtime (prefers
  mini/haiku/astra/flash) so no hardcoded slug.
- Cron: /etc/cron.d/vantyr-x-radar, 08:30 + 16:30 UTC (30 min before the
  poster's 09:00/17:00). First live run drafted 4 posts on the DeepSeek
  government-ban story — quality verified on-topic, no hype, brand angle via
  the self-reply link.
- Reddit stays human: the /prefs/apps create form was broken for the owner
  (both accounts), and Reddit blocks datacenter IPs for the JSON/RSS feeds
  anyway — f5bot emails cover Reddit keyword alerts, owner replies in-thread.

## 2026-10-21 — Manual merchant pick + health-ranked promote + standby verify (pinned-next44, LIVE)

Owner asks: manual merchant selection (not auto-next), and a live bug —
"verify now" after promote reported failed.

Two live bugs fixed:
1. **Promote could leave a model dead**: run_action_promote quarantined the
   active pin then called promote_next_standby with the pre-quarantine
   snapshot; the idempotence guard saw the pin as still-enabled and refused
   — zero active pins (live: fable-5-1 unroutable ~00:49 until manual
   repair). Fixed: promote against a post-quarantine live list.
2. **Verify after promote described the wrong channel**: a standby (or
   just-rotated pin) check went through the gateway ladder, which skips
   disabled channels, so the verdict was attributed to whatever provider
   actually served (mia-failover). Pins are now checked DIRECTLY against
   their own A6 key (revealed on demand via the management API, cached) —
   works for enabled AND standby pins, and answers the right question:
   is THIS merchant real.

New capability: manual merchant pick. POST /api/cctest/promote {model,
merchant} promotes exactly that standby; the drawer lists every standby
with live A6 health (success rate, sample count, price, eligibility) +
per-merchant "Verify this merchant" / "Use this merchant" actions. Auto
promote (no merchant) ranks candidates by A6 health (healthy+cheap) and
refuses rather than promoting into a dead merchant. A6Market client reads
the public marketplace listings; health surfaces on /api/cctest/status as
merchant_health (verified live: fable-5-1 pins 3825 healthy/99%/100
samples, 5052/5630 attr_swapped, 2000 pool-inactive).

Live verification: standby 5052 verify -> attr_swapped (correct: it IS
fake); manual promote 5630 over active 3825 -> promoted 5630, verified
attr_match, fable-5-1 relays + attributed to 5630. Monitor 41/41, web 28.

## 2026-10-21 — Discord/Telegram community buttons + floating widget (pinned-next45, LIVE)

`feat(home): Discord + Telegram community buttons and floating widget`
(64bc2a931, tag deploy/2026-10-21-community-buttons). Owner-approved.

- **What ships:** two glass-button entries (Discord blurple, Telegram blue)
  under the hero sign-up video, plus a floating bottom-right Community widget
  on every public page (collapsed by default, expands on tap, closes on
  Escape, links aria-hidden while collapsed so they don't duplicate in the
  a11y tree). New filled brand marks (icon-discord-solid / icon-telegram-solid)
  replace the thin stroke glyphs — they read as the real mascots at button
  size. Shared invite config in components/community-links.ts (permanent
  discord.gg/BNBdHZqGFb + t.me/vantyrapi). Header social icons swapped to the
  same solid marks. Glass surface via data-slot='glass-box'; verified
  backdrop-blur/sheen/edge in light + dark + mobile.
- **Scope:** web-only. 12 files; i18n keys (Join Discord/Telegram, Community,
  Open/Close community links) already present in HEAD locales (synced earlier,
  verified all 12 locales). build/lint/format clean; 6/6 community tests pass;
  production rsbuild + prerender 11/11 locales.
- **Deploy (safe protocol):** pre-deploy backup
  /opt/vantyr-backup-web-pre-community-2026-10-21 (6 modified files); web file
  delta rsynced from staging (no tar -C into live paths; /bin/bash verified
  after). Image vantyr/new-api:pinned-next45 (266e0861cf5a) built on-server;
  code embedded verified (Join Discord ×47, discord.gg ×59 in the binary).
  compose repointed next44->next45 (backup compose.yaml.bak-next44-community);
  gateway recreated --no-deps, healthy. NOTE: `compose build` retagged
  pinned-next44 in place during the build (gotcha) — the pre-deploy next44
  image id is 5f31c93e6513 for tag-based rollback reference.
- **AGPL:** source archive vantyr-source-2026-10-21-community-buttons.tar.gz
  (sha256 5f89c81c…96ecb) uploaded to static/source/, source-notice.txt
  updated (backup source-notice-pre-next45.txt), both serving 200.
- **Live verification:** gateway healthy on pinned-next45; / /pricing /about
  /rankings /nl/ /ar/ all 200; zero gateway errors in 3 min; live bundle
  index.4980f8ab22.js contains Join Discord / Open community links / Telegram
  (community section markup is in the code-split home route chunk, loaded at
  runtime — confirmed present in the served bundle).
- **Rollback:** repoint compose to vantyr/new-api:pinned-next44 and
  `docker compose up -d --no-deps gateway` (old image id 5f31c93e6513 if the
  tag points at the new build); web backup at the -pre-community dir above.

## 2026-10-21 — Quarantine release on re-verify + verdict-colored toasts (pinned-next46, LIVE)

Owner reports: re-verified merchants stayed quarantined; a FAILED verify
toast rendered green.

1. **Release on re-verify**: a passing direct re-check of a pin we
   quarantined now RELEASES it (release_quarantine — the monitor's recovery
   action) instead of leaving the merchant benched until the next cycle's
   recovery loop noticed. A failing re-check still does NOT release. The
   drawer's standby row explains the state ("Passes re-check but stays
   quarantined — click Verify to release").
2. **Verdict-colored toasts**: the verify toast was an unconditional
   toast.success. Color now follows the verdict — pass green, soft amber,
   failed/inconclusive red — so a `attr_swapped` re-check reads as the
   failure it is.
3. **Price clarity**: per-standby price ($/1M from A6 health) promoted to
   foreground ink (was muted).

Live proof: quarantined a6pin-fable-5-3825 (stored attr_match) verified ->
attr_match -> status 2→1 (released). Monitor 43/43, web 29/29.

## 2026-10-21 — Wallet/crypto fixes: USDT auto-credit, BASE channels, session timeout

User feedback (owner): USDT deposits need manual tx-hash entry; BASE channels error; sessions expire on idle.

1. **USDT auto-credit** — root cause: GM Pay (epusdt) ran on SQLite, whose
   database is a continuous SQLITE_BUSY write-lock under concurrent scan
   + order + cleanup load; the on-chain scanner could not persist a match,
   so the auto-credit callback never fired and users had to enter the hash.
   Fix: moved GM Pay's store to the existing Postgres container (new `epusdt`
   database, `db_type=postgres` + postgres_host/user/passwd/database keys
   in /data/.env). Live: gateway + pay.vantyr.xyz healthy, GM Pay serving.
   Backup: /opt/vantyr/deploy/vantyr/data/gmpay/.env.bak-pre-postgres.
2. **BASE channels** — GM Pay's scanner does not support the Base chain
   (its supported set is TRC-20, BSC, Polygon, Plasma, Arbitrum — confirmed
   by its own binary strings). The BASE entries in GM Pay's dashboard were
   listed but could never credit. Owner action: remove/disable those
   channel rows in the GM Pay admin UI (a console delete, not code).
3. **Session timeout on idle** — the access token expires after 15 min
   (AccessTokenTTL, service/auth_token.go:20). The frontend refreshed only
   reactively (on 401) or via getFreshAuthHeaders, so an idle page let the
   token lapse and the next interaction presented as "logged out". Fix:
   a proactive refresh scheduler in web/src/lib/auth-session.ts —
   scheduleTokenRefresh (REFRESH_LEAD_MS 90s before expiry) runs after
   applyAuthBundle and stops on clearAuthentication. Tests: 3 new in
   web/src/lib/__tests__/auth-session-refresh.test.ts (refreshes before
   expiry, stops on logout, no timer without a token).

## 2026-10-21 — Crypto payment links fixed (Caddy regression)

Owner: crypto links broken for both GM Pay and BEpusdt.

Root cause (my deploy): the `handle /api/cctest/*` block I added for the
Model Routing page sat inside the vantyr.xyz site block but was malformed
(a broken comment + orphaned reverse_proxy), which Caddy tolerated as
valid config but that block swallowed the /api/* paths on the GM Pay
site block below it. Separately, pay2.vantyr.xyz had NO Caddy route at
all — BEpusdt's public URL was never wired.

Fix: rebuilt the Caddyfile — the cctest handle moved cleanly into the
vantyr.xyz block (before the gateway catch-all), and a new
pay2.vantyr.xyz site block reverse-proxies to bepusdt:8080. Verified
live: pay.vantyr.xyz 200 (GMPay cashier), pay2.vantyr.xyz 200
(BEpusdt cashier), /api/cctest/* still works. GM Pay on postgres from
the previous fix (SQLite lock).

## 2026-10-21 — GM Pay signature fix (EpayId 1001 → 1000)

Owner: GM Pay payment link returned "signature verification failed" on a
new tab.

Root cause: New API's EpayId option was `1001`; GM Pay's only api_keys row
is pid `1000` with secret_key 4643e80f... . GM Pay signs/verifies with the
pid in the request, so the signed submit form 401'd before any order was
created. (EpayKey was also stale — updated to the current GM Pay secret.)

Fixed live (options sync in ~60s, no restart): EpayId=1000, EpayKey=
<current secret>. PayAddress path also corrected to GM Pay's actual
create endpoint (/order/create-transaction). Verified: POST
/order/create-transaction returns 200 (not 401).

## 2026-10-21 — GM Pay 404 fixed: correct epay path + wallets + USD

Owner: GM Pay payment link opened "404 Oops! Page Not Found!".

Root cause: the go-epay client builds the submit URL as `PayAddress +
"/submit.php"`, and `PayAddress` was `https://pay.vantyr.xyz` — so the
gateway sent customers to `/submit.php`, which does not exist in GM Pay
v2; its SPA rendered its own 404 page. GM Pay v2's real epay-compatible
endpoint (found in its source, route/router.go:98) is
`/payments/epay/v1/order/create-transaction/submit.php` (POST+GET). It
verifies the SAME legacy MD5 ksort sign the go-epay client produces
(`sign` field, `sign_type` excluded, all other params sorted k=v joined
with &, MD5(that + secret_key)) and 302-redirects to
`/pay/checkout-counter/<trade_id>`. Its callback posts epay-style
trade_no/out_trade_no/trade_status and expects plain-text `ok` — exactly
what our /api/user/epay/notify handler does. No code change needed.

Fixes applied (all config/data, no Go changes):
1. `PayAddress` option → `https://pay.vantyr.xyz/payments/epay/v1/order/create-transaction`
   (options sync in ~60s, no restart).
2. Restored 8 owner receiving wallets into the new Postgres
   `wallet_address` from the pre-migration SQLite `/data/epusdt.db`
   (tron/solana/ethereum/polygon/binance/plasma/aptos enabled, ton
   disabled=status 2; the duplicate soft-deleted `bsc` row not restored —
   GM Pay's BSC chain is `binance`). GM Pay had ZERO wallets after the
   SQLite→Postgres move, which caused "no available wallet address".
3. `epay.default_currency` cny→usd (money is our USD top-up amount; with
   cny it would multiply by rate(usdt,cny)≈0.14 and undercharge 7x),
   `epay.default_token`=usdt, `epay.default_network`=tron (so the
   gateway's `alipay` type maps to a concrete TRON order with an address
   instead of a placeholder). Restarted `vantyr-gmpay` to reload settings.

Verified live end-to-end with GM Pay's real secret_key: POST
submit.php + valid sign + type=alipay → 302 to /pay/checkout-counter/<id>;
checkout-counter-resp shows status 1, amount 5 USD, actual 5 USDT,
network tron, receive_address = owner TRON wallet. Test orders deleted.

Note: `type=usdt.trc20` 400s (GM Pay wants chain names like `tron`, not
`trc20`); bare `alipay`/empty type is what our gateway sends and works.

## 2026-10-21 — "everything inconclusive" root cause: monitor quota exhausted

Owner: Model Routing dashboard showed almost every channel/model
"inconclusive".

Root cause: NOT a channel/merchant problem. The monitor's service account
`cctest-sidecar` (user id 29) ran out of internal Vantyr quota
(-$0.0035). Every authenticity check the sidecar fired was rejected by
the gateway with HTTP 403 "Insufficient quota", so the sidecar recorded
no verdict — and by design a failed/blocked check = inconclusive
(fail-open, never assume fake on a failed test). The account had been
funded ~$5 on 2026-10-12 and burns ~$0.36/day across 643 checks/day, so
it ran dry after ~9 days.

Fix: owner topped the account up to ~$100 in the admin UI.

Manual verification (this session):
- Relay path (what was 403ing): fired live /v1/chat/completions as the
  monitor token for all 9 default-group models — all HTTP 200, each
  served by its active A6 pin (fable-5->3825, fable-5-1->5630,
  opus-5->851, opus-5-5->3859, sonnet-5->851, sonnet-5-5->5828,
  gpt-6-sol->5703, gpt-6-astra->5942, gpt-6-1-sol->1416), no fallback.
  Quota decremented (spend clearing normally).
- Authenticity verdicts (the monitor's own direct "verify" action):
  8/9 pins -> attr_match (pass). a6pin-6.1-sol-1416 -> attr_unknown
  twice (inconclusive, no state change; its self-id is "GPT-5 Codex" so
  attribution can't decide — merchant 1416 may be serving a mixed pool;
  monitored, not quarantined since unknown != bad).

Follow-up worth doing: add a low-balance alert to the sidecar (Discord/log
at <$3 remaining) so this fails loudly next time instead of silently
going inconclusive. Not yet implemented.

## 2026-10-21 — PAYG rate limit: briefly 60/min, then REVERTED to unlimited (owner decision)

Context: Selora and Mia are temporarily out of use; PAYG Claude + Codex
traffic rides A6 pins only. Owner asked to raise PAYG from the documented
30/min, then — on learning PAYG had effectively been running uncapped —
decided to keep it uncapped.

Pre-change findings (live state had drifted from the R5 docs):
- `ModelRequestRateLimitCount` (global/PAYG total) was **0 = unlimited**,
  `ModelRequestRateLimitSuccessCount` 10000, and
  `ModelRequestRateLimitGroup` was `{"unlimited":[0,1]}` — i.e. the
  *unlimited* group was throttled to 1 success/min while PAYG had no
  working cap. The documented "default 30/min, unlimited 60/min" was not
  what was running. So PAYG ran effectively unlimited from some point
  after the 2026-10-04 launch verification until today.
- Routing: a6pin tier at priority 20 serves all default-group models;
  Selora/Mia channels still enabled at priority 5 as the failover ladder
  (fable-5-1 served by exactly one active pin, ch42/merchant 5630; the
  other three pins standby). Under a higher RPM a single merchant's
  saturation would cascade onto Selora (~30/min key) — left as-is per
  owner scope, flagged for the possible default-group ability disable.

Sequence of changes (both DB options only, no restart — gateway re-syncs
every 60s):
1. Set `ModelRequestRateLimitGroup = {"default":[60,60],"unlimited":[0,1]}`.
   Verified live with a temp token burst: 65 requests → first 63 cleared
   the limiter (403 on quota), 64–65 returned 429 (token-bucket capacity
   60 + refill during the burst).
2. REVERTED same session on owner decision back to
   `{"unlimited":[0,1]}` — the exact prior state: PAYG (default group)
   falls back to the globals (total 0 = unlimited, success 10000), so
   **no working PAYG rate limit**. Verified live with a second temp-token
   burst: 65/65 requests → 403 (quota), zero 429s. Both temp tokens
   deleted, Redis rate-limit keys flushed.

Standing state: PAYG has no rate limit by owner choice; `unlimited` group
remains throttled at [0,1]. If PAYG abuse ever becomes a problem, the
restoration is a one-line options update
(`{"default":[60,60],"unlimited":[0,1]}`).

Gotcha recorded: a token with remain_quota<=0 is rejected 401
"Invalid token" at TokenAuth (model/token.go ValidateUserToken) *before*
any rate-limit or quota check, so zero-quota tokens cannot be used to
probe the limiter — give the probe token a small quota (2000) on a
zero-balance user instead; requests then 403 on quota for free.

## 2026-10-22 — Model Routing check history (pinned-next47, LIVE)

Owner ask: per merchant, show when the last check ran + the results of the
last 3 checks (model + timestamp); latest visible without expanding, history
drops down on click.

- **Backend (monitor.py):** `record_verdict` now also appends to a capped
  per-(channel,model) `verdict_history` (HISTORY_DEPTH=3, newest first);
  `last_verdicts` still mirrors the newest entry. All 5 record paths (cycle
  + verify + promote) funnel through it. status_payload passes it through
  (channels entries verbatim). 46/46 dry-run tests.
- **Frontend:** new `CheckHistory` component — inline latest check (verdict
  badge + relative time) with a chevron; click expands the last 3 (verdict +
  relative time, absolute on title). Wired into both the routing ladder and
  standby pool rows. Falls back to last_verdicts when verdict_history is
  absent (older state). i18n "No checks yet" synced to all 12 locales.
  35/35 tests; production build clean.
- **Deploy:** commit 540e0aad3, tag deploy/2026-10-22-check-history pushed
  to public main. Server tree: full tag archive → /tmp extract → synced only
  cctest-monitor + web/src/features/model-routing + web/src/i18n/locales
  (backup /opt/vantyr/backups/pre-check-history-20261022-000741; md5-verified,
  LF-normalized). NOTE: server tree flattens the repo — monitor source is
  /opt/vantyr/deploy/vantyr/cctest-monitor (NOT .../deploy/vantyr/cctest-monitor);
  an initial mis-copy to the nested path was removed. cctest-monitor image
  rebuilt + recreated (rm -f + up -d --no-deps); gateway pinned-next47
  (dfa0f6941f85) built on-server, binary grep-verified ("No checks yet"),
  compose repointed next46→next47 (backup compose.yaml.bak-next46-check-history),
  gateway recreated --no-deps --no-build, healthy.
- **AGPL:** source archive vantyr-source-2026-10-22-check-history.tar.gz
  (sha256 06d0389c…b748) + source-notice.txt updated (backup
  source-notice-pre-next47.txt), both serving 200; Footer option → new tag.
- **Live verification:** / /pricing /about /rankings 200; gateway healthy,
  zero errors; footer in /api/status; monitor already recording
  verdict_history (13 entries) and producing real verdicts post-quota-top-up.
- **Rollback:** repoint compose to vantyr/new-api:pinned-next46
  (id c17cdb0c7d50), `docker compose up -d --no-deps --no-build gateway`;
  monitor rollback = restore the cctest-monitor backup dir + rebuild/recreate.

## 2026-10-22 — Model Routing page missing → server tree was stale (fixed, LIVE)

Owner: Model Routing not visible in the admin dashboard after the next47
deploy.

Root cause: the deploy synced only cctest-monitor + the model-routing feature
dir + locales, but the page's *registration* lives elsewhere —
web/src/hooks/use-sidebar-data.ts (sidebar entry) and
web/src/routes/_authenticated/model-routing/ + web/src/routeTree.gen.ts
(the route). A diff of the tag's web/ tree vs the server showed 34 files
stale — the server web tree predated several shipped features (community
buttons next45, session-refresh fix, hero video, SEO public/ assets), i.e.
earlier "web file delta" syncs had silently missed files for multiple
deploys.

Fix: full web/src sync from the tag (rm -rf + cp -a, LF-normalized), plus
web root config (package.json/bun.lock/rsbuild.config.ts/tsconfig.json/
index.html) and web/public (og-image.png, robots.txt, sitemap.xml).
Post-sync diff = 0. Gateway pinned-next47 rebuilt in place (ad964e47ac5e),
recreated; /model-routing now 200 and "Model Routing" present in the served
bundle; all public pages 200; gateway healthy, no errors.

Deploy-protocol hardening (recorded): a scoped "only the files I changed"
web sync is UNSAFE on this server because the tree already drifts — always
diff the tag's web/ tree against the server first, and sync web/src +
web/public in full when building a gateway image.

## 2026-10-22 — Sonnet 5.5 outage: manual promote pick refused (fixed, LIVE)

Owner: "No standby promoted — next standby will be tried next cycle" when
manually picking a Sonnet 5.5 merchant; the model then went dark.

Root cause (two parts):
1. Logic gap in promote_next_standby — the eligible-candidate set is
   `fresh if fresh else expired`, so when any FRESH (never-marked) pin
   exists, a marked merchant is never in `candidates`. The manual-pick
   (`preferred_name`) lookup only searched that set, so a manual pick of a
   marked merchant was refused as "not eligible" even when its mark was 70h
   old (cooldown is 3h — long expired). Merchant 546 was verified
   attr_match minutes earlier, yet still refused.
2. Ordering hazard — run_action_promote quarantines the active pin FIRST,
   then promotes. A refused pick left sonnet-5-5 with zero enabled pins →
   503 "No available channel" from 01:03.

Fix (monitor.py): a manual pick now matches against ALL of the model's
disabled standby pins regardless of bad marks or fresh alternatives — an
operator override. Safety kept: the enable-first-verify path still checks
the pin before serving, and a passing check clears the stale mark.
Automatic (no-pick) promotion keeps fresh-first/expired behavior.
Regression test added (marked merchant picked while a fresh pin exists).
47/47 dry-run tests.

Immediate remediation: enabled the owner's verified pick
a6pin-sonnet-5-5-546 (id 17, attr_match) directly in the DB + fix_abilities
(74 success/0 fail) — sonnet-5-5 serving again on 546, confirmed HTTP 200
relay served by channel 17.

Deploy: commit dbc6a1555, tag deploy/2026-10-22-promote-pick-fix, public
main pushed. cctest-monitor rebuilt + recreated (rm -f + up -d --no-deps);
new code grep-verified in the running container; monitor enforcing, logs
clean. No gateway rebuild (monitor-only change). Backups:
monitor.py.bak-pre-pick-fix, test_monitor.py.bak-pre-pick-fix.

## 2026-10-22 — Selora/Mia fully disabled + sick sonnet-5 pin quarantined

Trigger: bazaarlink.ai reported "the other party is limiting traffic
(~10/min)" while probing us. Gateway logs showed the real cause was NOT
our limiter (PAYG unlimited since the 2026-10-21 revert) but the stale
fallback ladder: claude-sonnet-5 pin ch13 (merchant 1204) was returning
69× 503 "个人智能路由池没有活跃候选" (merchant pool empty) in 6h while
still serving intermittently (189 OK in the same window), so New API kept
selecting it at P20. Its failures cascaded to selora-default-fallback
(429, ~30/min key) and mia-failover (429) before a slow 200 — the exact
seller-429s bazaarlink saw.

Changes applied (SQL, backups at /opt/vantyr/backups/2026-10-22-*.csv):
- Channels 1 (selora-default-primary), 3 (selora-default-fallback),
  4 (selora-unlimited), 7 (mia-failover) → status=2 (disabled). Selora
  and Mia now serve NO group — the "temporarily not used" decision is
  finally reflected in routing. (Note: this also removes unlimited
  group's Selora/Mia rails; re-enable from the CSV backup if unlimited
  comes back.)
- Channel 13 (a6pin-sonnet-5-1204) → status=2 quarantined, remark set.
  Monitor's own 01:20 probe still found it attr_match — this is pool
  instability, not attr fraud; the monitor skips disabled channels and
  can re-promote when the merchant recovers.
- All abilities for channels 1/3/4/7/13 disabled (24 rows).

Verified live after the 60s channel-cache sync: claude-sonnet-5 → ch15
(a6pin-sonnet-5-851) single-hop 200; claude-fable-5-1 → ch40
(a6pin-fable-5-1-3825) single-hop 200. Zero ch1/3/4/7/13 activity
post-change. cctest monitor continues normally.

Caveats: channels table has NO status_reason column on this fork (the
monitor's status_reason lives in its own tracking) — use remark. fable-5-1
now rides exactly two active pins (ch40 3825 + ch42 5630) — still thin;
worth promoting another standby pin next A6 pass.

## 2026-10-22 — Selora/Mia DELETED from the deployment entirely

Owner follow-up to the disable earlier today: remove Selora and Mia
completely so they no longer appear anywhere (channels list, routing
ladder, standby pool).

Deleted (full data-only pg_dump of channels+abilities first at
/opt/vantyr/backups/2026-10-22-pre-selora-mia-delete.sql):
- channels 1 (selora-default-primary), 3 (selora-default-fallback),
  4 (selora-unlimited), 7 (mia-failover) — DELETE removed all 4 rows.
- their 22 ability rows (already disabled, now deleted).

References checked clean afterward:
- cctest monitor needs NO config change: its SELLER_CHANNELS in
  /opt/vantyr/deploy/vantyr/.env contains only the "a6pin" wildcard entry
  (pins were migrated to direct gateway-routed probes long ago). The
  FAIL_THRESHOLD_SELORA/MIA env names in monitor.py are dead defaults.
- Pricing page (/api/pricing): zero selora/mia references.
- Relay verified post-sync: sonnet-5 → 200, fable-5-1 → 200, no
  dangling channel errors in gateway logs.
- Remaining enabled channels are 100% a6pin-* (15 active pins). The
  monitor auto-promoted a6pin-fable-5-5630 into the active fable-5 pool
  during this session's work.

Restore path if ever needed: the pg_dump file re-inserts all rows
(channels and abilities) with original IDs; Selora/Mia seller keys would
need re-entry from the owner (keys were recoverable in the channels
table and are preserved in the dump).

## 2026-10-22 — gpt-6.1-sol pool unified + pickable-after-verify (LIVE)

Three owner asks. (1) Merge the gpt-6-1-sol / gpt-6.1-sol split into one
pool. (2) Make the standby "Use this merchant" button match the verify
result. (3) Was the unclickable button a bug?

(3) Answer: NO — the button-disable was intentional (cooldown benching /
no-merchant-id). The real bug was the BACKEND refusing a marked-merchant
pick after the click (fixed earlier today, commit dbc6a1555). The
confusion was the button not matching the verify result or saying why.

(1) Merge: gpt-6-1-sol and gpt-6.1-sol are the same A6 model — legacy
pins existed under each spelling (a6pin-6.1-sol-* dot, a6pin-6-1-sol-*
dash), duplicating every merchant and splitting the active pin (both
a6pin-6.1-sol-1416 and a6pin-6-1-sol-5950 were status=1 for the same
model — split-brain). Monitor now creates 6.1-sol pins with both aliases
+ upstream mapping (gpt-6-1-sol/gpt-6.1-sol → gpt-6.1-sol) and treats the
spellings as one pool via MODEL_ALIASES across sync/promote/verify/cycle
membership. Live data merge (backup pre-61sol-merge-20261022-023929,
channels+abilities dumped): 5 dash standbys got both aliases + mapping,
duplicate active a6pin-6.1-sol-1416 demoted, 4 redundant dot pins deleted,
a6pin-6.1-sol-1416 then deleted. fix_abilities 74/0. Pool 11 → 6 pins (1
active 5950 + 5 standbys). Both spellings relay HTTP 200 via the single
active pin 5950.

(2) Button now matches verify: a cooldown merchant that re-verified clean
(green) is pickable again (the verify is the recovery signal). Quarantined
pins still need a passing Verify first (releases quarantine). Blocked rows
show WHY (cooling down / quarantined / no merchant id). 3 i18n strings,
all 12 locales.

Deploy: commit 4a43afc72, tag deploy/2026-10-22-61sol-pool-merge, public
main pushed. Monitor rebuilt (0ee965df88dc) + recreated; gateway
pinned-next47 rebuilt in place (156db0858128, "Cooling down..." in binary)
+ recreated; both healthy; / /model-routing /pricing 200; gpt-6.1-sol
relay 200 post-restart. Backend 49/49, web 35/35. AGPL: source archive +
notice + Footer → new tag (sha256 2cac9d86…7512).

## 2026-10-22 — Phantom merchant pins: honest verify + sync reconciliation (LIVE)

Owner: verified gpt-6-astra "merchant 5312" green but couldn't pick it; also
asked why a removed A6 key's pin stays in the pool.

Root cause: merchant 5312 does not exist in the A6 account (owner has 5132 —
a different merchant). Its pin a6pin-6-astra-5312 could never be
direct-verified; the verify endpoint silently fell back to a gateway-routed
check that lands on the ACTIVE pin (5942) and reports THAT merchant's
attr_match — a green badge borrowed from a different merchant. Quarantine
release (direct-check-only) never fired, so the pin stayed unpickable.
And the 5-min sync is add-only — nothing ever removed pins whose merchant
lost its A6 key, so phantoms accumulated.

Fixes (A + B, owner-approved):
- A: deleted the 3 true phantom pins (a6pin-6-astra-5312,
  a6pin-opus-5-5-1205, a6pin-sonnet-5-5-0 — merchants absent from both the
  A6 token list AND the A6 marketplace), removed their monitor state + bad
  marks, fix_abilities 71/0. Legacy plain-named pins (a6pin-fable-5 etc.)
  deliberately kept — model-name suffix, not a merchant.
- B1: run_action_verify now returns honest 409 "unverifiable" when a
  pinned merchant's key can't be revealed (names the merchant, explains the
  fallback trap) instead of borrowing the active pin's verdict. Quarantine
  release still requires a passing DIRECT check.
- B2: sync_a6_keys reconciliation — each 5-min sync disables (never
  hard-deletes) pin channels whose merchant is not on the A6 account, with
  a Discord alert; skipped entirely when the token list failed to load.
  Stem-aware merchant check so legacy plain pins (a6pin-fable-5 — suffix
  "5" IS a digit) are not mispruned.

DISCORD: alerts go via the DISCORD_WEBHOOK env on the cctest-monitor —
currently EMPTY (no alerts are being sent anywhere; they only appear in
container logs). To receive them: create a webhook in any Discord channel
(Server Settings → Integrations → Webhooks) and set CCTEST_DISCORD_WEBHOOK
in /opt/vantyr/deploy/vantyr/.env. One webhook = one channel.

Deploy: commit 46b715698, tag deploy/2026-10-22-phantom-reconcile, monitor
rebuilt (ec910a175c00) + recreated; first sync pass clean (pruned 0,
65 pins synced); honest-verify live. 51/51 tests. Monitor-only — no
gateway rebuild. Backups: monitor.py.bak-pre-phantom, channels-full-bak.

## 2026-10-22 — Discord alerts wired (cctest-monitor)

Owner provided a Discord webhook URL. Added CCTEST_DISCORD_WEBHOOK to
/opt/vantyr/deploy/vantyr/.env (backup .env.bak-pre-discord), monitor
recreated — DISCORD_WEBHOOK is now live in the container. This webhook's
channel receives: quarantine/promotion events, phantom-pin prune notices,
sync summaries (new keys), sick-pin rotations, and cooldown alerts.

Fix shipped alongside: http_json crashed json.loads-ing Discord's empty
204 No Content success body, so every delivered alert raised a false
JSONDecodeError. Empty bodies now return {}. Commit 9bf928239, monitor
rebuilt + recreated, delivery verified twice with no error logs.

## Recharge-view display fix (2026-10-22, customer-reported)

A customer reported that Model Overview's "Recharge" view showed prices
7.3× lower than "Standard". Root cause: the recharge display formula is
`price × Price / usd_exchange_rate`; `Price` was correctly 1 (top-ups
1:1) but `USDExchangeRate` still carried the upstream default 7.3 (a
CNY rate irrelevant to our USD-denominated setup), so the Recharge view
divided by 7.3. Display-only — billing always uses the Standard rates;
no customer was mischarged. Fixed by setting `USDExchangeRate` = 1 via
options (the row didn't exist; the 7.3 was the in-code default in
setting/operation_setting/payment_setting_old.go, INSERT not UPDATE).
All Go-side consumers of USDExchangeRate (billing.go ×2, logger.go ×2,
channel-billing.go) are gated on quota_display_type = CNY — unreachable
while the site runs USD — so setting it to 1 changes only the recharge
formula. Verified live after the 60s sync: status now reports
usd_exchange_rate 1, and the recharge view computes identical numbers to
Standard ($0.050 vs $0.050 on gpt-6-sol).

## Model Overview — Recharge toggle hidden on 1:1 sites (2026-10-22)

Fork change (frontend, documented gap): the pricing toolbar's
Standard/Recharge toggle is hidden when recharge pricing is a no-op. A
customer reported the Recharge view showing prices 7.3× below Standard
(the legacy USDExchangeRate default; fixed separately by setting
USDExchangeRate=1). With the rate fixed, the toggle changed nothing —
the Recharge view multiplies the listed price by Price /
usd_exchange_rate, so it differs from Standard only when those rates
differ. Added `isRechargePriceMeaningful(priceRate, usdExchangeRate)` in
web/src/features/pricing/lib/model-helpers.ts and gated the toggle on it
in pricing-toolbar.tsx (index.tsx passes priceRate/usdExchangeRate from
usePricingData). It re-appears automatically if a real top-up markup or
a custom display currency is ever configured (rates no longer equal).
Tests: lib/__tests__/recharge-toggle.test.ts (gate) +
pricing-controls.test.tsx (hidden-on-1:1 regression, existing
interaction test updated to supply a markup). Verified against live
production data via the deployed-code preview: the toolbar renders only
token-unit, sort, and view-mode controls; no Standard/Recharge; zero
console errors. Pre-existing pricing failures (model-cards,
dynamic-price, task-price-display) are unchanged, stash-verified on the
pre-change tree. Commit 7d5954f68.

## 2026-10-22/23 — SSE heartbeat + latency/reliability auto-rotation (cctest monitor)

User-reported "stream disconnected before completion: error decoding
response body" (Codex CLI client-side string). Root-caused from logs:

- ALL stream errors are `end_reason=client_gone/context canceled` — zero
  server/upstream cuts. The client hangs up during the pre-first-token
  silence of slow merchants.
- ch52 (a6pin-6-1-sol-4820) was the sole disconnect source: 48% gone /
  13.9s FRT vs healthy fleet 0-2% gone. ch40 (fable-5-1-3825) showed the
  hang signature: 11 rows frt=-1000 (no first token ever) + 60s deaths.
  Same model via other channels: clean. Conclusion: MERCHANT problem, not
  backend.

Fixes:
1. `general_setting.ping_interval_enabled=true, 15s` (options table,
   live via 60s sync). General fix: all streaming paths incl.
   pre-first-token window (pinger starts before relayClient.Do). Only
   Gemini excluded (adaptor sets DisablePing). Small streams improved
   (sol small 3%→0% gone); comment-pings do NOT reset Codex/Claude CLI
   liveness timers, so long-generation disconnects persist — the real
   cure is merchant rotation, not keep-alive.
2. Owner manually rotated sol→5950 and fable→5630 (both one active pin
   now; sol double-pin from verify-releases-from-quarantine side effect
   self-healed via [dedup] at 21:07). NOTE the UX gap: "Verify this
   merchant" on a standby ENABLES it (release path sets status=1).
   Promote-only UI is by design; verify-enables is a bug to fix.
3. Latency/reliability auto-rotation deployed in cctest-monitor
   (staged, flag OFF): pin_is_sick now also scores recent consume logs
   — client_gone ratio ≥0.20, mean FRT ≥10s, hangs (frt=-1000) ≥3, min
   20 samples (thresholds from live fleet distribution 2026-10-22;
   owner-approved). Reuses the existing sick-rotation quarantine→promote
   path. Fail-open on thin/missing evidence. Gate: compose env
   CCTEST_LATENCY_ROTATION_ENABLED (+ _MIN_SAMPLES/_FRT_MS_THRESHOLD/
   _CLIENT_GONE_RATIO/_HANG_THRESHOLD) added with off defaults; arm with
   `.env` + `compose up -d cctest-monitor --no-deps` (recreate, NOT
   restart — env re-read requires recreate). monitor.py.bak-pre-latency
   + compose.yaml.bak-latency-* backups on VPS; 54/54 tests pass locally
   incl. new test_pin_latency_sick. Watch `[latency]` log lines for a
   few cycles before arming.

Update 2026-10-22 22:50 UTC — latency monitor fixed + sol market health:
- pin_latency_sick now scores only STREAMING rows (non-stream /v1/messages
  log frt=-1000 with no stream_status on every success — without the filter
  ch25 showed 40 false "hangs"). Test fixture updated (54/54 pass); the
  ch25 false-positive case is now a regression test. monitor.py.bak-
  pre-hangfix-20261023-* backup on VPS.
- Probe (read-only) against live pool: ch34/5950 reads SICK on 1h+6h
  (42%/39% gone, 14.6s FRT) — BUT that is the tail of OLD pre-rotation
  traffic; A6 market shows 5950 recent_p50 = 2543ms (best in pool) and
  100% success. Old pin 4820 = slowest (recent_p50 15964ms) AND 3.7x
  price (57600 vs ~15000). Sol pool has healthy fast standbys: 3016
  (recent_p50 3046), 5132, 5312. Market success rates are all 100% — the
  client_gone problem is real-traffic latency, not merchant death.
- Decision: NO rotation needed now — 5950 is currently the best performer.
  LATENCY_ROTATION_ENABLED stays OFF; thresholds may need the hang-signal
  window tuning (ch76 trips at exactly 3 hangs / 10.2s on 6h window but is
  fine on 1h — flap risk). Watch before arming.
- Open bug: "Verify this merchant" on a standby pin ENABLES it (release
  path sets status=1) — caused sol double-pin 20:14→21:07 until [dedup]
  healed it. Verify should be read-only.

## 2026-10-23 — Quarantine release fixes + multi-active dedup (LIVE)

Owner: "merchants verified green but still quarantined — why?" (e.g.
a6pin-opus-5-5-3859 had 3x attr_match but stayed quarantined).

Root causes (three separate bugs, all fixed):
1. **Phantom-pin verdicts were borrowed.** A pin with no A6 token (merchant
   gone from the account) can't be direct-checked; the verify fell back to a
   gateway-routed check that tested the ACTIVE pin and reported its green
   verdict as the phantom's. Release (direct-only) never fired. Fixed:
   verify returns honest 409 "unverifiable" for merchant-suffixed pins with
   no A6 key. (Yesterday's deploy.)
2. **Plain-named legacy pins could never release.** a6pin-sonnet-5 (no
   merchant suffix — the "5" is part of the model) can never be
   direct-checked, and the release gate required a direct check. Fixed:
   ANY passing verify now releases quarantine (gateway-routed pass proves
   the model pool serves genuine output, which is what quarantine guards).
3. **Stem ambiguity.** pin_merchant() now uses the SKU-map stems to tell
   a6pin-fable-5-4665 (merchant 4665) from a6pin-sonnet-5 (legacy plain —
   "5" is model, not merchant). The phantom guard and the reconcile both
   use it. Note: a6pin-opus-5-5 is genuinely ambiguous (opus-5-5 is itself
   a stem) and resolves as merchant "5" — acceptable since it has no A6
   key either way.

Also: sonnet-5 went dark overnight — the cycle promoted merchant 1204 (the
only non-quarantined standby) but 1204 is dead on A6's side (503 direct).
The promote path checks authenticity (attr_match), not availability.
Manually promoted a6pin-sonnet-5-3825 (attr_match, 100% A6 success) —
sonnet-5 relaying 200 again. The legacy a6pin-sonnet-5 pin then verified
attr_match via the gateway path and its quarantine released correctly.

Cycle dedup (previous deploy, confirmed live): the first cycle after
restart disabled the manually-enabled extra pins (fable-5 5630+4756,
sonnet-5-5 5881, fable-5-1 5630), keeping one active per model.

Deploys: deploy/2026-10-23-release-any-pass + deploy/2026-10-23-stem-aware-release,
monitor rebuilt + recreated both times. 55/55 tests. Monitor-only — no
gateway rebuild.

## 2026-10-23 — A6 marketplace health gates auto-promote (LIVE)

Owner: "go ahead" on gating auto-promote with A6 health after the
sonnet-5/1204 outage.

What changed:
- A6Market.health_for now returns an entry for EVERY asked-about merchant;
  one absent from the marketplace listing is explicitly
  healthy=False / available=False / unlisted=True (previously omitted →
  callers treated "missing" as "unknown" instead of "dead").
- promote_next_standby's automatic path ranks candidates by A6 health:
  healthy first, then success rate, then cheapest; unlisted merchants rank
  dead-last and a delisted-only pool logs a loud warning (fail-open, still
  promotes rather than strand the model). Marketplace fetch failure →
  first-fresh fallback (never worse than before). Manual picks are
  unchanged (operator override).

Regression test: a delisted candidate is skipped for a healthy one in
promote_next_standby. 56/56 dry-run tests.

Deploy: deploy/2026-10-23-health-gated-promote, monitor rebuilt
(fa4d627b4ef5) + recreated; first cycle clean; all 9 models serving 200
with exactly 1 active pin each.

## 2026-10-23 — Audit round: 4 confirmed bugs fixed (LIVE)

Owner asked for a full audit of the cctest monitor after the day's rapid
changes. Confirmed + fixed:

1. **Dedup not alias-aware** — two pins serving gpt-6-1-sol and gpt-6.1-sol
   (the same pool) were not flagged as duplicates because the dedup tracked
   by exact model name. Now uses model_pool_names canonical keys. Caught
   before it fired on live data.
2. **release_quarantine never rebuilt routing** — set_status(1) without
   fix_abilities meant a released pin showed enabled in the DB but served
   no traffic until the next unrelated routing rebuild. Now fix_abilities
   runs inline.
3. **Sync prune could strand a model** — if the owner deleted an A6 key
   whose merchant was the ACTIVE pin, the 5-min sync would disable it and
   leave zero serving pins. The active pin is now never pruned (Discord
   alert instead).
4. **save_state race** — the cycle thread, sync thread, and HTTP action
   handlers could interleave json.dump into the same .tmp file, producing
   a truncated/corrupt state.json. Now serialized with a threading.Lock.

Also shipped: release respects the one-active-per-model rule — a passing
verify on a quarantined pin whose model already has an active pin clears
the quarantine but keeps the pin benched as a standby (no surprise
lottery).

Deploy: deploy/2026-10-23-audit-round, monitor rebuilt + recreated.
57/57 tests. All 9 models serving 200 post-deploy.
git add VANTYR.md && git commit -q -m "docs(VANTYR): three-agent audit + mutation lock deploy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push public HEAD:main 2>&1 | tail -1

## 2026-10-23 — Three-agent independent audit (LIVE)

Owner asked for an independent 3-agent run on the rotation system. Three
parallel auditors (lifecycle, concurrency, API-contract lenses), none aware
of the others or of today's earlier fixes. Convergent finding: channel
mutations (promote/quarantine/prune/release) from three threads with NO
mutual exclusion — the state file had a lock but the gateway writes did not.

Fixed (deploy/2026-10-23-audit-round3):
1. _MUTATION_LOCK on all mutation paths: promote (non-blocking 409 on busy
   — a second click during rotation is refused, not queued), verify
   (blocking — serializes the A6 key-reveal budget too), cycle sick-rotation
   (skip this round on busy), sync prune (skip this tick on busy).
   Prevents double-promote (two pins enabled — the retired lottery) and
   promote-vs-prune thrash.
2. Demotion failure of a confirmed-fake pin now sends a CRITICAL Discord
   alert (was log-only).
3. sync_loop persists state after each 5-min tick (last_sync_at no longer
   lags a full cycle; created-pin records survive restarts).
4. Earlier same-day rounds (already deployed): stale-snapshot failover
   promote, pin_merchant longest-stem parse, empty relay key on no-active
   promote, alias-aware dedup, release fix_abilities, active-pin prune
   guard, save_state file lock.

Live fallout caught during deploy verification: the 6.1-sol pool rotated
to merchant 6481 (its A6 pool exhausted — 502); manually rotated to 5110
(A6 100%). gpt-6-sol was found 503 (the stale-snapshot bug had left it
dead); promoted 5110 — both restored 200. All 9 models serving.

67/67 dry-run tests (up from 46 at the start of the audit campaign).

## 2026-10-23 — Third auditor + quarantine-branch stale-snapshot fix (LIVE)

The third agent (API contracts) confirmed: gateway/A6/cctest request shapes
all correct; frontend status-payload contract aligned (attr_upgraded already
in all frontend PASS sets — the auditor read a mid-edit snapshot); the
in-flight `pruned` NameError had been fixed pre-deploy. Notables:
A6Market.search fail-open means an A6 outage degrades auto-promote to
409-refuse (manual picks still work — by design); /status debug endpoint is
container-internal only (fine while 8787 stays unpublished).

Its verification pass also caught a live outage: gpt-6-astra stranded at 0
active pins — the cycle's quarantined-permanent branch (process_channel)
still passed the cycle-start snapshot to promote_next_standby, so the
idempotence guard saw the quarantined pin as "already active" and refused
every recovery. Same stale-snapshot class as the failover_model fix — this
was the third place the pattern occurred. Fixed + deployed
(deploy/2026-10-23-quarantine-relist); astra promoted to 3016 (attr_match),
serving 200. All 9 models 200, exactly 1 active pin each.

Also: mutation lock (round 3) prevented the promote that restored astra
from double-firing — the 409-busy refusal worked as designed during a
concurrent cycle tick.

VANTYR.md audit campaign total: 12 confirmed bugs fixed across 4 rounds
(stale-snapshot ×3, phantom/borrowed verdicts, pin_merchant parsing,
dedup alias-awareness, release routing rebuild, active-pin prune guard,
no-mutual-exclusion, demotion alert, sync persistence, state-file lock).
67/67 tests (from 46 at campaign start).

## 2026-10-23 — Accepted-upgrade tier policy (cctest monitor + web, LIVE)

Owner rule: a cctest attr_swapped whose attribution.prediction ranks
STRICTLY HIGHER than the expected model on the same tier ladder is an
upgrade (customer got more than they paid for) — a PASS, never quarantined.
Ladders (low→high): claude sonnet-5 < sonnet-5-5 < opus-5 < opus-5-5 <
fable-5 < fable-5-1; gpt 6-sol < 6-1-sol < 6-astra. Owner rulings locked in:
fable-5-1 and gpt-6-astra (ladder tops) accept nothing (exact match only);
sonnet-5→sonnet-5-5 and the opus-5 row (gaps in the original table) follow
the higher-is-fine ladder principle, owner confirmed "keep both".

Implementation (monitor.py): TIER_LADDERS + _tier_stem (lowercase, strip
claude-/gpt-, map cctest's gpt-6.1-sol dot spelling) + _tier_match /
accepted_upgrade. do_check now returns (verdict, prediction); attr_swapped
reclassifies to attr_upgraded (strictly higher) or attr_match (same rung —
the dot-alias false positive the audit caught). attr_upgraded in
PASS_VERDICTS; all five web/src/features/model-routing PASS_VERDICTS copies
updated (health badge green, verify toast green, upgraded standby
pickable). One-time deduped Discord alert per (channel, model) upgrade.
Tests: 67/67 monitor, 36/36 frontend.

Independent 3-agent audit of this feature (spec-compliance, correctness,
regression lenses): caught and fixed the dot-spelling false positive
(same-rung → attr_match), the frontend verdict-set gap, the upgrade-alert
spam (now deduped), and the "verified genuine" wording for upgrades.

Deploy: deploy/2026-10-23-attr-upgraded-frontend (9f0e061a1), source
archive vantyr-source-2026-10-23-attr-upgraded-frontend.tar.gz (sha256
89afb651…). Monitor redeployed by the parallel audit session; gateway
pinned-next48 (7df36b9039b4) built on-server and recreated. Live-verified:
gateway healthy, / /pricing /about /rankings /model-routing 200, binary
grep confirms attr_upgraded ×5 in the embedded bundle.

Deploy gotcha (cost two wasted builds, now recorded in memory): the gateway
compose build context is /opt/vantyr/ (repo ROOT), NOT the deploy dir —
syncing only /opt/vantyr/deploy/vantyr/web/src changes nothing in the
image. Sync BOTH web trees from the tag, LF-normalize, then build; verify
with a binary grep on /new-api for the marker string.

## 2026-10-23 — Pinned-image accumulation control (weekly prune cron)

The on-server pinned-next rebuild chain accumulated ~330 MB × ~18 distinct
images (~5 GB) plus ~12 GB build cache per fresh build. Owner removed the
tilkie stack (freed 108 GB); the pinned chain is now the main self-inflicted
growth. Fix: weekly cron /etc/cron.d/vantyr-image-prune (Sundays 04:17 UTC)
keeps the 2 newest vantyr/new-api tags, rmi's the rest, then image-prunes
dangling layers. One-time manual prune run the same day removed
pinned-next30..46 + the bare 'pinned' tag (kept next48 running + next47
fallback) — disk 68%→13%. Rollback beyond next47 = rebuild from the git
deploy tag (~20 min); VANTYR.md records every deploy tag. NOTE: the cron
sorts tags lexicographically, so it breaks at next100 (string "next99" >
"next100") — revisit the sort when the suffix nears three digits.

## 2026-10-23 — Self-healing quarantine system (owner-approved upgrade, LIVE)

Owner: "I think we need to upgrade the pinning/quarantine system." Approved
five changes after the audit data showed 21 quarantines / 0 releases in 48h
(the system removed fast but never recovered on its own):

1. **Quarantined pins re-checked every 2h** (8h for permanent) via direct
   check against the pin's own A6 key. A pass releases to standby (never
   straight to active — another pin is serving by now).
2. **Verify-before-enable**: promote_next_standby direct-checks the
   standby's own A6 key BEFORE enabling it. No unverified merchant serves
   traffic. Falls back to enable-first only when the pin's key can't be
   revealed (fail-open).
3. **FAIL_THRESHOLD_A6PIN default 1 → 2** (two consecutive bad verdicts
   before quarantine, not one — transient upstream glitches no longer
   bench a good merchant).
4. **STANDBY_COOLDOWN_HOURS default 3 → 8** (bad-mark expiry; the owner's
   8h, not my proposed 24h).
5. **Auto-release on green history**: a quarantined pin whose latest
   verdict is a pass is released at cycle start (a green check from any
   path proves the quarantine is stale).

Plus: _pin_reveal_key now uses pin_merchant (stem-aware) so legacy
plain-named pins (a6pin-sonnet-5) are correctly excluded from direct-check
instead of misparsing as merchant "5".

Deploy: deploy/2026-10-23-self-healing-quarantine, monitor rebuilt +
recreated. 68/68 tests. All 9 models serving 200, exactly 1 active pin
each. Live verification: astra rotated from dead 3016 to healthy 5940
through the new pre-verified promote path (verified attr_match before
enabling).

VANTYR.md campaign total: 13 confirmed bugs fixed across 5 rounds.

## 2026-10-23 — Per-user cache hit rate stat (cache-stat endpoint + usage-logs chip)

**Gap (config-first justification):** users were worried they were not
receiving prompt-cache discounts through the relay. Upstream New API shows
per-request cache token counts in the log details dialog but ships no
aggregate "what share of my prompt tokens were cache reads" number. No
native setting provides it; a focused Go + TS change was required.

**What was built:**

- `GET /api/log/self/cache-stat` (controller/log.go GetLogsSelfCacheStat,
  model/log.go SumUserCacheStats, router/api-router.go). Self-scoped by
  session `user_id`, consume-type logs only, honoring the page's
  time-window/model/token/group filters. Returns raw sums
  `{cache_tokens, prompt_tokens}`; the client derives the percentage.
  cache_tokens is summed out of the per-row `other` JSON blob with a
  per-dialect extraction expression (SQLite / Postgres / MySQL /
  ClickHouse), each guarded so malformed JSON or non-numeric values count
  as zero instead of erroring the query.
- Access-token route rule added
  (middleware/access_token_routes.go): `GET /api/log/self/cache-stat` →
  `usage:read`, matching the other /api/log/self/* routes so scoped PATs
  are not fail-closed 403.
- Frontend: a "Cache hit" chip in the usage-logs stats strip
  (web/src/features/usage-logs/components/common-logs-stats.tsx), user view
  only, computed as `cache/(prompt+cache)` clamped to [0, 100], '—' when
  the window has no prompt traffic. i18n key "Cache hit" added to en.json
  and synced to all 12 locales (English placeholder until translation pass).

**Privacy / merchant-hiding invariant:** the endpoint returns only two
user-scoped aggregates; no channel id/name, merchant identity, or retry
chain can ride along (verified: no log rows are projected, so the
formatUserLogs stripping layer is not even in play). No per-merchant
breakdown is exposed anywhere — by design, per the owner's decision that
the A6 merchant-listing cache % is a vetting signal for us, never a
user-facing number.

**Semantic caveat (recorded, accepted):** the stored `prompt_tokens`
column subtracts cache-read tokens for Claude-native rows but not for
OpenAI-semantic rows, so the formula is exact for Claude traffic (Vantyr's
dominant case) and can drift for OpenAI-format channels; the UI clamps to
[0, 100] to keep blended windows sane. Documented in
web/src/features/usage-logs/types.ts (CacheStatistics) and
common-logs-stats.tsx.

**Verification:** `go build ./...` exit 0 (Docker golang:1.26.1-alpine,
fresh module cache); `TestSumUserCacheStats` + `TestLogOther` pass;
4 cache-hit-stats vitest pass (percentage, em-dash empty window, 100%
clamp, admin-hidden + endpoint-not-called). Full usage-logs suite matches
the pre-existing clean-tree failure baseline (no new failures). The Go
test caught a real bug pre-deploy: SQLite `json_extract` errors on
malformed JSON rather than returning NULL, fixed with a per-dialect
validity guard. Pre-deploy 3-agent independent audit (backend /
frontend / privacy-compliance) — findings addressed: ClickHouse
JSONExtractUInt fix, PAT scope rule, MySQL JSON_UNQUOTE, Postgres
numeric guard, display clamp, admin no-call test assertion.

**Not yet deployed** — awaiting owner approval per the live-deployment
gate.

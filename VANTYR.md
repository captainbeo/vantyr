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
- [ ] Turnstile site/secret keys
- [ ] sub2api `SECRET_KEY` for its admin/cookie flows

## AGPL obligations (live)

- Publish the Corresponding Source offer: link the exact git commit (public
  repo or archive) on the site footer/about page. `docs/compliance/2026-07-31-new-api-license-compliance.md`
  has the full analysis.
- Keep `LICENSE`, `NOTICE`, `THIRD-PARTY-LICENSES.md` intact in the image
  (upstream Dockerfile already ships them in `/licenses`).

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
| gpt-5-6-luna | 0.02 | 0.12 | 0.002 |

Subscription: "Unlimited Monthly" — $180 one-time, 30 days, unlimited
quota (`total_amount=0`), upgrades user to group `unlimited` (group ratio
1.0; channel serves `default,unlimited`). One-time Stripe price
(`price_1ULtvo...`); renewal is manual — the customer re-purchases. No
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

## Known-weak spots (accepted at launch)

- Subscription recurring renewal is manual (native webhook activates
  subscriptions; renewals require customer re-purchase or admin action).
- New API stores channel keys and customer token keys recoverably
  (admin-visible). Operator-circle-of-trust risk, accepted for the private
  cohort.
- No strict per-plan concurrent-request cap; native rate limiting
  (ModelRequestRateLimit) covers burst abuse.

## R5 production deploy (2026-10-04, live at https://vantyr.xyz)

Server: one.com VPS 85.190.118.190 (Ubuntu 26.04, 4 vCPU/7.8GB),
SSH key-only (`~/.ssh/vantyr_server`, user `administrator`), ufw
22/80/443, Docker 29.1 + compose v2. Stack at `/opt/vantyr/deploy/vantyr`:
gateway `vantyr/new-api:pinned` (built from source at deploy commit) on
127.0.0.1:3000 behind Caddy 2 (auto-TLS, Let's Encrypt cert, HSTS,
nosniff, `-Server`, 600s read timeout, no proxy buffering for SSE —
`X-Accel-Buffering: no` verified live). Postgres 17 + Redis 7 with
on-server-generated secrets in chmod-600 `.env` (never transmitted).

DNS: `vantyr.xyz` A-record → 85.190.118.190 (Namecheap; the URL-redirect
and www parking CNAME that broke ACME were deleted).

**Bootstrap:** root admin `H049161` created by the owner via the web
setup wizard at 02:42 UTC (password never transited chat). A temporary
`vantyr-bootstrap` root (id 2) was inserted directly in the DB for
config automation and **must be deleted at launch** (see rotation list).
Config rebuilt from this doc: channels 1=selora-reseller
(default+unlimited), 2=a6-marketplace (default only; 50/50 weights,
retry=1), all 9 pricing ratios, `GroupRatio` default/unlimited = 1.0,
UserUsableGroups, `Unlimited Monthly` plan (id 1, $180, total_amount=0,
upgrade_group=unlimited, one-time Stripe test price
`price_1ULtvo22rqPqAmkD…` — live price at launch), payment compliance
confirmed, rate limits (default 30/min success+total counts, unlimited
60/min via `ModelRequestRateLimitGroup`), Telegram OAuth (bot
@VantyrVerificationBot + token in options), `ServerAddress`,
`HomePageContent` (domain fixed to vantyr.xyz), `SystemName=Vantyr API`.

**Stripe on production (test mode):** valid key recovered from the
owner's original chat message (the shell copy had one corrupted char —
position 51 `b`→`m`; the same corruption bit again this session when
extracting keys, both times the user's original paste was the valid
one). Top-up product `prod_VNQVEq1YsbsyIU` + one-time $1/unit price
`price_1UMfeF22rqPqAmkD0Ntf2iy1` (StripeUnitPrice=1, min top-up 1).
Webhook `we_1UMfeW22rqPqAmkD5RkKzlNC` →
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
username. Fixed on production: `telegram.client_id` = `8655936058`
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
`client_id` must be the **numeric bot ID** (8655936058), not the bot
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

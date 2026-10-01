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

## Known-weak spots (accepted at launch)

- Subscription recurring renewal is manual (native webhook activates
  subscriptions; renewals require customer re-purchase or admin action).
- New API stores channel keys and customer token keys recoverably
  (admin-visible). Operator-circle-of-trust risk, accepted for the private
  cohort.
- No strict per-plan concurrent-request cap; native rate limiting
  (ModelRequestRateLimit) covers burst abuse.

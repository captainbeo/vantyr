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

## Known-weak spots (accepted at launch)

- Subscription recurring renewal is manual (native webhook activates
  subscriptions; renewals require customer re-purchase or admin action).
- New API stores channel keys and customer token keys recoverably
  (admin-visible). Operator-circle-of-trust risk, accepted for the private
  cohort.
- No strict per-plan concurrent-request cap; native rate limiting
  (ModelRequestRateLimit) covers burst abuse.

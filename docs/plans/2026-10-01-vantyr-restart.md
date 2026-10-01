# Vantyr API — Restart Plan (config-first New API)

- **Status:** Decisions locked; ready for R0 execution
- **Date:** 2026-10-01
- **Replaces:** `docs/plans/2026-07-31-commercial-mvp.md` as the product
  authority for the restart. The old plan, its specs, and the `docs/aegis/`
  artifacts stay in git history as reference material only.
- **Core principle:** Vantyr is a *configured deployment* of New API, not a
  fork. Every line of custom code must map to a concrete gap we actually hit
  in operation. Target fork delta for v1: **zero Go code changes** — branding,
  channels, plans, pricing, and billing are all native settings.

## Why restart

The `codex/commercial-mvp` branch added ~30,000 lines of custom
`commercial_*` Go (access projections, wallet PAYG ledgers, Redis leases,
enforcement epochs, provider account pool, Stripe event inbox, …) plus ~18,000
lines of process documentation to re-implement things the pinned New API
already ships: token auth, quota, model permissions, channel routing,
multi-key rotation, usage logs, wallet top-up with Stripe checkout and
webhook order completion, subscription plans, pricing pages, and a Codex
OAuth-account channel type with credential auto-refresh.

Vantyr's actual requirements map to stock features:

| Vantyr need | Native New API answer |
|---|---|
| Customers get a Vantyr key + dashboard | Tokens, quotas, per-token model restrictions, usage console |
| Our own Codex (ChatGPT) accounts upstream | Channel type 57 "ChatGPT Subscription (Codex)": paste account OAuth JSON; auto credential refresh; multi-key rotation for several accounts |
| Our own Claude accounts upstream | Run sub2api against Claude Max/Pro accounts, add it as a Sub2API/NewAPI channel (see Decision B) |
| Third-party sellers (our base URL → theirs) | "New API" channel type 60: base URL = seller's URL, key = seller-issued key; multi-key (random/polling) across multiple seller keys |
| Usage billing | Wallet top-up via native Stripe checkout + webhook (order completes automatically); model ratios price every request |
| Reliability | Native channel priority/weight, retry, multi-key failover, per-channel test button |

## Locked decisions (2026-10-01, owner)

- **A. Baseline commit: v1.0.0-rc.41** (published 2026-09-30) — two months
  of Claude-adaptor and relay fixes over the old pin (`66ee6b8`, 2026-07-29).
  We fetch the exact tag and pin its exact SHA; we never track `main` or a
  moving `latest`. If a newer release tag exists on the day R0 executes, pin
  that tag the same way and note it here.
- **B. Claude source: own accounts via sub2api, with sellers as fallback.**
  sub2api (open-source, converts Claude OAuth accounts to an
  Anthropic/OpenAI-compatible API) runs as one small container next to the
  gateway; a native Sub2API channel points at it with the higher routing
  priority, and seller channels for Claude serve as fallback capacity.
  Accepted business risk: routing paid traffic through personal ChatGPT and
  Claude subscription accounts conflicts with those providers' ToS — the
  owner knowingly accepts this for the private cohort.
- **C. Billing mode: wallet top-up / PAYG only at launch.** Customers
  prepay credit; every request debits by model ratios through the native
  Stripe checkout → signed webhook → wallet credit loop. Subscription plans
  remain a later option; recurring renewal is the known-weak spot and is not
  being built now.
- **D. Hosting: deferred until R4 passes.** Needed before R5: server, DNS,
  TLS, Stripe live keys, backups — chosen with real usage data in hand.

## Execution phases

### Phase R0 — Repo and baseline (half a day)

1. Fetch the chosen upstream tag into this repo
   (`git fetch new-api-upstream tag v1.0.0-rc.41` or equivalent).
2. Create branch `vantyr/main` from that exact commit in a **new worktree**
   (e.g. `D:\worktrees\vantyr-main`); leave `codex/commercial-mvp` and
   `master` untouched as reference.
3. First commit on the new branch: this plan, an updated `AGENTS.md`/
   `CLAUDE.md` scoped to the config-first approach, and a short
   `VANTYR.md` deployment notes file.
4. AGPL hygiene from day one: keep upstream `LICENSE`, `NOTICE`,
   `THIRD-PARTY-LICENSES.md`; add a dated fork-origin notice in the README;
   plan to publish the Corresponding Source offer (repo or archive link) when
   the service goes live. Reuse the analysis in
   `docs/compliance/2026-07-31-new-api-license-compliance.md`.

**Gate R0:** fresh checkout builds (`go build ./...`, web `bun run build`),
`docker compose config` validates; nothing from the old branch is present
except the three documents we intentionally carry over.

### Phase R1 — Local deployment (half a day)

1. Write `deploy/vantyr/compose.yaml`: gateway + PostgreSQL + (if chosen)
  sub2api, Redis via env connection string; secrets only through env vars.
   Start from upstream's `docker-compose.yml`, not the old fork's
   `deploy/mvp/compose.yaml` (that one is coupled to mock channels).
2. Bring it up locally; create the root admin account.
3. Registration **off** until Phase R4 (System Settings → "Allow new users
   to register" disabled).
4. Create a first admin-side test token; smoke-test `GET /v1/models` with it.

**Gate R1:** compose is healthy, admin can log in, `/v1/models` answers with
a valid token.

### Phase R2 — Upstream channels (1 day)

One channel per upstream kind, configured through the admin UI
(Channels → Add):

1. **Codex accounts** — type "ChatGPT Subscription (Codex)". One account's
   OAuth JSON per key slot; multi-key mode `random` (or `polling`) to spread
   load across accounts. Verify the credential-refresh task is enabled.
   Verify with the channel Test button, then a real Codex CLI turn
   (`OPENAI_BASE_URL` pointed at the gateway, platform token as the key).
2. **Claude accounts** (per Decision B) — start sub2api, add a
   Sub2API/NewAPI channel pointing at it, with model mapping if names differ.
3. **Third-party sellers** — "New API" channel per seller (or one channel,
   multi-key, if a seller issues several keys): their base URL + the key they
   issued us. Set model mapping where their model slugs differ from the
   public names we sell.
4. **Routing policy** — channel priority/weight so our own accounts serve
   first and sellers act as fallback (e.g. own accounts priority 10, sellers
   priority 5), or dedicated model names per source, as preferred. Group
   multipliers in Operation Settings set the margin on seller-sourced usage.
5. Set model ratios/prices in Operation Settings so every model we sell has a
   real price (the pricing page and billing derive from these).

**Gate R2:** each channel passes its Test button; a real request through the
playground (or Codex CLI) completes per channel kind; usage log rows show
correct model, tokens, and cost.

### Phase R3 — Billing (half a day)

1. Stripe test-mode keys + webhook secret into env/settings; point the
   webhook at `/api/stripe/webhook`.
2. Enable wallet top-up (TopUp settings), set top-up min/max and the
   exchange rate that makes the pricing page sane.
3. Dry-run the full loop in Stripe test mode: top-up → checkout → test
   webhook → wallet credited → relay request consumes quota → usage log
   matches.
4. (Optional) configure subscription plans if wanted alongside wallets;
   renewal is manual until/unless we build the recurring lifecycle later.

**Gate R3:** the money loop works end-to-end in test mode with evidence
(order row, wallet balance, usage log).

### Phase R4 — Customer-facing setup (half a day)

1. Registration on: password + email verification (SMTP configured) +
   Cloudflare Turnstile keys.
2. `QuotaForNewUser = 0` — nobody gets free usage; first action is a top-up.
3. Document the customer flow on the landing/setup page (system name, logo,
   footer, homepage content — all System Settings; no code):
   register → verify → top up → create token (set quota/expiry/model
   restrictions) → point Codex CLI at `https://<our-domain>/v1`.
4. Enable native rate limiting (ModelRequestRateLimit) at sensible
   per-token/per-user RPM.

**Gate R4:** a scratch user can register, top up (test mode), create a
token, and complete a real Codex turn — without admin intervention.

### Phase R5 — Production deploy (requires explicit owner approval)

1. Server + DNS + TLS (reverse proxy or Caddy); secrets via env injection,
   never in files or chat.
2. PostgreSQL backups + a restore drill; Redis persistence on.
3. Stripe live keys; the Corresponding Source offer published.
4. Invite the first cohort; watch usage logs and channel health for a few
   days.

**Gate R5:** one real customer completes register → top-up → Codex turn on
the live domain.

## Hardening backlog (port from the old fork only when a real need appears)

These are the only pieces of the old 30k-line layer worth reconsidering,
each as a small focused change, never a bulk port:

- **HMAC one-time-display customer keys** — upstream stores token keys
  recoverably by admins. Acceptable for a trusted cohort; revisit if the
  operator team grows or a key leak occurs.
- **Strict per-plan concurrency caps** — the native per-user/token request
  rate limit plus wallet balance covers most abuse; port the Redis lease
  design only if measured abuse demands it.
- **Automatic subscription renewal lifecycle** — only if subscriptions
  become the main billing mode and manual renewal annoys customers.
- **Outbound transport hardening (SSRF guards, `env://` secret refs)** —
  relevant only if non-admin staff get channel-management rights.

## What we keep from the abandoned branch

- `docs/compliance/2026-07-31-new-api-license-compliance.md` (AGPL analysis).
- The Stripe subscription-lifecycle docs (the manual-renewal conclusion).
- `docs/specs/2026-07-30-channel-and-codex-compatibility-design.md` as a
  compatibility reference for Codex CLI behavior.
- Everything else stays in history for reference; the ~75 untracked scratch
  files in the old worktree can be deleted whenever.

## Effort estimate

R0–R4 is roughly **2–3 working days** of focused work including Stripe test
loops, versus the ~3 weeks the fork approach consumed. R5 depends on external
inputs (server, DNS, Stripe live approval) and owner approval.

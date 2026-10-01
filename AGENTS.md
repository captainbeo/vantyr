# AGENTS.md — Vantyr API (config-first New API deployment)

## Authority and scope

- These instructions apply to this repository/branch. They override
  user-global instructions when they conflict.
- Authority order:
  1. `docs/plans/2026-10-01-vantyr-restart.md` (the restart plan with locked
     decisions)
  2. `VANTYR.md` (deployment/ops notes)
  3. `docs/compliance/2026-07-31-new-api-license-compliance.md`
  4. Upstream New API documentation/README
- The abandoned `codex/commercial-mvp` branch is reference-only. Do not port
  code from it unless a documented, operational gap demands it (see the
  plan's hardening backlog).

## Product boundary

- Vantyr is a **configured deployment** of upstream New API at pinned tag
  `v1.0.0-rc.41` (commit `2035a82a`). Default answer to any product need:
  find the native setting. Custom Go code is a last resort and requires a
  documented gap plus a focused change with tests.
- Upstream sources are: our Codex OAuth accounts (channel type 57),
  Claude via sub2api sidecar + seller channels, and third-party sellers as
  "New API" (type 60) channels.
- Billing is wallet top-up / PAYG via native Stripe. No subscriptions at
  launch.
- Never hardcode vendor URLs, credentials, model slugs, or prices into
  product logic; they are channel/settings data.

## Non-negotiable gates

- Live deployment, real payment activation, customer invitations, DNS/SSL
  changes, publishing, and pushing require explicit owner approval.
- Secrets only via environment injection; never in files, chat, logs, or
  committed config. Check for literal secrets before any commit.
- Do not modify upstream code for style; keep the fork delta minimal and
  document every deviation in `VANTYR.md`.
- Preserve AGPL obligations: notices, license files, and the Corresponding
  Source offer for the live service.
- Money-relevant configuration (model ratios, group ratios, Stripe keys,
  top-up settings) is high-risk: verify changes with an actual checkout +
  request + usage-log pass in Stripe test mode before considering them done.
- Before any upstream re-pin, review the intervening upstream history and
  re-run the R-phase gates.

## Verification cadence

- For config-only changes: exercise the affected flow through the real UI
  or API (channel test button, playground request, test-mode Stripe loop)
  and record the evidence in the commit message or `VANTYR.md`.
- For any Go/TS code change (exception path): focused failing test first,
  then implementation, then the package test suite. `cd relaykit &&
  GOWORK=off go build ./...` must pass if relaykit is touched.
- Docker build from the pinned source is the release validation: never ship
  a registry `latest` image.

## Git

- Branch: `vantyr/main` from the pinned tag. Small, reviewable commits
  after each phase gate passes. Never amend/rebase/discard/push user work
  without explicit authority; never stage unrelated files.
- Do not commit secrets, scratch files, or temp outputs. Keep the tree
  clean of build debris.

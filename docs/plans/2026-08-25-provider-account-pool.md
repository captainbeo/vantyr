# Implementation Plan: Provider-Neutral Account Pool

## Overview

This plan adds an administrator-managed pool of authorized provider API accounts
while keeping New API as the customer-facing gateway and channel owner. Each
pool entry is linked to one New API commercial channel, so existing provider
adaptors, model aliases, secret-reference authentication, native multi-key
behavior, wallet PAYG, response commitment, and audit owners remain in place.

The pool is provider-neutral and can contain official API credentials for
DeepSeek, OpenAI, Anthropic, Gemini, or another supported channel. Consumer web
logins, cookies, browser sessions, and shared Plus/Pro subscriptions are out of
scope. No live resale, deployment, or provider activation is included.

The plan assumes the current dirty worktree. Existing staged, unstaged, and
untracked files are preserved; only files listed in an implementation step may
be changed or staged.

## Requirements

- Keep New API's native channel, model, key, and multi-key owners.
- Let an administrator provision multiple authorized provider API accounts using
  secret references, without storing raw credentials in PostgreSQL or logs.
- Route one customer gateway key to an eligible pool entry for the requested
  model and channel.
- Preserve the global concurrency limit of six and its Redis FIFO queue.
- Add bounded per-entry leases so an account cannot exceed its configured
  capacity across gateway instances.
- Use deterministic least-load selection with configured weight and stable ID
  tie-breaking.
- Exclude disabled, quarantined, expired, capacity-exhausted, and
  tenant-ineligible entries.
- Reuse existing health, attempt/usage, wallet PAYG, response fencing, audit,
  and sanitized-error controls.
- Never retry or replay after customer response bytes are committed.
- Keep provider authorization and the small funded proof as external gates.

## Architecture Changes

- `model/commercial_provider_account.go`: pool metadata linked one-to-one to a
  New API commercial channel; raw credentials remain in the channel's existing
  `env://` secret reference.
- `model/commercial_provider_account_migration.go` and
  `docs/migrations/2026-08-25-commercial-provider-account-pool.md`: PostgreSQL
  schema, ownership, bounds, indexes, compatibility, and guarded rollback.
- `service/commercial_account_pool.go`: candidate filtering, Redis lease
  acquisition/renewal/release, deterministic selection, and bounded errors.
- `model/ability.go`, `model/channel_cache.go`, and
  `service/channel_select.go`: expose eligible commercial channel candidates
  without replacing native legacy selection.
- `controller/relay.go` and `relay/common/relay_info.go`: attach one opaque pool
  lease to a request, release it on every terminal path, and retain existing
  health and response-fence ordering.
- `controller/channel.go`, `router/private_mvp.go`, and a focused admin
  controller test: reuse native channel administration while accepting and
  validating pool metadata only for administrator-authorized commercial
  channels.
- `service/commercial_attempt_usage.go` and existing attempt/usage models:
  retain channel ID as the internal account allocation evidence; do not create
  a second usage or billing owner.
- `docs/contracts/commercial-provider-account-pool.md`: freeze the admin/internal
  contract and the redacted status/error behavior before endpoint changes.

## Implementation Steps

### Phase 1: Contract, migration, and RED gates — minimum safe foundation

1. **Freeze the pool contract** (File:
   `docs/contracts/commercial-provider-account-pool.md`)
   - Action: Define administrator-only provisioning, update, disable, rotate,
     status, and redacted fields; link each entry to one New API channel; define
     model/capability filtering, lease states, bounded errors, tenant/group
     eligibility, and the rule that no customer route exposes provider data.
   - Why: Pool metadata and lease behavior must be unambiguous before schema or
     controller work.
   - Dependencies: Approved provider-account-pool design.
   - Risk: High — this is an authentication, routing, and secret boundary.

2. **Write the PostgreSQL migration contract** (File:
   `docs/migrations/2026-08-25-commercial-provider-account-pool.md`)
   - Action: Specify `commercial_provider_accounts` with a unique `channel_id`
     foreign key, bounded provider code and operator label, per-entry capacity,
     route weight, optional bounded spend cap, config version, timestamps, and
     indexes. State that channel status owns administrator enable/disable,
     Redis health owns runtime quarantine, and `channels.secret_ref` remains the
     only credential reference. Define forward ordering, compatibility reads,
     guarded rollback, and migration ownership evidence.
   - Why: Avoid a second channel or credential owner and make schema failure
     recoverable before implementation.
   - Dependencies: Step 1; data-migration review.
   - Risk: High — persistent routing metadata and foreign-key boundaries.

3. **Add deterministic RED tests** (Files:
   `model/commercial_provider_account_test.go`,
   `service/commercial_account_pool_test.go`,
   `controller/commercial_provider_account_test.go`)
   - Action: Add failing characterization tests for one-to-one channel binding,
     secret-ref-only validation, bounds, tenant/group eligibility, disabled and
     quarantined exclusion, capacity exhaustion, deterministic selection, and
     lease release on cancellation.
   - Why: Tests must prove the missing invariants before implementation rather
     than merely mirror finished code.
   - Dependencies: Steps 1–2; API-contract and data-migration gates.
   - Risk: Medium — fixtures must support PostgreSQL and Redis semantics.

**Phase 1 gate:** Contract and migration review are complete; RED tests fail only
for the intended missing pool behavior and no unrelated files are changed.

### Phase 2: Durable pool registry and administrator provisioning — happy path

4. **Implement the pool metadata model and migration runner** (Files:
   `model/commercial_provider_account.go`,
   `model/commercial_provider_account_migration.go`, `model/main.go`,
   `model/commercial_provider_account_postgres_test.go`)
   - Action: Add the one-to-one channel binding, bounded fields, PostgreSQL
     migration ledger, indexes, checks, and compatibility probe. Reject raw
     credentials, invalid channel ownership, non-positive capacity/weight, and
     configuration versions outside the accepted bounds.
   - Why: Durable metadata must be atomic, auditable, and safe across restarts.
   - Dependencies: Phase 1 gate; approved migration contract.
   - Risk: High — schema and startup migration behavior.

5. **Extend native channel administration with pool metadata** (Files:
   `controller/channel.go`, `model/channel_commercial.go`,
   `controller/commercial_provider_account_test.go`)
   - Action: Accept pool metadata only when creating or updating an existing
     commercial channel through native administrator authorization. Keep the
     channel's `env://` secret reference and provider adaptor fields as the
     source of truth. Redact secret references and pool internals from ordinary
     customer responses; record administrator mutations through existing audit.
   - Why: Administrators need one New API provisioning surface, not a parallel
     proxy or credential manager.
   - Dependencies: Step 4; existing commercial channel validation.
   - Risk: High — admin authorization and secret handling.

6. **Expose only the required native admin routes in private mode** (Files:
   `router/private_mvp.go`, `router/private_mvp_routes_test.go`)
   - Action: Add an explicit administrator-only allowlist for the existing
     channel-management routes needed to provision, disable, rotate, and inspect
     redacted pool entries. Keep customer registration, wallet, relay, and model
     routes unchanged; deny unrelated native/admin/static paths.
   - Why: Private mode must remain narrow while still allowing operator-managed
     accounts.
   - Dependencies: Step 5; existing role and session middleware.
   - Risk: High — route widening can expose unrelated New API surfaces.

7. **Verify provisioning and isolation** (Files:
   `controller/commercial_provider_account_test.go`,
   `model/commercial_provider_account_postgres_test.go`)
   - Action: Prove an administrator can add two entries, rotate a secret
     reference, disable one entry, and view only redacted metadata; prove a
     customer cannot list, mutate, or infer provider credentials or another
     tenant's eligibility.
   - Why: The pool is useful only if provisioning does not weaken the private
     access boundary.
   - Dependencies: Steps 4–6.
   - Risk: High — authorization and information disclosure.

**Phase 2 gate:** Two authorized entries can be provisioned through native New
API administration, durable metadata survives restart, and customer routes do
not expose pool or secret data.

### Phase 3: Redis allocation and relay lifecycle — core request path

8. **Implement the pool allocator and bounded Redis leases** (Files:
   `service/commercial_account_pool.go`,
   `service/commercial_account_pool_test.go`,
   `service/commercial_account_pool_redis_test.go`)
   - Action: Filter enabled commercial channels by existing ability/group/model
     eligibility, health state, capacity, and spend policy; choose least active
     load with weight and stable ID tie-breaking; acquire an owner/epoch-bound
     Redis lease atomically; renew it with a bounded loop; release it exactly
     once. Fail closed when Redis or the enforcement epoch is unavailable.
   - Why: Selection must be consistent across gateway instances and must not
     overrun an individual provider account.
   - Dependencies: Phase 2 gate; existing Redis and epoch services.
   - Risk: High — distributed lease and outage behavior.

9. **Expose eligible candidates without replacing native selection** (Files:
   `model/ability.go`, `model/channel_cache.go`,
   `service/channel_select.go`,
   `model/commercial_provider_account_selection_test.go`)
   - Action: Add a commercial-only candidate projection that retains New API
     model aliases, group eligibility, priority, and weight semantics. Leave
     legacy/non-commercial selection unchanged and prevent fallback widening.
   - Why: The pool needs a complete candidate set while New API remains the
     protocol and model-routing owner.
   - Dependencies: Step 8; existing commercial channel selection fence.
   - Risk: High — model visibility and routing regressions.

10. **Attach and release the request-scoped lease** (Files:
    `controller/relay.go`, `relay/common/relay_info.go`,
    `service/commercial_delivery.go`,
    `controller/relay_commercial_account_pool_test.go`)
    - Action: In private commercial relay selection, acquire one pool lease
      before channel setup and store only an opaque handle. Release it on setup
      failure, cancellation, compact completion, JSON completion, SSE terminal
      completion, and persistence failure. Ensure release is owner/epoch checked
      and idempotent; do not release another request's lease.
    - Why: A leaked lease can starve an account; a double release can violate
      capacity accounting.
    - Dependencies: Steps 8–9; existing response commitment and delivery
      lifecycle.
    - Risk: High — lifecycle ordering and distributed cleanup.

11. **Integrate health admission with pool candidates** (Files:
    `controller/relay.go`, `service/commercial_channel_health.go`,
    `controller/relay_commercial_account_pool_test.go`)
    - Action: Exclude open/quarantined candidates before dispatch and release
      their leases when health admission rejects them. Keep the existing
      channel-specific health keys and sanitized classifications; Redis health
      outage remains fail-closed for the protected commercial path.
    - Why: Pool capacity must not be consumed by an account already known to be
      unhealthy.
    - Dependencies: Steps 8–10; existing health tests.
    - Risk: High — health and lease ownership interact under failure.

12. **Prove the multi-account request path** (Files:
    `controller/relay_commercial_account_pool_test.go`,
    `relay/channel/openai/relay_responses_account_pool_test.go`,
    `relay/channel/openai/relay_responses_compact_account_pool_test.go`,
    `relay/helper/commercial_delivery_test.go`)
    - Action: Test two eligible accounts, deterministic selection, capacity
      exhaustion, six global concurrent requests with FIFO queueing, cancellation
      cleanup, compact/JSON/SSE terminal release, and no provider credential or
      internal account detail in customer responses.
    - Why: This falsifies the core routing and lifecycle behavior before retry
      hardening.
    - Dependencies: Steps 8–11; disposable mock provider only.
    - Risk: High — concurrency and stream cleanup.

**Phase 3 gate:** Requests route through eligible pooled channels, account leases
never exceed capacity or leak, global concurrency remains six, and all response
formats release state exactly once.

### Phase 4: Failure policy, accounting evidence, and operations

13. **Bind pool allocation to attempt/usage evidence** (Files:
    `service/commercial_attempt_usage.go`,
    `model/commercial_attempt_usage.go`,
    `relay/channel/openai/commercial_attempt.go`,
    `service/commercial_account_pool_audit_test.go`)
    - Action: Retain the selected channel ID as the opaque provider-account
      allocation in existing attempt and logical-usage rows; record failed and
      successful candidates without secrets, raw upstream errors, or customer
      headers. Keep wallet reservation/settlement as the only customer billing
      owner.
    - Why: Existing Phase 3 evidence already has the correct channel identity;
      duplicating an account ledger would create conflicting ownership.
    - Dependencies: Phase 3 gate; existing attempt/usage writer.
    - Risk: High — audit and money ordering.

14. **Add bounded pre-commit retry policy behind explicit configuration** (Files:
    `service/commercial_classification.go`, `controller/relay.go`,
    `relay/responses_handler.go`,
    `relay/channel/openai/relay_responses_account_pool_test.go`)
    - Action: Permit only classified retry-safe connection/timeout/429 failures
      before response commitment, within the existing bounded retry budget. On
      every attempt persist evidence, release the prior lease, acquire a new
      eligible lease, and settle wallet billing once by logical request. Keep
      private MVP default failover disabled until provider authorization and
      live proof are complete; never retry after output begins.
    - Why: This preserves the approved no-replay invariant while leaving a
      controlled pool failover path available.
    - Dependencies: Steps 10–13; existing response ordering tests.
    - Risk: Critical — replay and double-accounting risk.

15. **Add redacted operational status and rotation proof** (Files:
    `controller/commercial_provider_account.go`,
    `service/commercial_account_pool.go`,
    `controller/commercial_provider_account_test.go`,
    `docs/contracts/commercial-provider-account-pool.md`)
    - Action: Provide administrator-only redacted status for load, capacity,
      channel/provider label, config version, and coarse health; support disable,
      quarantine, secret-ref rotation, and re-enable without returning raw
      credentials or provider error bodies.
    - Why: Operators need to manage the pool without creating a credential
      disclosure surface.
    - Dependencies: Phase 3 gate; existing admin audit.
    - Risk: High — operational authorization and redaction.

16. **Run the account-pool proof and update handoff evidence** (Files:
    `deploy/mvp/verify-gateway.sh`,
    `docs/aegis/work/2026-08-10-commercial-mvp-phase1/`,
    `docs/migrations/2026-08-25-commercial-provider-account-pool.md`)
    - Action: Add a disposable mock-provider proof for two accounts, Redis
      outage fail-closed behavior, capacity/queue behavior, pre-commit retry,
      post-commit no-replay, wallet settlement idempotency, and secret scans.
      Record exact commands and output; do not use live provider credentials.
    - Why: A reproducible proof is required before any external provider gate.
    - Dependencies: Steps 13–15; all affected package tests.
    - Risk: High — release evidence and security regression.

**Phase 4 gate:** Pool routing, evidence, bounded failure policy, redacted admin
operations, and disposable proof pass. Live provider authorization and funded
proof remain explicitly unresolved external gates.

## Testing Strategy

- **Unit:** pool validation, candidate filtering, deterministic selection,
  bounded arithmetic, failure classification, lease state transitions, and
  idempotent release.
- **PostgreSQL integration:** channel binding, foreign keys, checks, migration
  ownership, compatibility reads, and restart/rollback guard behavior.
- **Redis integration:** atomic capacity acquisition, renewal, owner/epoch
  fencing, queue interaction, cancellation cleanup, outage fail-closed behavior,
  and concurrent selection across gateway instances.
- **Relay integration:** Responses JSON, compact JSON, and SSE success/failure;
  response commitment ordering; no replay after output; attempt/usage evidence;
  wallet settlement exactly once.
- **Authorization/security:** administrator-only provisioning and status,
  customer tenant isolation, secret-reference redaction, forbidden customer
  destination/credential overrides, and sanitized provider errors.
- **Proof harness:** disposable PostgreSQL/Redis/mock provider only; no live
  provider, payment, deployment, push, or launch activation.

## Success Criteria

- [ ] Approved pool contract and PostgreSQL migration contract are documented.
- [ ] Each pool entry is linked to exactly one New API commercial channel.
- [ ] Raw provider credentials never enter the database, customer response, or
      logs.
- [ ] Two or more authorized entries can be provisioned and administrated.
- [ ] Candidate selection respects model/group eligibility, health, capacity,
      weight, and stable tie-breaking.
- [ ] Six global requests run concurrently; additional requests use the existing
      FIFO queue and timeout contract.
- [ ] Redis/epoch failure fails closed without local capacity fallback.
- [ ] Leases renew and release exactly once on every terminal path.
- [ ] Attempt/usage evidence and wallet billing remain idempotent and tenant
      isolated.
- [ ] Pre-commit retry is bounded and never replays a committed response.
- [ ] JSON, compact, and SSE paths never expose provider/account internals.
- [ ] Disposable proof and affected package/contract tests pass.
- [ ] Provider terms, endpoint/model mapping, secret reference, and small funded
      balance are separately verified before live resale/proxy testing.
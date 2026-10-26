# Implementation Plan: Commercial Signup, Wallet, and PAYG

## Overview

This plan implements the approved thin New API commercial adapter. New API
remains the customer-facing gateway and owns users, sessions, native wallet
state, top-ups, Checkout, Portal, and routing. The fork adds only wallet-backed
commercial admission, atomic PAYG reservation/settlement, durable Stripe
idempotency, and the tests needed to prove the existing security and response
commitment invariants.

The plan integrates with the current dirty worktree. Existing staged,
unstaged, and untracked files remain untouched unless explicitly listed below;
unrelated files are never staged. No live payment activation, deployment,
push, launch, crypto payment, or failover work is included.

## Requirements

- Enable New API native free self-registration without manually provisioning users.
- Do not issue the legacy unlimited token automatically in commercial mode.
- Reuse native wallet, top-up, Stripe Checkout, Customer Portal, and account code.
- Keep the existing secure commercial gateway-key, access, Redis concurrency,
  response commitment, audit, and outbound-security owners.
- Add explicit wallet PAYG with atomic reservation, settlement, and refund.
- Add durable Stripe event deduplication and immutable versioned pricing.
- Preserve subscription billing as a separate mode with no automatic overage
  fallback in the initial release.
- Prove registration, top-up, insufficient balance, duplicate webhook, refund,
  tenant isolation, concurrency, delivery uncertainty, and price-version history.

## Architecture Changes

- `router/private_mvp.go` and `router/api-router.go`: expose the native
  registration, wallet, Checkout, Portal, and required account routes while
  retaining direct-authentication and private release restrictions.
- `controller/user.go`: make commercial registration self-service while
  suppressing automatic legacy unlimited-token creation.
- `model/topup.go`, `controller/topup.go`, and `controller/topup_stripe.go`:
  reuse native wallet credits and Checkout, with commercial event/idempotency
  guards around the existing balance owner.
- `model/commercial_wallet_payg.go` and its migration/contract tests: own the
  wallet reservation, price-version, adjustment, and Stripe inbox records.
- `service/commercial_wallet_payg.go`, `service/funding_source.go`, and
  `service/billing_session.go`: implement atomic wallet funding and connect it
  to the existing relay billing lifecycle.
- `service/commercial_billing.go`, `controller/relay.go`,
  `relay/channel/openai/relay_responses.go`, and
  `relay/channel/openai/relay_responses_compact.go`: select wallet PAYG where
  explicitly eligible and settle before the response commitment fence.
- `docs/contracts/customer-api.openapi.yaml`,
  `docs/contracts/customer-api.schemas.yaml`,
  `docs/contracts/stripe-events.md`, and
  `docs/migrations/2026-08-21-commercial-wallet-payg.md`: freeze the external
  route/event contracts and PostgreSQL forward/rollback behavior before code.
- `web/src/routes/(auth)/register.tsx`, `web/src/routes/_authenticated/wallet/index.tsx`,
  and `web/src/features/wallet/*`: keep the native signup/top-up journey usable
  and expose only server-authorized wallet/price data; do not add a second
  billing UI.

## Implementation Steps

### Phase 1: Contract and migration gates — minimum safe foundation

1. **Freeze the revised customer API contract** (Files:
   `docs/contracts/customer-api.openapi.yaml`,
   `docs/contracts/customer-api.schemas.yaml`,
   `docs/contracts/commercial-signup-wallet-payg.openapi.yaml`)
   - Action: Document native registration, authenticated wallet balance/top-up,
     Checkout/Portal, commercial key, Responses/compact, bounded PAYG errors,
     and the rule that provider/internal billing details are never returned.
   - Why: Endpoint work cannot begin until the public method/path/status/header
     behavior is unambiguous.
   - Dependencies: Approved design; none.
   - Risk: High — auth and money-facing contracts are externally observable.

2. **Freeze the Stripe event contract** (Files:
   `docs/contracts/stripe-events.md`,
   `docs/contracts/commercial-wallet-payg-events.md`)
   - Action: Specify signed bounded-body verification, supported top-up success
     and refund events, account/mode/customer/Price binding, duplicate handling,
     terminal effect states, and sanitized responses/logging.
   - Why: Stripe retries and out-of-order delivery must have one deterministic
     effect before the inbox is implemented.
   - Dependencies: Step 1.
   - Risk: High — incorrect event semantics can duplicate money or access.

3. **Write the PostgreSQL migration contract** (File:
   `docs/migrations/2026-08-21-commercial-wallet-payg.md`)
   - Action: Define forward/rollback SQL and compatibility order for immutable
     price versions, wallet reservations, adjustment references, Stripe event
     inbox, indexes, ownership constraints, and retention/audit fields. Reuse
     the native wallet balance owner; do not create a second balance table.
   - Why: Reservation and webhook correctness depend on transaction boundaries,
     uniqueness, and tenant ownership being reviewed before schema code.
   - Dependencies: Steps 1–2; database migration review.
   - Risk: High — schema mistakes affect durable balances and rollback safety.

4. **Add deterministic RED characterization tests** (Files:
   `controller/user_commercial_registration_test.go`,
   `model/commercial_wallet_payg_contract_test.go`,
   `service/commercial_wallet_payg_test.go`,
   `controller/stripe_wallet_webhook_test.go`)
   - Action: Capture the current failures for legacy-token suppression, native
     route exposure, reservation state transitions, duplicate events, refund,
     tenant mismatch, insufficient balance, and concurrent debit attempts.
   - Why: TDD proves each new invariant is real and prevents tests from merely
     describing the implementation after it exists.
   - Dependencies: Steps 1–3; invoke the API-contract and data-migration gates
     before implementation.
   - Risk: Medium — fixtures must remain PostgreSQL-compatible and deterministic.

**Phase 1 gate:** API/event contracts and migration forward/rollback review are
approved; RED tests fail for the intended missing behavior and do not modify
unrelated files.

### Phase 2: Signup, key, and native wallet top-up — complete happy path

5. **Enable self-registration in the commercial route policy** (Files:
   `router/private_mvp.go`, `router/api-router.go`,
   `router/private_mvp_access_routes_test.go`)
   - Action: Allow native registration, authenticated wallet balance/top-up,
     Checkout, Portal, and required account routes through the private release
     guard. Preserve rate limits, body limits, Turnstile/email verification,
     session-origin, CSRF, and tenant checks.
   - Why: Users must create accounts and fund them without manual provisioning,
     while the restricted release surface remains explicit.
   - Dependencies: Phase 1 gate.
   - Risk: High — route ordering or guard widening could expose unrelated New API
     surfaces.

6. **Suppress the legacy unlimited default token for commercial registration**
   (Files: `controller/user.go`, `common/init.go`,
   `controller/user_commercial_registration_test.go`)
   - Action: Keep native account creation and normal session behavior, but make
     commercial mode skip `GenerateDefaultToken`-style unlimited-token issuance.
     Prove a registered user can later create only the secure commercial gateway
     key through the existing one-time display flow.
   - Why: Native registration should not grant an accidental quota bypass.
   - Dependencies: Step 5; existing commercial key verifier path.
   - Risk: High — token issuance is an authentication boundary.

7. **Expose the native wallet surface without creating a second balance owner**
   (Files: `controller/topup.go`, `controller/topup_stripe.go`, `model/topup.go`,
   `service/billing_session.go`, `web/src/features/wallet/*`,
   `web/src/routes/_authenticated/wallet/index.tsx`)
   - Action: Reuse native wallet balance/history handlers and preserve the
     native Checkout/UI redirect shape. Keep commercial credit selection
     disabled with a deterministic configuration error until the immutable
     price-version catalog is installed in Phase 3; no unversioned credit may
     be issued during this phase.
   - Why: This provides the customer-visible top-up flow without duplicating
     New API billing UI or balance ownership.
   - Dependencies: Steps 1–3. The price-version catalog and commercial Checkout
     activation are explicitly deferred to Steps 9–10 and 15–16.
   - Risk: High — price-to-credit mismatches can create financial loss.

8. **Verify the signup-to-wallet journey** (Files:
   `controller/user_commercial_registration_test.go`,
   `controller/topup_commercial_test.go`,
   `web/src/features/wallet/hooks/use-payment.test.ts`,
   `web/src/features/wallet/lib/payment.test.ts`)
   - Action: Test free registration, no unlimited token, commercial-key creation,
     tenant-scoped wallet view, deterministic pre-catalog Checkout rejection,
     and no browser-visible secret/provider data.
   - Why: The happy path is valuable only if account, key, and wallet ownership
     remain bound to the same user.
   - Dependencies: Steps 5–7.
   - Risk: Medium — frontend tests must not rely on live Stripe or provider calls.

**Phase 2 gate:** A test user can register, authenticate, create a commercial
key, and view only its wallet. Commercial Checkout remains closed until the
versioned price catalog exists; the legacy unlimited token is absent.

### Phase 3: Wallet PAYG request path — atomic happy path

9. **Add wallet PAYG durable models and migration** (Files:
   `model/commercial_wallet_payg.go`,
   `model/commercial_wallet_payg_migration.go`,
   `model/main.go`,
   `model/commercial_wallet_payg_postgres_test.go`)
   - Action: Add price-version, wallet-reservation, adjustment-reference, and
     event-inbox models with tenant/user ownership, bounded integer micro-unit
     amounts, unique gateway request IDs, unique Stripe event IDs, and terminal
     states `pending`, `committed`, `refunded`, or `delivery_uncertain` where
     applicable. Register forward and compatibility migration paths.
   - Why: The wallet balance remains native, while the adapter needs durable
     idempotency and a history of every commercial charge.
   - Dependencies: Phase 1 migration contract; no code until data-migration
     review accepts transaction/index/rollback behavior.
   - Risk: High — persistent money state and uniqueness constraints.

10. **Implement immutable price-version selection and bounded charge math**
    (Files: `service/commercial_price.go`,
    `service/commercial_price_test.go`,
    `model/commercial_wallet_payg.go`)
    - Action: Validate integer rates and limits, select one active price version
      for a request, compute a bounded maximum reservation from validated input
      and output limits, and retain the selected version on every reservation.
      Reject overflow, negative values, unknown aliases, and unknown Stripe
      Price IDs.
    - Why: Reservation must be safe before upstream usage is known, and old
      charges must not change when prices are edited.
    - Dependencies: Step 9 and the API/event contracts.
    - Risk: High — arithmetic and pricing errors directly affect balances.

11. **Implement atomic wallet reservation, settlement, and refund** (Files:
    `service/commercial_wallet_payg.go`,
    `model/commercial_wallet_payg.go`,
    `service/commercial_wallet_payg_test.go`)
    - Action: Add one-transaction compare-and-set operations that reserve only
      available balance, settle to actual bounded usage, release unused funds,
      refund only a matching pending reservation, and make duplicate request IDs
      return the original terminal result without a second debit.
    - Why: Concurrent requests must never overdraw a wallet or double-settle it.
    - Dependencies: Steps 9–10; PostgreSQL migration applied in test fixtures.
    - Risk: High — transaction isolation and retry behavior are money-critical.

12. **Add wallet funding to the existing BillingSession lifecycle** (Files:
    `service/funding_source.go`, `service/billing_session.go`,
    `service/commercial_billing.go`,
    `service/commercial_wallet_payg_test.go`)
    - Action: Add an explicit wallet funding implementation selected only for
      wallet PAYG requests. Keep subscription funding unchanged; remove any
      implicit wallet/subscription fallback for this path. Expose commit,
      settle, refund, and delivery-uncertainty state through the existing
      session interfaces.
    - Why: One billing lifecycle must own Redis admission, reservation, response
      fencing, and audit without creating a second relay path.
    - Dependencies: Steps 10–11; existing commercial subscription reservation
      and delivery tests must remain green.
    - Risk: High — a factory-selection bug could bypass quota or charge twice.

13. **Integrate PAYG with Responses and compact relay commitment** (Files:
    `controller/relay.go`, `relay/responses_handler.go`,
    `relay/channel/openai/relay_responses.go`,
    `relay/channel/openai/relay_responses_compact.go`,
    `relay/common/relay_info.go`)
    - Action: Select wallet mode only after key/access/model checks and Redis
      lease admission; reserve before upstream; parse bounded usage; settle
      before the first customer-visible byte; refund pre-fence failures; retain
      post-fence delivery uncertainty. Preserve one-channel/no-retry behavior.
    - Why: The monetary boundary must be the same response commitment boundary
      already proven for subscription traffic.
    - Dependencies: Steps 11–12; existing Phase 2/3 commitment tests.
    - Risk: High — ordering mistakes can expose free usage or charge twice.

14. **Prove the PAYG request happy path** (Files:
    `service/commercial_wallet_payg_integration_test.go`,
    `relay/channel/openai/relay_responses_wallet_test.go`,
    `relay/channel/openai/relay_responses_compact_wallet_test.go`)
    - Action: Test sufficient balance, insufficient balance with zero upstream
      attempts, actual-usage settlement, unused-reservation release, and one
      gateway-generated request ID across retries/repeated completion callbacks.
    - Why: These tests falsify the core customer value path before edge-case
      hardening.
    - Dependencies: Steps 11–13; explicit mock transfer station only.
    - Risk: High — integration fixtures must prove database and upstream effects.

**Phase 3 gate:** Wallet PAYG requests reserve and settle atomically, cannot
overdraw under concurrency, and cross the existing response fence exactly once.
Subscription requests and unrelated native routes remain behaviorally unchanged.

### Phase 4: Stripe idempotency, refunds, and security hardening

15. **Add durable Stripe inbox processing** (Files:
    `controller/topup_stripe.go`,
    `model/commercial_wallet_payg.go`,
    `service/commercial_wallet_payg.go`,
    `controller/stripe_wallet_webhook_test.go`)
    - Action: Verify bounded raw bodies and signatures, bind events to the
      configured account/mode/customer/Price, insert-or-replay by event ID, and
      apply top-up credit or refund adjustment in one transaction. Persist
      processed/rejected effect state without raw payloads or signatures.
    - Why: Stripe delivery is at-least-once and may be duplicated or reordered.
    - Dependencies: Steps 2, 9–11; approved Stripe event contract.
    - Risk: High — webhook mistakes can duplicate credits or miss refunds.

16. **Make Checkout intents idempotent** (Files:
    `controller/topup_stripe.go`, `model/commercial_wallet_payg.go`,
    `service/billing_session.go`,
    `controller/topup_commercial_test.go`)
    - Action: Require an authenticated purchase idempotency key, persist its
      normalized fingerprint and server command ID, reuse the original Checkout
      session on exact retry, and reject key reuse with a different Price or
      amount.
    - Why: Browser reloads and lost responses must not create multiple paid
      sessions for one intent.
    - Dependencies: Steps 2, 9, 15.
    - Risk: High — idempotency keys are part of the payment contract.

17. **Add adversarial tenant, refund, and concurrency tests** (Files:
    `model/commercial_wallet_payg_postgres_test.go`,
    `service/commercial_wallet_payg_test.go`,
    `controller/stripe_wallet_webhook_test.go`,
    `service/commercial_concurrency_test.go`)
    - Action: Test cross-tenant reads/reservations/refunds, duplicate and
      concurrent webhooks, verified refunds, stale price versions, PostgreSQL
      contention, Redis cap enforcement, pre-fence refund, post-fence consumed
      delivery uncertainty, and sanitized errors/logs.
    - Why: These are the accepted money, isolation, and commitment failure modes.
    - Dependencies: Steps 11–16.
    - Risk: High — tests must use real PostgreSQL/Redis fixtures where the
      invariant depends on database or distributed atomicity.

18. **Verify browser-facing wallet and registration behavior** (Files:
    `web/src/routes/(auth)/register.tsx`,
    `web/src/routes/_authenticated/wallet/index.tsx`,
    `web/src/features/wallet/components/recharge-form-card.tsx`,
    `web/src/features/wallet/hooks/use-payment.test.ts`)
    - Action: Ensure registration and wallet pages use server-authorized data,
      display safe balance/Checkout states, never embed Stripe/provider secrets,
      and cannot select another tenant's wallet or Price mapping.
    - Why: UI must not become an alternate authorization or billing owner.
    - Dependencies: Steps 5–8 and 15–17.
    - Risk: Medium — browser tests must cover unauthorized and stale-session states.

**Phase 4 gate:** Stripe replay, duplicate Checkout intent, refund, tenant
isolation, concurrent debit, and commitment failure tests pass with no sensitive
data leakage.

### Phase 5: Sandbox integration and release evidence

19. **Add the wallet/PAYG Compose proof harness** (Files:
    `deploy/mvp/compose.yaml`, `deploy/mvp/.env.example`,
    `deploy/mvp/verify-gateway.sh`, `deploy/mvp/verify-compose.sh`,
    `integration/mvp/wallet_payg_test.go`)
    - Action: Extend the existing disposable PostgreSQL/Redis/mock-channel stack
      with deterministic price, wallet, Stripe-event, and transfer-station
      fixtures. Keep credentials as secret references and keep the mock egress
      exception test-only.
    - Why: Local evidence must exercise the real service boundaries before any
      external sandbox credential is used.
    - Dependencies: Phase 4 gate; WSL/Docker availability.
    - Risk: High — harness shortcuts must not claim production behavior.

20. **Run focused, race, migration, and contract verification** (Files:
    `docs/aegis/work/2026-08-10-commercial-mvp-phase1/20-checkpoint.md`,
    `docs/aegis/work/2026-08-10-commercial-mvp-phase1/90-evidence.md`)
    - Action: Run affected Go tests, PostgreSQL migration tests, `go test -race`
      for wallet/concurrency packages, frontend tests/build, contract lint,
      secret scan, and the Compose sandbox proof. Record exact commands and
      outputs without staging unrelated evidence/cache artifacts.
    - Why: Completion claims require fresh evidence at the relevant phase gate.
    - Dependencies: Step 19; all previous gates green.
    - Risk: Medium — WSL or external infrastructure gaps remain explicit evidence
      gaps rather than being treated as passes.

21. **Run the external sandbox journey** (Files:
    `deploy/mvp/.env.example`, `deploy/mvp/README.md`,
    `docs/aegis/work/2026-08-10-commercial-mvp-phase1/20-checkpoint.md`)
    - Action: Inject sandbox Stripe and CodexEverywhere-compatible credentials
      through the approved secret mechanism, execute registration → Checkout →
      webhook → wallet PAYG → streamed Responses, and retain sanitized evidence.
    - Why: This validates integration with the selected transfer station without
      funding or activating production payments.
    - Dependencies: Step 20; credentials, sandbox account, and written
      resale/proxy permission available externally.
    - Risk: High — external terms and credentials are release inputs, not guesses.

22. **Prepare the small funded test only after explicit live-test approval**
    (Files: `deploy/mvp/README.md`, `docs/aegis/work/2026-08-10-commercial-mvp-phase1/20-checkpoint.md`)
    - Action: Document the exact balance, price version, spend cap, rollback,
      and stop conditions for one small CodexEverywhere-funded test. Do not run
      it, activate live Stripe, deploy, invite customers, or push without a
      separate explicit approval.
    - Why: A funded supplier test is an external financial and terms boundary.
    - Dependencies: Step 21 and written provider resale/proxy permission.
    - Risk: High — real money and external service state.

**Phase 5 gate:** All applicable local proofs are fresh and green; sandbox
journey evidence is retained; any WSL/provider/Stripe limitation is reported as
an evidence gap; no live activation or launch is implied.

## Testing Strategy

- Unit: price validation/overflow, reservation state machine, wallet funding
  selection, registration token policy, error sanitization, and webhook event
  classification.
- PostgreSQL integration: row ownership, unique request/event IDs, atomic
  reserve/settle/refund, stale price versions, rollback/reapply, and concurrent
  contention.
- Redis integration: exact concurrency cap, fail-closed limiter behavior, lease
  release/expiry, and wallet requests sharing the existing entitlement lease.
- Relay integration: compact JSON and SSE commitment ordering, pre-fence refund,
  post-fence consumed delivery uncertainty, no replay, and usage accounting.
- Frontend: registration, wallet balance/top-up, Checkout retry, tenant scoping,
  stale-session handling, and absence of browser-visible secrets.
- E2E/sandbox: registration → commercial key → top-up → webhook → wallet PAYG
  streamed Codex-compatible request through the single mock/sandbox channel.
- Release verification: affected package tests, race tests, frontend build,
  contract/migration tests, Compose proof, secret scan, and retained evidence.

## Success Criteria

- [ ] Free native registration succeeds with existing abuse protections.
- [ ] Commercial registration does not issue a legacy unlimited token.
- [ ] Users can create and use the existing secure commercial gateway key.
- [ ] Native Stripe Checkout credits the correct wallet exactly once.
- [ ] Duplicate or reordered webhook delivery cannot duplicate credit/access.
- [ ] Verified refunds create exactly one compensating wallet adjustment.
- [ ] Insufficient balance prevents any upstream attempt.
- [ ] Concurrent requests cannot overdraw a wallet or exceed the Redis cap.
- [ ] PAYG settlement occurs before the first customer-visible response byte.
- [ ] Pre-commit failures refund; post-commit uncertainty remains consumed.
- [ ] Historical reservations retain their original immutable price version.
- [ ] Tenant isolation and sensitive-data non-disclosure tests pass.
- [ ] Compose and sandbox proofs run with secret references and no live activation.

## Handoff and safety rules

- Preserve the current dirty worktree, including all staged, unstaged, and
  untracked files. Only files named in an approved step may be edited.
- Do not access or modify `C:\Users\z\Documents\Proxy Server`.
- Do not reset, delete, push, deploy, or stage unrelated files.
- Because this linked worktree's Git metadata resides under the protected path,
  do not commit until a separate safe metadata procedure is explicitly approved.
- Stop only the affected step when an external credential, provider permission,
  database review, or WSL proof is unavailable; continue independent local work.

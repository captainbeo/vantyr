# Implementation Plan: Native Stripe Subscription Manual Renewal

## Overview

Implement the approved private-MVP Stripe path by exposing New API's native
subscription plans, self-status, and Stripe pay route through private mode. A
purchase covers one billing period only: after Checkout is created, the Stripe
subscription is marked `cancel_at_period_end=true`; customers must purchase
again for a later period. The existing New API order/webhook flow remains the
billing owner, while a narrow bridge makes the completed native subscription
visible to the existing commercial access projection.

## Requirements

- Keep the private MVP invite-only/admin-provisioned; do not add public signup.
- Reuse native `SubscriptionPlan`, `SubscriptionOrder`, `UserSubscription`,
  Checkout, and Stripe webhook handling.
- Expose only `/api/subscription/plans`, `/api/subscription/self`, and
  `/api/subscription/stripe/pay` in private mode, plus the existing webhook.
- Ensure a successful purchase is cancelled at period end and never
  auto-renews.
- Bind Stripe customer, Checkout/order, subscription, plan, and period to the
  authenticated New API user before activating commercial access.
- Preserve tenant isolation, sanitized errors, and no raw Stripe signature or
  payload logging.
- Keep the existing commercial access, quota, Redis, audit, and relay controls
  unchanged except for the subscription activation bridge.

## Architecture Changes

- `docs/contracts/customer-api.openapi.yaml`: replace the custom Checkout and
  Portal operations with the native pay request/response contract.
- `docs/contracts/customer-api.schemas.yaml`: define the native plan/pay/status
  schemas and remove the Portal-only contract.
- `docs/contracts/stripe-events.md`: make native Checkout/order/webhook behavior
  normative; remove the custom inbox/Portal/recurring-event requirements from
  this private-MVP slice.
- `router/private_mvp.go`: allow the three native subscription routes and the
  existing Stripe webhook only in the intended private-mode path.
- `controller/subscription_payment_stripe.go`, `controller/topup_stripe.go`,
  `model/subscription.go`, and the existing commercial projection owner: add
  the smallest post-Checkout cancellation and projection bridge needed to
  enforce one-period access.

## Implementation Steps

### Phase 1: Contract alignment — minimum viable

1. **Amend the native Stripe route and event contracts** (Files: `docs/contracts/customer-api.openapi.yaml`, `docs/contracts/customer-api.schemas.yaml`, `docs/contracts/stripe-events.md`, `docs/contracts/contract_test.go`, `docs/contracts/contract_stripe_lint_test.go`)
   - Action: define `POST /api/subscription/stripe/pay` with `{plan_id}` and
     native success/error envelopes; retain native plans/self and webhook;
     remove `/checkout` and `/portal` from the commercial route inventory and
     event frontmatter.
   - Why: implementation must match the approved native-only decision.
   - Dependencies: none.
   - Risk: Medium.

### Phase 2: Private native subscription access — core experience

2. **Expose native subscription routes in private mode** (Files: `router/private_mvp.go`, `router/private_mvp_routes_test.go`)
   - Action: allow authenticated native plans/self/pay routes and the webhook
     while continuing to deny custom Checkout/Portal and unrelated billing
     surfaces.
   - Why: customers need the native New API purchase and status flow without
     widening the private API.
   - Dependencies: Step 1.
   - Risk: Medium.

3. **Add one-period Stripe completion handling** (Files:
   `controller/subscription_payment_stripe.go`, `controller/topup_stripe.go`,
   `model/subscription.go`, commercial projection owner)
   - Action: after native Checkout creation/completion, verify ownership and
     configured plan binding, call Stripe's official subscription update to set
     `cancel_at_period_end=true`, then transactionally activate/project the
     native subscription. Reject activation if cancellation or projection
     fails. Keep webhook completion idempotent through the native order lock.
   - Why: native Checkout otherwise creates an auto-renewing subscription and
     commercial authorization requires the projection.
   - Dependencies: Steps 1–2.
   - Risk: High.

4. **Remove Stripe secret/payload logging** (File: `controller/topup_stripe.go`)
   - Action: retain only sanitized event/order identifiers, type, and status in
     logs; never log `Stripe-Signature` or raw payload bytes.
   - Why: required security invariant.
   - Dependencies: Step 3.
   - Risk: Medium.

### Phase 3: Edge cases and regression proof

5. **Add focused native lifecycle tests** (Files: new tests beside the changed
   controller/model/router files)
   - Action: cover Checkout/order creation, cancellation-at-period-end,
     successful activation, expiry, manual second purchase, no automatic
     renewal, cross-customer binding rejection, idempotent webhook replay, and
     absence of raw Stripe data in logs.
   - Why: prove money, access, and tenant invariants at their owning boundary.
   - Dependencies: Steps 3–4.
   - Risk: High.

## Testing Strategy

- Contract: `go test ./docs/contracts` and the Stripe contract lint tests.
- Unit: native subscription/order helpers and Stripe request validation.
- Integration: PostgreSQL-backed completion/projection and webhook replay.
- Router: private-mode route inventory and denied custom billing routes.
- Security: log-capture assertions for signatures/payloads and
  cross-customer binding.
- External evidence gap: live Stripe API and live webhook delivery remain
  unavailable until deployment credentials and payment activation are approved.

## Success Criteria

- [ ] Contract tests describe only the approved native pay route, native plans/self, and webhook.
- [ ] Private mode exposes the native subscription flow and denies custom Portal/Checkout routes.
- [ ] Every completed purchase is set to cancel at period end before access activation.
- [ ] Native subscription state is projected to commercial access atomically and tenant-safely.
- [ ] A later purchase is manual; no renewal worker or recurring invoice path is added.
- [ ] Focused tests pass, with no raw Stripe signature or payload leakage.

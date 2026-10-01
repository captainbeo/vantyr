# Stripe Subscription Lifecycle Design

**Status:** Approved for implementation planning; scope amended 2026-08-29
**Date:** 2026-08-28
**Scope:** Phase 4 Stripe subscription lifecycle for the thin New API commercial fork

## Goal

Complete the one-period subscription purchase path for the two enabled commercial
plans while keeping New API's native Stripe integration as the payment engine.
Each purchase must end after its paid period; the customer must explicitly buy a
new period. The gateway derives access and quota from durable, tenant-bound
PostgreSQL state; browser state and Checkout completion alone must never grant
access or quota.

This work does not change wallet PAYG settlement, provider-account pooling, image
entitlements, crypto payment, failover, live payment activation, deployment, or
customer invitations.

## Existing owners and additions

- New API remains the owner of users, sessions, native `SubscriptionPlan`,
  `SubscriptionOrder`, `UserSubscription`, Stripe Checkout creation, native
  webhook dispatch, and the inherited billing UI.
- PostgreSQL remains the source of truth for billing commands, Stripe event
  inbox state, native subscription binding, commercial plan versions, billing
  periods, access projections, quota state, and audit entries.
- Redis and the existing gateway admission/commitment path remain unchanged.
- Stripe remains the source of truth for the initial payment and period boundary.
  The native Checkout-created subscription is immediately updated through the
  official Stripe SDK with `cancel_at_period_end=true`, so Stripe does not charge
  a later period.
- New code is limited to the native completion bridge that performs the
  period-end cancellation and creates/updates the existing commercial access
  projection, private route exposure, and focused regression tests. No separate
  Stripe billing engine, custom Portal, recurring invoice processor, or wallet
  event path is added.

## Customer API contract

### Existing native `POST /api/subscription/stripe/pay`

Authenticated dashboard bearer only. The request uses New API's native `plan_id`
and native plan/Price configuration. Private mode exposes only the two enabled
commercial plans; browser input cannot supply a Stripe Price ID, amount, currency,
customer ID, or redirect destination. The native handler creates a pending
`SubscriptionOrder` and a Stripe Checkout session.

The response is the native Stripe-hosted Checkout URL. The existing native
idempotency behavior remains an explicit limitation of this native-only scope;
the customer must not rely on a retried request being the same Checkout session.

## Webhook lifecycle

The existing `/api/stripe/webhook` route remains the only event ingress. The native
handler remains responsible for bounded request handling, signature verification,
and dispatch:

1. Read at most 1 MiB of raw bytes.
2. Verify `Stripe-Signature` over the exact bytes with the configured endpoint
   secret and signed timestamp (1-300 second tolerance; default 300).
3. Parse and validate the event only after signature verification.
4. Dispatch the native Checkout completion/expiry/async-payment behavior.

The native subscription purchase path uses these events:

- `checkout.session.completed`: native `CompleteSubscriptionOrder` creates one
  local `UserSubscription`; the completion bridge verifies the returned Stripe
  subscription belongs to the order's customer and immediately updates it with
  `cancel_at_period_end=true`. Only after that succeeds is the commercial access
  projection linked to the local subscription and paid period.
- `checkout.session.expired`: native code expires the pending order; it grants no
  access or quota.
- `checkout.session.async_payment_succeeded`: native code completes the same
  order and applies the same period-end cancellation bridge.
- `checkout.session.async_payment_failed`: native code marks the pending order
  failed; it grants no access or quota.

Recurring `invoice.paid`, `invoice.payment_failed`, and later subscription update
events are intentionally outside this native-only manual-renewal path. Because
the Stripe subscription is canceled at the period end, no later period should be
charged. The local native expiry task is the access cutoff; a customer must call
the native purchase route again for the next period.

Unsupported event types retain New API's existing ignore behavior. A missing
subscription ID or failed period-end cancellation fails the completion bridge
closed: the local order is not treated as a commercially active entitlement and
Stripe is allowed to retry the webhook. No synthetic subscription or quota grant
is created.

## Transaction and state rules

The native completion transaction owns the order and local subscription. The
commercial bridge then uses one PostgreSQL transaction for the existing access
projection, billing period, quota reset, and sanitized audit entry:

- native subscription order and Stripe customer/subscription binding;
- immutable commercial plan-version selection;
- one `CommercialBillingPeriod` keyed by Stripe subscription plus period bounds;
- native subscription status and period/quota reset fields;
- commercial access projection status and expiry;
- exactly one quota grant/reset for this one paid billing-period ID;
- one append-only sanitized audit entry.

The bridge is idempotent on the native `SubscriptionOrder.TradeNo` and local
subscription ID. Replayed completion events cannot create a second local
subscription or second commercial period for the same order. All tenant checks
compare the authenticated platform customer with both the Stripe customer and
native subscription owner.

The current inherited Stripe controller's raw signature/payload logging is removed
for this path. Logs and audit details contain only event ID, sanitized event type,
mode, internal command/subscription/period references, transition class, and
processing result. They never contain signatures, raw payloads, payment data,
provider secrets, customer gateway keys, prompts, responses, or internal URLs.

## Error and access behavior

- Native invalid signature/body handling remains authoritative.
- Missing or mismatched Stripe subscription/customer binding, failed
  `cancel_at_period_end` update, or failed commercial projection transaction keeps
  the entitlement inactive and returns a retryable webhook failure where the
  native handler can do so; no access or quota mutation is accepted as success.
- Native local expiry rejects the next request after the paid period; an already
  committed stream may finish under its admission snapshot.

## Verification requirements

Focused tests must prove:

- Native plan selection, Checkout creation, pending order, and completion.
- The completion bridge sets `cancel_at_period_end` and rejects missing or
  cross-customer subscription IDs.
- One local subscription/access projection/billing period is created, quota is
  granted once, and the local subscription expires at period end.
- A second manual purchase creates the next period; no automatic renewal or
  second-period quota grant occurs.
- Native expiry and delayed-payment failure grant no access or quota.
- No raw Stripe signature or payload appears in logs, errors, audit rows, or
  customer responses.

Verification runs in disposable Docker PostgreSQL/Go environments using focused
tests first, then the Phase 4 billing/security/database/compliance gate. No live
Stripe credentials or payment activation are required for the local gate.

# Implementation Plan: Commercial Phase 3.5 Attempt and Usage Writer

## Overview

Implement the approved narrow durable writer for the existing
`channel_attempts` and `logical_request_usages` tables. The slice covers only
private commercial Responses and compact requests on the single configured
channel; native subscription reservation/settlement remains the quota owner.

## Requirements

- Insert one pending attempt before `DoRequest`; dispatch is refused if it fails.
- Finalize one immutable attempt and one immutable logical-usage row atomically.
- Make exact terminal retries idempotent and divergent retries fail closed.
- Keep `response.completed` behind successful terminal persistence.
- Preserve consumed/no-replay semantics after commitment or earlier output.
- Store only bounded identifiers, aliases, timestamps, meters, classifications,
  integer cost evidence, and delivery state; never secrets or payload content.

## Architecture Changes

- `model/commercial_attempt_usage_writer.go`: persistence contract, validation,
  begin/finalize transactions, duplicate comparison, and sanitized errors.
- `service/commercial_attempt_usage.go`: commercial request snapshot, usage/cost
  projection, lifecycle handle, and durable delivery callbacks.
- `relay/responses_handler.go`: begin the attempt immediately before upstream
  dispatch and finalize non-stream terminal evidence before body copy.
- `relay/channel/openai/relay_responses.go`: finalize SSE terminal evidence
  before releasing `response.completed`; preserve failure/no-replay behavior.
- `relay/channel/openai/relay_responses_compact.go`: finalize before commit/body
  copy and record write outcomes through the durable handle.
- Existing migration owner `model/commercial_attempt_usage.go` is unchanged.

## Implementation Steps

### Phase 1: Persistence contract — minimum viable

1. **Add writer inputs/results and bounded validation** (File:
   `model/commercial_attempt_usage_writer.go`)
   - Action: Define immutable identity, terminal evidence, logical-usage, and
     delivery snapshots; validate request IDs, aliases, classifications, IDs,
     meters, timestamps, and integer costs before SQL.
   - Why: Keep persistence independent of relay internals and prevent sensitive
     or unbounded values from reaching the database.
   - Dependencies: Approved migration/model slice.
   - Risk: High.

2. **Implement begin and finalize transactions** (File:
   `model/commercial_attempt_usage_writer.go`)
   - Action: Insert-or-compare the pending `(request_id, attempt_index=0)` row;
     lock it with `FOR UPDATE`, transition it once, insert the reservation-bound
     logical row, and return exact duplicates without mutation.
   - Why: Enforce one upstream observation and one immutable usage result.
   - Dependencies: Step 1.
   - Risk: High.

3. **Add RED then GREEN PostgreSQL writer tests** (Files:
   `model/commercial_attempt_usage_writer_test.go`,
   `model/commercial_attempt_usage_writer_postgres_test.go`)
   - Action: Prove insert-before-dispatch contract fixtures, atomic rollback,
     exact/divergent duplicates, terminal immutability, reservation binding, and
     known token/cost values on disposable PostgreSQL.
   - Why: Falsify locking, idempotency, and accounting errors at their owner.
   - Dependencies: Steps 1–2.
   - Risk: High.

### Phase 2: Commercial lifecycle adapter — complete happy path

4. **Build a request-scoped lifecycle handle** (File:
   `service/commercial_attempt_usage.go`)
   - Action: Snapshot `RelayInfo` identity after mapping, derive endpoint class,
     channel/model IDs, reservation binding, and bounded cost/usage projections;
     expose begin, terminal, commit-fence, first-write, and delivery callbacks.
   - Why: Keep relay code thin while centralizing redaction and cost conversion.
   - Dependencies: Phase 1.
   - Risk: High.

5. **Add lifecycle and redaction tests** (File:
   `service/commercial_attempt_usage_test.go`)
   - Action: Test Responses/compact eligibility, stable classifications, known
     token/cost fixture, absent-cost failure projection, and rejection of URLs,
     headers, secrets, provider payloads, prompts, responses, and raw errors.
   - Why: Protect the operator-only evidence boundary.
   - Dependencies: Step 4.
   - Risk: High.

6. **Wire begin immediately before upstream dispatch** (File:
   `relay/responses_handler.go`)
   - Action: Invoke the lifecycle begin hook after conversion/mapping and before
     `adaptor.DoRequest`; on failure return a sanitized error without dispatch,
     retry, or reselection, leaving existing pre-fence refund behavior intact.
   - Why: Guarantee no upstream observation exists without a pending row.
   - Dependencies: Steps 4–5.
   - Risk: High.

### Phase 3: Response ordering and failure semantics — edge cases

7. **Finalize JSON/compact evidence before body copy** (File:
   `relay/channel/openai/relay_responses_compact.go`)
   - Action: Finalize terminal attempt/usage after safe response parsing and
     before the commit fence/body copy; route persistence errors through the
     existing sanitized error and consumed/no-replay rules.
   - Why: A customer must never receive a body whose durable evidence failed.
   - Dependencies: Steps 4–6.
   - Risk: High.

8. **Gate SSE terminal delivery on durable finalization** (File:
   `relay/channel/openai/relay_responses.go`)
   - Action: Keep `response.completed` buffered until terminal evidence commits;
     finalize known usage/cost before writing it; record first-write and delivery
     transitions; on post-output failure emit only sanitized `response.failed`.
   - Why: Preserve commitment fencing and prevent replay or duplicate completion.
   - Dependencies: Steps 4–7.
   - Risk: High.

9. **Add relay ordering and no-replay tests** (Files:
   `relay/responses_handler_commercial_attempt_test.go`,
   `relay/channel/openai/relay_responses_commercial_attempt_test.go`)
   - Action: Use fake lifecycle/adaptor boundaries to prove no dispatch before
     begin, one attempt/usage row, completion-after-persistence ordering,
     persistence-failure `response.failed`, delivery uncertainty, and absence of
     provider/internal evidence in customer output.
   - Why: Verify observable behavior at the response boundary, not only helpers.
   - Dependencies: Steps 6–8.
   - Risk: High.

### Phase 4: Gate verification and handoff

10. **Run focused verification and reviews** (Files: touched Go files and
    existing phase evidence ledger)
    - Action: Run focused PostgreSQL/model/service/relay tests, race tests, vet,
      Docker formatting, `git diff --check`, and required database, Go, AI,
      security, and code reviews; update the progress ledger only with fresh
      evidence.
    - Why: Close the Phase 3.5 application-writer gate without claiming broader
      Phase 3 or release completion.
    - Dependencies: Steps 1–9.
    - Risk: High.

## Testing Strategy

- Unit: validation, projection, classification, cost conversion, redaction, and
  duplicate comparison in model/service tests.
- Integration: disposable PostgreSQL transaction, row-lock, rollback, binding,
  and immutable-row tests; Responses/compact relay tests with deterministic fake
  upstream and writer failures.
- E2E boundary: streamed terminal ordering and sanitized failure/no-replay proof
  through the existing commercial mock harness. No live supplier or payment
  activation is part of this plan.

## Open Questions

None for this approved scope. If an implementation needs a new schema column,
provider-specific payload, quota owner, retry path, or customer-facing field,
stop and return to review rather than expanding this plan.

## Success Criteria

- [ ] No upstream call occurs when pending-attempt insertion fails.
- [ ] One request produces one final attempt and one logical-usage row.
- [ ] Exact terminal retries are idempotent; divergent retries fail closed.
- [ ] Known token/cost fixture is exact and bounded.
- [ ] `response.completed` follows terminal persistence for SSE and compact.
- [ ] Post-output persistence failure is consumed, uncertain, sanitized, and not replayed.
- [ ] Focused tests, race, vet, formatting, diff check, and required reviews pass.

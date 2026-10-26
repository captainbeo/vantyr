# Implementation Plan: GPT-5.6 Commercial Model Support

## Overview

Extend the private commercial gateway so an entitled customer can use the
public alias `gpt-5.6` on Responses and Responses compact. Compact requests will
continue to use the existing suffix/mapping pipeline, with the public alias
restored in billing, usage, and customer-visible responses. This is a catalog,
fixture, and regression change; it does not add a router, limiter, wallet, or
Stripe owner.

## Requirements

- Advertise `gpt-5.6` only when an enabled commercial channel and explicit plan
  entitlement both contain that alias.
- Map compact requests through `gpt-5.6-openai-compact` without exposing an
  upstream slug or changing the public response alias.
- Use the same existing versioned customer price as `gpt-5.5`; do not create a
  new price version.
- Reject a key without the entitlement before channel selection or upstream
  observation.
- Preserve existing `gpt-5.4` and `gpt-5.5` behavior and proof coverage.
- Keep provider URLs, credentials, and provider model identifiers in channel
  configuration/fixtures, not core routing logic.

## Architecture Changes

- `service/commercial_mock_channel_seed.go`: allow the deployment fixture to
  advertise a bounded set of configured public aliases per mock channel and
  generate their compact variants/mappings through the existing helper.
- `deploy/mvp/mock-channels.json`: advertise `gpt-5.4`, `gpt-5.5`, and
  `gpt-5.6` (with compact variants) using the existing mock upstream stations.
- `setting/ratio_setting/model_ratio.go`: add the public `gpt-5.6` fallback at
  the same ratio as `gpt-5.5`; compact pricing continues to use the wildcard.
- Existing entitlement, access, response, billing, and proof code remains the
  owner of its current invariant; only its model fixtures/assertions expand.

## Implementation Steps

### Phase 1: RED regressions — Minimum Viable

1. **Add explicit entitlement and discovery failures** (Files:
   `model/commercial_plan_entitlement_test.go`,
   `router/private_mvp_entitlement_test.go`,
   `router/private_mvp_access_routes_test.go`,
   `middleware/commercial_access_enforcement_test.go`)
   - Action: Add `gpt-5.6` to entitled fixtures and assert it is allowed and
     discoverable; add a control fixture with no `gpt-5.6` entitlement and
     assert rejection before the dispatch callback.
   - Why: Locks the authorization contract before implementation and prevents
     model-list checks from becoming a routing bypass.
   - Dependencies: None.
   - Risk: Medium; authorization behavior is high-risk but the change is test
     fixture-only.

2. **Add compact alias and billing RED cases** (Files:
   `relay/common/relay_info_test.go`,
   `relay/channel/openai/relay_responses_public_alias_test.go`,
   `service/commercial_billing_test.go`)
   - Action: Add table cases for public `gpt-5.6`, internal
     `gpt-5.6-openai-compact`, and a mapped upstream slug; assert the public
     alias is retained for usage/billing and never leaks the internal slug.
   - Why: Protects the recently repaired compact public-alias fence for the new
     model.
   - Dependencies: None.
   - Risk: Medium; response and accounting identifiers are security-relevant.

3. **Add mock seed and price RED cases** (Files:
   `service/commercial_mock_channel_seed_test.go`,
   `service/commercial_price_test.go`,
   `controller/model_owned_by_test.go`)
   - Action: Assert all three public aliases and their compact variants are
     emitted by the seed, and assert `gpt-5.6` resolves to the same configured
     customer price behavior as `gpt-5.5`.
   - Why: Makes the missing catalog/configuration behavior deterministic before
     changing production code or deployment fixtures.
   - Dependencies: None.
   - Risk: Low.

### Phase 2: Configuration and smallest implementation — Core Experience

4. **Extend the bounded mock-channel alias schema** (Files:
   `service/commercial_mock_channel_seed.go`,
   `service/commercial_mock_channel_seed_test.go`)
   - Action: Add a bounded `public_model_aliases` configuration path while
     preserving the current single-alias fixture contract where practical.
     Validate aliases with the existing model grammar, require the two mock
     channels to share the same ordered alias set, generate one compact alias
     per public alias, and write configured alias-to-upstream mappings without
     inventing provider names.
   - Why: Both existing aliases and GPT-5.6 must be exercised by the same
     disposable stations; replacing the current alias would regress GPT-5.4.
   - Dependencies: Steps 1–3 (RED tests).
   - Risk: High; channel selection and model mapping are security boundaries.

5. **Update the disposable channel catalog** (Files:
   `deploy/mvp/mock-channels.json`, `deploy/mvp/compose_contract_test.go`)
   - Action: Configure `gpt-5.4`, `gpt-5.5`, and `gpt-5.6` on both mock
     channels, including generated compact variants, and assert the fixture
     contains no customer or provider secret.
   - Why: Gives the immutable gateway proof a real eligible route for the new
     alias while retaining the old aliases.
   - Dependencies: Step 4.
   - Risk: Medium; deployment configuration can change what is publicly
     discoverable.

6. **Add the GPT-5.6 customer price fallback** (File:
   `setting/ratio_setting/model_ratio.go`)
   - Action: Add `gpt-5.6` beside `gpt-5.5` with the same ratio and leave the
     existing compact wildcard and versioned commercial wallet price path
     unchanged.
   - Why: Keeps normal New API price lookup and the commercial assumption in
     parity without a second billing catalog.
   - Dependencies: Step 3.
   - Risk: Medium; an incorrect price can mischarge usage.

### Phase 3: Proof and edge coverage — Edge Cases

7. **Expand direct API, compact, and route regressions** (Files:
   `relay/channel/openai/relay_responses_public_alias_test.go`,
   `relay/common/relay_info_test.go`,
   `router/private_mvp_access_routes_test.go`,
   `router/private_mvp_routes_test.go`)
   - Action: Exercise canonical and root Responses, model listing/retrieval,
     compact JSON, and compact SSE for `gpt-5.6`; assert unauthorized,
     expired, disabled, exhausted, wrong-group, and wrong-model keys do not
     create an upstream attempt.
   - Why: Verifies the public contract at the HTTP boundary rather than only
     testing helper functions.
   - Dependencies: Steps 4–6.
   - Risk: High; this is the primary customer authorization surface.

8. **Update the immutable Compose/gateway proof** (Files:
   `deploy/mvp/verify-compose.sh`, `deploy/mvp/verify-gateway.sh`)
   - Action: Seed and assert GPT-5.6 entitlements, token model limits, model
     pricing, compact abilities, and public response aliases. Keep at least one
     GPT-5.4 and one GPT-5.5 request in the proof so the extension cannot hide a
     regression. Assert the mock receives only its configured upstream model.
   - Why: Converts the feature into repeatable PostgreSQL/Redis/HTTP evidence
     on the release image and preserves the existing private-MVP gate.
   - Dependencies: Steps 5 and 7.
   - Risk: High; proof scripts are release evidence and must not weaken gates.

### Phase 4: Verification and handoff — Optimization/Release Gate

9. **Run focused verification and review the narrow diff** (Files: all files
   changed by Steps 1–8)
   - Action: Run focused Go tests in the cached Docker Go toolchain, `gofmt`,
     `go vet` for touched packages, `git diff --check`, and the immutable
     gateway proof with `MVP_GATEWAY_NETWORK_SUBNET=10.253.0.0/24`. Inspect
     response bodies, attempt counters, billing rows, and logs for alias
     preservation and secret/provider-slug redaction.
   - Why: Satisfies the GPT-5.6 acceptance criteria with fresh evidence while
     avoiding the known unrelated dirty-worktree failures.
   - Dependencies: Steps 1–8.
   - Risk: High; incomplete evidence blocks the feature gate.

10. **Prepare an isolated handoff** (Files: only GPT-5.6 files above)
   - Action: Report changed scope, exact verification output, unresolved
     external evidence gaps, and the next gate. Do not stage or commit unrelated
     dirty files; wait for explicit commit authorization before staging this
     feature.
   - Why: Preserves the current worktree and the repository's commit policy.
   - Dependencies: Step 9.
   - Risk: Low.

## Testing Strategy

- Unit: entitlement filtering, compact alias normalization, seed alias
  validation, model-price lookup, and public response redaction.
- Integration: PostgreSQL commercial access/entitlement fixtures plus Redis
  admission and mock-channel model mapping for canonical and compact requests.
- E2E: immutable Compose gateway proof covering model discovery, canonical/root
  Responses, compact JSON/SSE, unauthorized-key rejection, attempt counters,
  billing alias, and provider-slug redaction.
- Verification environment: use WSL Docker and the existing cached Go image;
  do not touch `C:\Users\z\Documents\Proxy Server`.

## Success Criteria

- [ ] Active entitled keys list and call `gpt-5.6` on `/v1/responses` and the
      documented root alias.
- [ ] Active entitled keys call `/v1/responses/compact` with `gpt-5.6`; the
      upstream sees only configured compact mapping and the customer sees
      `gpt-5.6`.
- [ ] A key without `gpt-5.6` entitlement is rejected before channel selection
      and creates no upstream attempt.
- [ ] Usage and billing evidence store `gpt-5.6`, never the compact/internal
      slug, and use the existing `gpt-5.5` price behavior.
- [ ] Existing `gpt-5.4` and `gpt-5.5` focused tests and gateway assertions stay
      green.
- [ ] Focused tests, formatting/vet/diff checks, and immutable gateway proof
      pass with fresh output.

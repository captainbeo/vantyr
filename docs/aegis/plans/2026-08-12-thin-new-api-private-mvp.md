# Thin New API Private MVP Implementation Plan

# Goal

Implement the approved Option B thin New API private MVP: a valid native New API
token calls Codex Responses through a configurable origin, receives mock JSON or
SSE, uses compact and model-list compatibility, and can recover once through a
configured mock channel before the first customer-visible byte. This plan is
local/private only; it does not authorize public deployment, real providers,
payments, or launch.

# Architecture

New API remains the only customer-facing gateway and the canonical owner of
authentication, authorization, channel records, model mapping, priority/weight
routing, relay, quota, usage, and native retry. The fork adds only a private
mode boundary around existing router/relay owners, central disabling of unused
legacy paths/jobs, mock-backed acceptance proof, and deployment configuration
checks. No custom proxy, routing sidecar, second account/token system, custom
billing/attempt/cost ledger, or alternate channel owner is introduced.

# Tech Stack

- Go 1.25.1, Gin, GORM, the pinned New API fork, and the existing relaykit module.
- PostgreSQL is the only production database. SQLite remains a test harness.
- Redis is required in private production where New API's native limiter or
  coordination path is used; this plan does not claim stronger fail-closed
  semantics than the pinned source proves.
- Docker Compose mock-primary/mock-secondary fixtures and existing contract tests.
- Codex CLI compatibility target 0.146.0; upstream pin
  66ee6b8f9889050ffef1f863a4314ce4a0516fb9.

# Baseline/Authority Refs

- AGENTS.md
- docs/aegis/specs/2026-08-12-thin-new-api-private-mvp-design.md
- docs/plans/2026-07-31-commercial-mvp.md
- docs/specs/2026-07-30-channel-and-codex-compatibility-design.md
- docs/compliance/2026-07-31-new-api-license-compliance.md
- docs/upstream/new-api.md
- Existing staged Step 1.4 work is preserved as deferred launch hardening and
  is not an implementation authority for this private path.

# Compatibility Boundary

The private path supports GET /v1/models, GET /v1/models/{model}, POST
/v1/responses, POST /v1/responses/compact, and the approved root aliases
/models, /models/{model}, /responses, and /responses/compact when the Codex
origin-only configuration requires them. Native New API Bearer token
validation, token status/expiry/quota, group/model permissions, channel
mapping, JSON/SSE relay, and usage settlement remain observable. Customer
Authorization is never sent as provider authentication; only the selected
channel credential is injected. Fallback is limited to one classified,
replay-safe failure before the first customer-visible byte. Disabled
image/video/Midjourney/Ollama/task and payment routes are unavailable in private
mode. Inherited non-commercial behavior remains compatible outside private mode.

# Verification

Every implementation slice follows deterministic RED/GREEN evidence, then the
affected package tests, go vet, gofmt check, contract/Compose checks, and one
frozen-fingerprint review appropriate to the risk. Evidence must cover native
token authorization, JSON/SSE/compact forwarding, model-list filtering,
alias-to-upstream mapping, credential/header isolation, pre-response fallback,
no post-byte replay, one logical usage record, disabled-route rejection,
PostgreSQL/Redis Compose requirements, and neutral origin configuration.
Docker/WSL failures remain explicit evidence gaps and are never represented as
passes.

## Plan Basis

- Fact: the pinned New API source already owns native users, API tokens, groups,
  model permissions, channels, credentials, model mapping, priority/weight
  routing, Responses, compact, model listing, quota, usage, and native retry.
- Fact: the fork already contains commercial channel secret-reference and
  transport safeguards plus two mock fixtures, but the public router still
  registers many inherited relay and task surfaces.
- Fact: the existing Compose contract already requires PostgreSQL, Redis,
  environment-backed secrets, loopback bindings, and mock fixtures.
- Assumption: the private MVP can run one gateway replica with configured mock
  channels and no live provider credentials.
- Unknown/external: final domain, DNS/TLS, provider credentials, resale terms,
  public Corresponding Source hosting, and production egress. These are not
  local implementation blockers.
- Ripple Signal Triage: route registration affects auth, distributor, mode
  detection, model listing, relay commitment, mock proof, and deployment
  documentation; verification therefore spans those owners only.

## BaselineUsageDraft

- Required baseline refs: all six refs in Baseline/Authority Refs.
- Delivered context refs: the approved design and independent New API/base-URL
  audits supplied in the current task context.
- Acknowledged before plan: all six required refs, read in this worktree.
- Cited in plan: all six required refs.
- Missing refs: none for private mock implementation; live commercial evidence
  is intentionally external.
- Decision: continue.

## Requirement Ready Check

- Requirement source refs: approved thin MVP design and current user scope lock.
- Goals and scope refs: design Goal, Architecture, Included behavior, and
  Explicitly deferred sections.
- User/scenario refs: valid native token calling Responses through the future
  hostname with mock JSON/SSE and controlled fallback.
- Requirement item refs: design Acceptance tests 1-14.
- Acceptance/verification refs: design acceptance tests plus AGENTS.md step and
  review gates.
- Open blocker questions: none for private mock execution.
- Decision: ready.

## File-Level Ownership Map

| Surface | Existing owner/files | Planned change |
| --- | --- | --- |
| Public relay routes | router/relay-router.go, router/main.go | One private-mode boundary; keep native Responses/compact/models. |
| Native API authentication | middleware/auth.go, model/token.go | Preserve native token behavior; add only private-boundary tests and any minimum guard needed to prevent the deferred commercial-key path from becoming the private contract. |
| Token/group/model filtering | middleware/distributor.go, controller/model.go, model/ability.go | Owner-level regressions; no second permission owner. |
| Channel mapping/credentials | model/channel_commercial.go, service/channel_secret.go, service/commercial_transport.go | Reuse resolver/transport; extend only missing mock assertions. |
| Responses/compact relay | controller/relay.go, relay/responses_handler.go, relay/common/relay_info.go | Reuse native handler; add JSON/SSE/compact and commitment/fallback regressions. |
| Mock proof | deploy/mvp/mock/main.go, deploy/mvp/mock/main_test.go, deploy/mvp/verify-compose.sh, deploy/mvp/mock/openapi.yaml | Extend bounded capture/control only where an acceptance test lacks evidence. |
| Deployment contract | deploy/mvp/compose.yaml, deploy/mvp/gateway-entrypoint.sh, deploy/mvp/compose_contract_test.go, deploy/mvp/README.md | Assert PostgreSQL/Redis, no literal secrets, neutral origin configuration, and private route inventory. |
| Startup/legacy jobs | main.go, controller/system_task_handlers.go, service/codex_credential_refresh_task.go | Centrally disable unused private-mode jobs while preserving non-private defaults. |
| Evidence | docs/aegis/work/2026-08-12-thin-new-api-private-mvp/* | Record plan, checkpoints, drift, evidence, and final bundle. |

## Existence Check

- Proposed new surface: a private-mode route/startup policy and missing mock
  acceptance evidence.
- Existing owner/reuse candidate: New API router/middleware and existing mock
  fixture/Compose contract.
- Why existing surface is insufficient: inherited relay routes remain
  registered and existing mock proof does not cover every private-MVP invariant.
- Creation proof: one boundary guard and focused tests are smaller than a second
  proxy or route registry; existing relay and mock owners remain canonical.
- Entropy/retirement impact: no duplicate gateway owner; private mode centrally
  disables unsupported paths while non-private compatibility remains.
- Decision: add-with-proof for one narrow boundary policy; reuse-existing for
  auth, routing, mapping, relay, quota, usage, and mock ownership.

## Architecture Integrity Lens

- Invariant: one request path owns authentication, permissions, channel
  selection, relay, response commitment, quota, and usage.
- Canonical owner/contract: New API router/middleware/relay plus the existing
  Codex Responses contract and channel records.
- Responsibility overlap: a caller-side proxy, fallback ledger, custom token
  store, billing service, or sidecar would duplicate New API and is forbidden.
- Higher-level simplification: one private-mode boundary can disable unused
  legacy surfaces centrally; individual adaptor upgrades are unnecessary.
- Retirement/falsifier: remove the guard only if a later approved route
  inventory proves every exposed route is supported; otherwise keep it.
- Verdict: architecture aligned; proceed with one boundary owner and proof.

## Plan Pressure Test

- Owner/contract/retirement: explicit; New API remains source of truth and the
  staged Step 1.4 track is preserved as deferred.
- Architecture/higher-level path: explicit; no sidecar or duplicate ledger.
- Verification scope: every acceptance invariant has a focused test or a
  Compose structural check and an exact command.
- Task executability: tasks name files, tests, RED/GREEN commands, and stop
  conditions.
- Pressure result: proceed.

## Plan-Time Complexity Check

- Artifact class: Go router/middleware, relay compatibility, mock/deployment
  proof, and lifecycle documentation.
- Current pressure: router and controller are broad inherited files; commercial
  transport and mock fixtures are already focused.
- Projected pressure: low if policy is centralized and tests remain owner-level;
  high if route-specific guards, a second router, or per-adaptor rewrites appear.
- Budget result: within-budget with one centralized guard; over-budget for a
  custom gateway/sidecar or commercial rewrite.
- Recommendation: add one small policy owner only if an in-place router guard
  would duplicate decisions; do not refactor unrelated inherited code.

## Dirty-Tree Safety

The current worktree contains existing staged Step 1.4 commercial-key changes
and four known unstaged bootstrap fixes. This plan does not authorize editing,
unstaging, staging, resetting, rewriting, or committing those files. Before
implementation, capture status and the staged binary fingerprint. If a required
thin-MVP change overlaps a staged file, isolate the change without rewriting
the staged content or stop for a scope decision.

## Implementation Tasks

### Task 1: Freeze the private route and startup boundary

Files: router/relay-router.go, router/main.go, main.go,
controller/system_task_handlers.go, service/codex_credential_refresh_task.go,
and focused router/startup tests.

Why: a private proxy must expose only Responses/compact/models and must not
accidentally expose image/video/Midjourney/Ollama/task/payment surfaces.

Impact/compatibility: private mode is opt-in through an explicit deployment
setting; unset/private-mode-off preserves inherited route registration. The
Responses, compact, model, and liveness handlers remain existing New API
handlers.

Steps:

1. Write failing route-table tests that build the Gin engine in private mode,
   assert accepted method/path behavior, assert disabled relay/task/image
   paths return a sanitized rejection, and assert private-mode-off keeps
   existing routes.
2. Run the exact RED command:
   wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go test ./router ./controller -run 'Private|Route|SystemTask' -count=1"
   Expected result: the new tests fail for the missing private boundary.
3. Implement the smallest centralized guard using existing route context
   conventions; gate startup registration of unused polling, image/video,
   Midjourney, Ollama operations, balance probes, ratio sync, and legacy Codex
   refresh jobs without changing non-private defaults.
4. Rerun the RED command and expect ok with no route leakage.
5. Run gofmt on touched Go files and:
   wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go vet ./router ./controller ./service"

Repair track: fix broad inherited registration at one boundary; do not add
provider adaptors. Retirement track: disabled jobs remain available only outside
private mode until a separate approved route inventory retires them.

### Task 2: Prove native auth, permissions, model listing, aliases, and bounds

Files: middleware/auth.go, middleware/distributor.go, controller/model.go,
model/ability.go, relay/constant/relay_mode.go, relay/common/relay_info.go,
router/relay-router.go, and owner-level tests beside those owners.

Why: direct API calls must enforce native token validity, status/expiry/quota,
group/model permissions, bounded body/content-type/path inputs, and token-scoped
model listing before any channel sees a request. The origin-only aliases must
enter the same chain without a redirect.

Impact/compatibility: preserve native model-list and orphan-ability behavior.
Do not make the deferred sk-pxv1 commercial-key system the private contract.
Outside private mode, keep inherited authentication alternatives unchanged.

Steps:

1. Add deterministic failing tests for valid native token success; invalid,
   expired, disabled, exhausted, wrong-group, and unauthorized-model rejection;
   filtered list/retrieve behavior; root aliases; alternate credential rejection
   in private mode; bounded request rejection; and zero mock attempts.
2. Run:
   wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go test ./middleware ./controller ./model ./relay/constant ./relay/common ./router -run 'Token|Model|Ability|Alias|Request|Private' -count=1"
   Expected result: RED only for the new regressions.
3. Add the smallest private auth guard and canonical alias-path helper. Register
   root aliases with the same TokenAuth, distributor, request-limit, and relay
   handlers. Ensure mode detection and channel selection use the canonical
   internal path while logs retain the customer path. Filter model retrieval
   through the same token/group visibility owner as model listing.
4. Rerun the focused command and expect ok. Run go vet on the same packages.
5. Record the known Minor pagination mismatch (next_cursor in a usage response
   while GET /api/log/self has no cursor input) without changing this diff.

Repair track: address only confirmed compatibility or authorization gaps.
Retirement track: retain legacy token behavior outside private mode and preserve
the staged Step 1.4 files as deferred hardening.

### Task 3: Prove JSON, SSE, compact, mapping, isolation, and fallback

Files: controller/relay.go, relay/responses_handler.go,
relay/common/relay_info.go, service/commercial_transport.go,
deploy/mvp/mock/main.go, deploy/mvp/mock/main_test.go,
deploy/mvp/mock/openapi.yaml, and focused relay/service tests.

Why: this is the observable private-MVP product path.

Impact/compatibility: reuse native response parsing, channel mapping, quota,
usage, and retry. One classified primary failure may use one secondary channel
before commitment; a stream is never replayed after a customer byte or event.
No credential, channel detail, internal model slug, or raw upstream error reaches
the customer.

Steps:

1. Add failing mock-backed tests for Responses JSON, Responses SSE, compact,
   exact public-alias to upstream-model mapping, provider-credential-only
   headers, sanitized response headers/errors, one pre-response secondary
   attempt, no post-byte replay, and one logical usage/quota settlement.
2. Run:
   wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go test ./controller ./relay/... ./service ./deploy/mvp/mock -run 'Response|Compact|Commercial|Mock|Fallback|Header' -count=1"
   Expected result: RED only for missing proof or a confirmed gap.
3. Implement the minimum changes beside the existing response and transport
   owners. Never add an attempt ledger, cost ledger, custom router, or retry
   sidecar.
4. Rerun the focused command and expect ok. Run go vet on those packages.
5. Inspect customer-visible responses and mock capture to confirm no secrets,
   raw upstream errors, internal channel names, or internal model slugs appear.

Repair track: fix only failures that violate the accepted contract. The known
Minor pagination issue remains deferred. Retirement track: unsupported legacy
relay adaptors are centrally rejected, not deleted.

### Task 4: Lock PostgreSQL/Redis and neutral-origin deployment behavior

Files: deploy/mvp/compose.yaml, deploy/mvp/gateway-entrypoint.sh,
deploy/mvp/README.md, deploy/mvp/compose_contract_test.go,
deploy/mvp/verify-compose.sh, and the existing customer contract files.

Why: production storage and shared coordination must be explicit, credentials
must remain deployment-configured, and the future domain must remain changeable.

Impact/compatibility: no live deployment or real credentials. Keep loopback
mock controls, source-attribution requirements, and the existing exact-tree
release-context fence.

Steps:

1. Add failing structural tests for PostgreSQL/Redis requirements, no literal
   secrets, neutral ServerAddress/session-origin configuration, accepted route
   inventory, and disabled private routes.
2. Run:
   wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go test ./deploy/mvp -count=1"
   Expected result: RED only for new structural assertions.
3. Make only Compose/readme/contract changes needed to express the approved
   boundary; do not add MySQL/SQLite production services or a public hostname.
4. Rerun the command and expect ok.
5. Run bash deploy/mvp/verify-compose.sh config. Run the up proof only if Docker
   and WSL are healthy; otherwise record the exact external failure and do not
   claim an up pass.

### Task 5: Freeze, review, evidence, and separate commit

Files: docs/aegis/work/2026-08-12-thin-new-api-private-mvp/*,
docs/aegis/plans/2026-08-12-thin-new-api-private-mvp.md, and narrowly affected
evidence JSON.

Steps:

1. Freeze the implementation fingerprint with zero unstaged and zero untracked
   files; do not include existing staged Step 1.4 work unless scope is
   explicitly changed.
2. Obtain one consolidated independent quality/security review of that exact
   fingerprint. Critical/Important findings block; Minor findings are recorded
   and deferred.
3. Repair blocking findings with focused RED/GREEN evidence, then rerun only
   affected checks and the required final gate once.
4. Update checkpoint, drift, evidence, and proof bundle records; run Aegis
   check, bundle, and JSON artifact validation.
5. Commit the thin private-MVP slice separately with the approved author
   identity. Do not start the next step before the commit exists.

## Exact Verification Commands

~~~text
wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go test ./router ./controller -run 'Private|Route|SystemTask' -count=1"
wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go test ./middleware ./controller ./model ./relay/constant ./relay/common ./router -run 'Token|Model|Ability|Alias|Request|Private' -count=1"
wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go test ./controller ./relay/... ./service ./deploy/mvp/mock -run 'Response|Compact|Commercial|Mock|Fallback|Header' -count=1"
wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go test ./deploy/mvp -count=1"
wsl.exe bash -lc "cd /mnt/c/Users/z/Documents/worktrees/commercial-mvp && /usr/local/go/bin/go vet ./router ./controller ./middleware ./model ./relay/... ./service ./deploy/mvp/mock"
gofmt -l on each touched Go file; expect no output
git diff --check
git diff --cached --check
bash deploy/mvp/verify-compose.sh config
python C:/Users/z/.codex/plugins/cache/personal/aegis/2.2.0/scripts/aegis-workspace.py check --root C:/Users/z/Documents/worktrees/commercial-mvp
~~~

No full unrelated suite is required after each slice; widen only at the
approved final gate.

## Risks and Rollback

- Redis limiter failures and fallback semantics are inherited evidence
  limitations; production configuration must require Redis and must not claim
  stronger behavior without a separate tested change.
- Docker/WSL storage or network failures can prevent Compose up; record them as
  external evidence gaps and keep local contract proof separate.
- A route allowlist can break an undocumented inherited client. Private mode is
  explicit and tests enumerate its accepted contract; private-mode-off preserves
  inherited registration.
- Rollback is a commit-level revert of the private guard/startup switch/mock
  proof/documentation. Do not drop database columns, staged Step 1.4 files, or
  unrelated user work.

## Retirement and Deferred Tracks

- Step 1.4 commercial gateway-key schema/UI remains staged, preserved, and
  classified as deferred launch hardening. It is not expanded or deleted here.
- Stripe/payment adapters, custom billing/accounting, health/attempt/cost
  ledgers, image/video/Midjourney/Ollama, task polling, MySQL/SQLite production
  parity, public deployment, real providers, payments, customer invitations,
  and launch remain deferred.
- The known next_cursor versus cursorless /api/log/self mismatch is a Minor
  pagination issue and is recorded, not expanded.
- Future public launch must add AGPL Corresponding Source publication, final
  domain/DNS/TLS proof, provider/resale authorization, and a separate launch
  hardening review.

## ADR and Baseline Sync Signal

This plan preserves the approved architecture decision that New API is the sole
customer-facing gateway and source of truth. If implementation introduces a
second gateway owner, custom token/account owner, custom billing ledger, or a
new fallback authority, stop and return to architecture review before editing.


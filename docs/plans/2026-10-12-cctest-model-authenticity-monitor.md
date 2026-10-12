# CCTest Model-Authenticity Monitoring — Design (2026-10-12)

Status: **draft, owner sign-off pending.** Nothing deployed; no sidecar
exists yet. Zero fork delta: external sidecar container + admin API +
seller endpoints only, per AGENTS.md config-first rule.

## Problem

New API's channel test verifies connectivity, not identity — it cannot
detect a seller serving a different model than the request asked for.
On A6 this is structural (auto-routing over ~1,686 merchants, see
VANTYR.md); on Selora it is a trust assumption. cctest.ai fingerprints
Claude/GPT-family responses (verdicts: `official` 100 / `official_flawed`
/ `unofficial` / `reversed` / `not_claude` 0) and exposes a REST API:
`POST /api/v1/check` (1 credit) + `GET /api/v1/check/:taskId`; free
status endpoints pair with console-configured scheduled monitoring.

## Architecture

`vantyr-cctest` sidecar container on the VPS — same pattern as
`discord-ticket-bot`: small Python service in
`deploy/vantyr/cctest-monitor/`, one compose service. It talks to the
sellers' endpoints directly (monitoring keys, via cctest's check API),
the gateway admin API (channel status + usage logs), and a Discord
webhook (alerts).

Division of monitoring labor (all three layers enabled):

| Concern | Owner | Cost |
|---|---|---|
| Connectivity / latency | native channel test, 10 min (Monitor settings) | ~free (MaxTokens 16) |
| Catalog drift | native model-update scan, 30 min default | free |
| Model authenticity | cctest sidecar (this doc) | credits + tokens |

## Verified mechanics (pinned fork code, v1.0.0-rc.41)

- `POST /api/channel/:id/status` accepts only 1 (enabled) and 2
  (manually disabled) — `controller/channel.go` `isManageableChannelStatus`.
- The scheduled test loop skips status-2 channels
  (`selectChannelsForAutomaticTest` in `controller/channel-test.go`),
  and auto-re-enable (`ShouldEnableChannel`) fires only on status 3.
  A status-2 quarantine is therefore exclusively the sidecar's to
  release, and native auto-disable (status 3) is exclusively New API's —
  the two systems cannot fight over a channel.
- Every status flip is audit-logged (`recordManageAudit`).
- Channel lookup is by **name** (`selora-reseller`, `a6-marketplace`):
  VANTYR.md records conflicting A6 channel IDs (3 in the R2 entry, 2 in
  the production bootstrap entry); names are stable.
- Sidecar quarantine state lives in a volume-mounted JSON file. If the
  state is lost, the default is *never re-enable* (fail-safe). The
  sidecar re-enables only channels it recorded as self-quarantined;
  owner-disabled channels are never touched.

## Policy

**Coverage.** `claude-*` and `gpt-*` models only (cctest's fingerprint
domain). Eligible set per channel = channel models ∩ supported prefixes
∩ used in the last 7 days (traffic-gate via the admin log API —
verifying a model nobody calls burns credits for nothing). glm/kimi
models rely on the native test. Optional per-model upstream-name
mapping in sidecar config (A6's dot/dash GPT naming, if the owner
widens that token's model permissions).

**Cadence.** One (channel, model) check per channel per
`CYCLE_MINUTES` (default 10), LRU rotation over the eligible set: each
model is re-verified every ~`CYCLE_MINUTES`·N minutes at N eligible
models. Credit burn and seller load scale linearly with cadence; one
knob adjusts both.

**Verdict mapping.** `official` = pass. `official_flawed` = pass,
logged; 3+ within 24 h → Discord alert. `unofficial` / `reversed` /
`not_claude` = fail. API errors, timeouts, and inconclusive results are
**never** fails — no quarantine without an explicit bad verdict.

**Fail thresholds.** selora: 1 fail → quarantine (single dedicated
upstream; a fail is unambiguous). a6: 2 consecutive fails → quarantine
(the merchant lottery makes single-draw verdicts noisy). mia (Mia
Router, https://miarouter.online): 2 consecutive fails — same noise
tolerance as a6 until live verdicts justify tightening.

**Quarantine.** Set status 2 via the admin API and record it in the
state file. Re-test the failing model every cycle; pass → status 1,
clear state. 3 consecutive fails → stop spending credits, permanent
quarantine, Discord alert, manual re-enable only. During quarantine the
other channel takes all traffic (`RetryTimes=1` failover) — accepted by
design: authenticity risk outranks latency risk.

## Credentials & exposure

- Seller keys: dedicated capped monitoring sub-keys at Selora and A6
  (~$5 balance, model-restricted to claude+gpt where supported), created
  by the owner at C0. Channel keys are the interim fallback until those
  exist. Bounded exposure, even though cctest claims not to store keys.
- cctest: owner account + API key + ¥50 credit pack (5,000 checks at
  ¥0.01/check, 180-day validity).
- Gateway: dedicated role-10 admin user `cctest-sidecar` with an access
  token (channel operate + log read permissions). Not the
  `vantyr-bootstrap` root, which must be deleted at launch. Created by
  the owner at C1.
- All secrets live in the sidecar's env (untracked `.env` on the VPS);
  none in the repo.

Cost at the default cadence (2 channels × 144 checks/day): credits
≈ ¥2.9/day (~$0.40/day; a pack lasts ~17 days) plus seller tokens
(quick mode ≈ 3 small requests per check — expected well under
$0.01/check at our cost basis; C0 measures it). A 20-minute cycle
halves both if C0 says so.

## Phases

### C0 — calibration (owner actions, before any build)

**Schema recovered (2026-10-12)** — cctest's docs page renders from
i18n strings embedded in their public JS bundle; mining it gave the
full field set. Request: `POST /api/v1/check` with
`{url, apiKey, model, provider, attributionOnly, concurrency}` —
`url` auto-appends the provider path (`/v1/messages` for claude,
`/v1/responses` for codex), `provider` is `claude` | `codex` (GPT
models must use `codex`), `attributionOnly: true` is the cheap quick
mode (3 requests, swap-detection only), `concurrency` 1–5. Response:
task returns `taskId`; poll `GET /api/v1/check/:taskId` every 2–3 s
until `status` is `done`/`error`; result fields include `verdict`
(official / official_flawed / unofficial / reversed / not_claude),
`responseModel`, `expectedModel`, `scores`, `progress`, `step`, and
with `tokenUsage` enabled a token audit. The monitor now sends this
exact schema (CCTEST_FULL_CHECK env selects full vs quick mode).

1. ~~Nail the check-API schema~~ (done — see above).
2. ~~Create the cctest account + buy the ¥50 pack~~ (done 2026-10-12).
3. **Generate the API key** in the cctest console's API Key page
   (Account → API Key). Key shows once; store it in the VPS `.env`.
4. Create capped monitoring keys at Selora and A6 (~$5, claude+gpt
   restricted) — or reuse the channel keys for calibration only.
5. Run 3–5 quick-mode checks (one per flagship model per channel) and
   record the token cost from seller-side billing / our channel
   accounting.
6. Ask cctest whether their console scheduled monitoring can run our
   cadence with the free `/api/v1/status` endpoints — if yes, Phase C3
   replaces our scheduler and per-check credits may drop away.

   Exit: real per-check cost → final cadence decision.

Calibration flow (verified schema):

```bash
CHECK=$(curl -s https://cctest.ai/api/v1/check \
  -H "Authorization: Bearer $CCTEST_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://api.selora.lol","apiKey":"<seller-key>","model":"claude-fable-5-1","provider":"claude","attributionOnly":true,"concurrency":1}')
curl -s "https://cctest.ai/api/v1/check/<taskId from CHECK>" \
  -H "Authorization: Bearer $CCTEST_KEY"
# poll until status is done; read "verdict"
```

### C1 — observe-only sidecar (1 week)

**Code complete (2026-10-12, this repo):** `deploy/vantyr/cctest-monitor/`
(monitor.py, test_monitor.py, Dockerfile) + compose service
`cctest-monitor` + `.env.example` CCTEST_* block. The sidecar's own
policy suite (12 mocked-gateway/cctest tests — quarantine, release,
thresholds, permanent, owner-override incl. status-3 native auto-disable,
traffic gate, fail-open) passes, and the image builds from the pinned
pattern (`docker compose build cctest-monitor`). The check request now
sends the verified schema (recovered from cctest's JS bundle, see C0);
`verdict_category` falls back through alias keys if the live response
differs. **Deploy is gated on C0 remaining steps:** generate the API
key, calibrate cost, create the monitoring PAT + seller keys.

Deploy steps (owner, on the VPS): commit + push, pull, set the real
CCTEST_* values in `.env`, `docker compose up -d cctest-monitor`,
confirm `docker logs vantyr-cctest-monitor` shows the startup line and
per-cycle checks. Observe-only (`ENFORCE=false`) by default.

Exit: one week of verdicts with zero would-be false quarantines.

### C2 — enforcement (owner sign-off gate)

Flip `ENFORCE=true`. Prove the disable → routing-shift → enable round
trip on production with one deliberate test disable (evidence recorded
in VANTYR.md), then leave it live.

### C3 — optional

If cctest console scheduling suffices, shrink the sidecar to a
`/api/v1/status` poller + enforcer.

## Open questions

- ~~cctest request/response schemas~~ — recovered from their JS bundle
  (see C0). The result poll's exact JSON key for the verdict is
  `verdict`; if the live response differs, the monitor's
  `verdict_category` falls back through `category`/`result`/`level`.
- Fingerprint coverage for our exact SKUs (C0.5 — run one check per
  flagship model and look at `responseModel`).
- A6 verdict attribution under the merchant lottery — mitigated by the
  2-fail threshold; per-merchant pinning (per-supplier tokens) is the
  later lever if it stays noisy.
- Whether A6 monitoring keys can be model-restricted.

## VANTYR.md delta

None yet. Record at C1 deploy (service name, credentials location,
observe-week start date) and again at C2 (enforcement flip + verification
evidence).

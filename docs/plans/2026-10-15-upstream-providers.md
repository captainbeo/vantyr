# 2026-10-15 — Upstream provider redesign (Selora / Mia / Yingzbot / A6)

Status: design aligned with owner 2026-10-15 (ladders below are the
owner's; A6 = pinned + general two-layer keys per §5; sol repriced and
luna dropped per §2). Execution pending: probe battery, owner-supplied
keys (Yingzbot pack, Mia production key, Selora unlimited-key
rotation, A6 pinned keys), and the OPEN decisions in §9. When
deployed, this supersedes the 2026-10-13 "Channel assignment map" in
VANTYR.md.

## 1. Provider economics (owner-supplied 2026-10-15)

| Provider | Billing | RPM | Marginal cost of one request |
|---|---|---|---|
| Selora (unlimited key) | flat per period | 20 (may upgrade to 30) | $0 — only the RPM cap binds |
| Mia ($72 → $5,500 credit pool) | per request from the pool (~$0.0079 effective at package rate) | 100 (a separate Mia "unlimited" product has 35) | ~$0.008 of prepaid credit |
| Yingzbot | prepaid token packs | owner-selectable 200–3,000 | ~$0 while the pack lasts |
| A6 | PAYG per 1M tokens | unknown — watch for 429s in logs | real dollars, unbounded |

## 2. Yingzbot margin check against live sell prices

Yingzbot cost card (owner-supplied; opus is the base at $0.0099/1M,
sonnet = 1/1.6666 of that, astra family priced off astra x1):

| Model | Yingzbot cost /1M | Our sell (in / out) | Margin |
|---|---|---|---|
| claude-opus-5 | $0.0099 | $0.12 / $0.50 | 12× / 50× — excellent |
| claude-sonnet-5 | $0.0059 | $0.26 / $1.30 | 44× / 220× — excellent |
| claude-opus-5-jailbreak | $0.0150 | not set | 2× floor = $0.03/1M; recommend pricing at ≥ vanilla opus so the jailbreak variant does not undercut it |
| gpt-6-astra | $0.0250 | $0.20 / $0.70 | 8× / 28× — good |
| gpt-6-sol | $0.0625 | $0.085 / $0.15 (owner reprice 2026-10-15, verified live: ratio 0.0425 / completion 1.7647) | resolved — input 1.36×, output 2.4×, blended ~1.6× at 3:1 in:out (1.57× at 4:1, ~1.45× at 10:1): inside the 1.5× exception band, so the uniform Yingz-first ladder stands. Input-heavy mixes (reasoning models with big system prompts) sit at the bottom edge — $0.10 input would floor every mix at ≥1.5×, owner's call. |
| gpt-6-luna | $1.2750 (astra ×51) | — | **not carried (owner decision 2026-10-15).** Cleanup owed: live /api/pricing again returns `gpt-5-6-luna` (ratio 37.5 → $75/1M in / $600/1M out, no groups, unroutable — re-added after the 2026-10-13 full strip, possibly a typo for 0.375); strip the ratio-map row again so Model Overview doesn't list an unsellable $75 model. Also verified live 2026-10-15: gpt-6-1-sol input raised $0.06 → $0.10 (ratio 0.05, completion 2). |

Assumption to verify in the probe: the $/1M rate is uniform for input
and output tokens (their card reads per-1M flat). Confirm from the
actual meter charge of a real request before finalizing prices.

Authenticity caution: these prices are 2–3 orders of magnitude below
official API pricing. That is presumably pooled/batched capacity —
fine, but it makes the cctest one-shot authenticity gate per Yingzbot
model non-optional before real traffic (§7). Supply durability is also
a risk (very cheap sellers disappear); the ladders' backstops cover
that by design.

## 3. Aligned ladders (owner decision, 2026-10-15)

Unlimited group: **Selora → Mia → Yingzbot → A6** (ordered by what an
extra request costs us: free flat key, cheap prepaid pool, prepaid
packs, real money last).

PAYG (default group): **Yingzbot → A6 → Mia → Selora** (prepaid/elastic
rails; the flat key is touched only when the other three are all down —
the 20 RPM stays the subscribers' private lane).

"Use the provider only when the model is supported" is automatic: each
channel lists only models its provider actually carries (probe-verified
first), and the ladder is built per model, so unsupported steps are
simply skipped. A provider that lists a model but errors on it also
self-heals: the error triggers the auto-retry and the next provider
takes over; the customer never sees the seller error.

Longest chain is 5 steps (opus-5/sonnet-5 walk
Selora→Mia→Yingz→A6pin→A6gen, mirrored in PAYG), so
**RetryTimes goes 2 → 4** (options table, 60s sync, no restart;
attempts = RetryTimes+1 must cover the full ladder). Shorter ladders
burn harmless extra attempts re-rolling the lowest step after it
already failed.

## 4. Channel topology (10 channels)

Priority is per channel, and a channel serves one group, so the same
seller sits at different depths per group — same role-split pattern as
the 2026-10-13 deploy. Repurposed existing channels keep their IDs.

| Channel | From | Group | Priority | Models (probe-gated entries marked *) |
|---|---|---|---|---|
| selora-unlimited | ch4 (+ rotation key) | unlimited | 40 | fable-5, fable-5-1, opus-5, opus-5-5, sonnet-5, sonnet-5-5* |
| mia-unlimited | new | unlimited | 30 | fable-5, fable-5-1, opus-5, opus-5-5, sonnet-5, astra* |
| yingz-unlimited | new | unlimited | 20 | opus-5, sonnet-5, astra, sol |
| a6pin-unlimited | new (pinned key) | unlimited | 10 | fable-5, fable-5-1, opus-5, opus-5-5, sonnet-5, sonnet-5-5, astra, sol — **no gpt-6-1-sol** (owner rule); each model merchant-pinned on the key |
| a6gen-unlimited | ch6 (general key) | unlimited | 5 | same eight — marketplace lottery, absolute last resort |
| yingz-default | new | default | 30 | opus-5, sonnet-5, opus-5-jailbreak, astra, sol |
| a6pin-default | new (pinned key) | default | 20 | all nine SKUs **incl. gpt-6-1-sol**, each merchant-pinned |
| a6gen-default | ch2 (ch5 merged in; general key) | default | 15 | all nine — lottery overflow for the pinned tier |
| mia-default | ch7 (real key, status 1) | default | 10 | fable-5, fable-5-1, opus-5, opus-5-5, sonnet-5, astra* |
| selora-default | ch1 (current shared key) | default | 5 | the six Claude SKUs — relief valve; traffic share should be ~zero normally |

ch3 (selora-default-fallback) and ch5 (a6-default-fallback) retire;
their model lists merge into ch1/ch2. Resulting ladders (the A6 step
is pinned-then-general, per §5): unlimited fable/opus-5-5 =
Selora→Mia→A6pin→A6gen; opus-5/sonnet-5 = Selora→Mia→Yingz→A6pin→
A6gen; sonnet-5-5 = Selora→A6pin→A6gen; astra = (Mia*)→Yingz→A6pin→
A6gen; sol = Yingz→A6pin→A6gen. PAYG fable/opus-5-5/sonnet-5-5 =
A6pin→A6gen→Mia→Selora; opus-5/sonnet-5 = Yingz→A6pin→A6gen→Mia→
Selora; astra/sol = Yingz→A6pin→A6gen (Mia* after A6); jailbreak =
Yingz only, no safety net; gpt-6-1-sol = A6pin→A6gen, default group
only — the pin/general split gives even the A6-only SKU an internal
second step.

One shape question the A6 probe (§8) decides: a New API channel holds
ONE key. If each pinned key carries exactly one model, the a6pin tier
becomes one channel per pinned model, all sharing the P20/P10 tier
(New API weight-shares same-priority channels automatically). If a
single key can hold several models each pinned to their own merchant,
the two a6pin channel rows above stand as written. Start minimal
either way: 2 pinned keys (fable-5, fable-5-1) — see §5.

Group mechanics are already live and untouched: `default` vs the
special usable group `unlimited` (group isolation deployed
2026-10-13). No fork changes to groups.

Yingzbot `model_mapping` is TBD from the /v1/models probe — their
marketing names ("GPT 5.6 Sol • Terra • Luna • ASTRA 6", "GPT SOL &
Lunar 6") do not obviously match our slugs; expect name mapping like
A6's (`gpt-6-sol → <their id>`). Same for the jailbreak model's
upstream name.

## 5. A6 key strategy (owner facts 2026-10-15: multiple keys per
wallet, merchant pinning available, personal model pools available)

**Design: two A6 channel layers — pinned keys + general key.**

- **a6pin tier (P20 default / P10 unlimited):** one pinned key per
  (model → merchant) we care about, all under the ONE wallet. Pinning
  gives deterministic attribution: we KNOW which merchant served the
  request, so a cctest bad verdict maps 1:1 to that merchant. Bad
  merchant → rotate the pin to the next merchant on A6's per-model
  listing (ranked by price) — exactly the owner's "move over to
  Merchant B" workflow. Merchant churn becomes a key-field edit on
  A6's side, not a gateway channel redesign.
- **a6gen tier (P15 default / P5 unlimited):** the current general
  key, all nine models, marketplace lottery — the overflow behind the
  pinned tier. One bad merchant in the lottery poisons ~1/N of
  requests; per-request randomness spreads the rest. The lottery's
  cheap anchor merchants remain the pricing-rule reference.

Why this beats pure-general (my earlier recommendation, superseded):
with pinning available, the general key's strengths (resilience,
spread) decouple from its weakness — attribution, the fable→opus swap
cctest caught at 96% on the general key. The pinned tier gives
*deterministic* authenticity, exactly where A6 is weakest; the lottery
tier keeps elasticity as backstop.

Channel shape note (probe decides): if a pinned key truly carries only
one model, the a6pin tier becomes one channel per key, all sharing
the same priority (weights can then favor cheap merchants).
New API weight-shares same-priority channels automatically, so the
shape is a row-count difference, not a redesign. Start with the
minimum: 2 pinned keys (fable-5, fable-5-1 — the flagship swap
victims) and expand only if verdicts say so.

**cctest mechanics under the two-layer design:** each pinned key gets
its own SELLER_CHANNELS entry (name `a6-<model>`), so the monitor
checks the deterministic path per model per cycle, and the general
entry keeps sampling the lottery path. A bad verdict on a pinned key
maps to an actionable unit: rotate the pin (edit the key's merchant
on A6's side — zero gateway changes), alert, or quarantine the pinned
channel and ride the lottery tier. Bad verdicts on the general key
stay model-level (remove the model from a6gen's list). The monitor's
PUT models-only removal remains the mechanism; coverage gate still
passes everywhere (pinned + general steps plus non-A6 backstops for
every multi-provider model; gpt-6-1-sol alerts instead of removing
when BOTH its steps would be hit).

**"Personal pool for a model":** if A6's personal-pool feature is a
dedicated capacity bucket for that model (not shared with the
marketplace), pinned+pool keys on the flagship models are the natural
home — probe the feature's exact semantics when creating the pinned
keys; pool keys would additionally insulate us from marketplace
capacity swings.

**Owner actions owed:** create the pinned keys on A6 (start: fable-5,
fable-5-1; expand per verdicts), each pinned to a cheap high-volume
merchant from the per-model listing; and **widen the A6 monitoring
key's model permissions to the Claude models** — it is currently
GPT-only, and PAYG fable/ops-5-5/sonnet-5-5 ride the pinned-A6 tier
as their normal path; the front door must be watched.

## 6. RPM notes

Selora 20 (→30 upgrade widens step 1; no structural change). Mia pool
100 — the $72 package key; the separate 35-RPM Mia unlimited product
is a future flat-cost subscriber channel if ever bought (one channel
add, no redesign). Yingzbot: set ~1,000 if RPM is a free setting,
~600 if it prices the pack — the ceiling it must cover is a full
subscriber cascade (~100 RPM burst) plus PAYG peak, not 3,000. A6
unknown: discover empirically from 429s in the logs; ask A6 per-key
limits if it binds.

## 7. cctest changes

Code (the only code change in this whole design): teach the monitor
the fourth seller — `yingz` prefix in `known_prefixes` and
`fail_threshold_prefixes` (default `FAIL_THRESHOLD_YINGZ=2`),
compose env mapping, `.env.example` entry, one mocked test; rebuild
the container. A `yingz|<base>|<key>` SELLER_CHANNELS entry follows
(auth works externally, or gateway-routed like Selora if their key is
TLS-gated — probe decides). With A6 pinned-merchant channels (§5),
each pinned key also gets a SELLER_CHANNELS entry (same wallet —
no extra A6 cost): cycle checks then cover both the deterministic
pinned path and the sampled lottery path per model.

Gates and posture: one full authenticity check per Yingzbot model
before pointing real traffic (the exact check that caught A6 serving
opus in place of fable); threshold 2 for yingz mirrors a6/mia until
live verdicts say otherwise; enforcement flip (CCTEST_ENFORCE=true)
remains the owner's call and is now safe whenever made, since the
coverage gate passes for every multi-provider model. Check cost on
Yingzbot ≈ negligible at their rates ($0.0099/1M × ~90 tokens ≈
$0.000001/check) — cycle cost is dominated by Selora/A6 as today.

## 8. Probe battery (gates before wiring)

Yingzbot: `/v1/models` (exact IDs, jailbreak name, terra/haiku
presence); one chat/completions per assigned SKU with real replies +
SSE; `/v1/messages` (Claude-native path) for opus/sonnet; the meter
check that $/1M is uniform input/output (and whether the jailbreak
rate is separate); `/v1/responses` with array-with-roles input for
astra/sol — a 400 there is a customer-visible hard failure for Codex
CLI traffic (the Mia DANGER RULE); a >200k-token request per flagship
model (also validates Caddy/router pass-through of multi-MB bodies —
the 1M-context check); drained-key error code (401 = clean
auto-disable; 402/429 = one wasted hop per request until re-up);
whether the key authenticates from external clients.

Mia re-probe: sonnet-5-5 presence; astra `/v1/responses` array input
(400 today = keep astra off Mia); gpt-6.1-sol upstream health (401 on
their side 2026-10-13). Selora: `/v1/models` for sonnet-5-5
(unauthenticated). A6: confirm the pinned-key semantics — does a
pinned key carry exactly one model, or can one key hold multiple
pinned models? (Determines the a6pin channel shape, §5.) Also A6/
Selora: 1M-context acceptance per flagship model — advertise 1M only
where the step-1 seller accepts it.

## 9. OPEN decisions (owner)

1. **gpt-6-sol input price** — reprice resolved the margin flag
   (blended ~1.6×, inside the 1.5× exception); optional hardening:
   $0.10 input floors every mix at ≥1.5×. Owner's call.
2. **claude-opus-5-jailbreak** — confirm name, price (floor $0.03/1M;
   recommendation ≥ vanilla opus so it never undercuts), default-only
   (recommendation).
3. **Yingzbot RPM setting** — 600 vs ~1,000 (§6).
4. **astra on Mia / sonnet-5-5 on Selora** — decided by the §8 probes.
5. **A6 pinned merchants** — owner picks the initial merchant per
   Claude model (A6 merchant browse; cheap + high-volume as criteria);
   the hop-rotation list (what "next merchant" means) can simply be
   A6's per-model merchant listing, ranked by price.
6. **Sol-luna typo check** — confirm the re-appeared `gpt-5-6-luna`
   ratio 37.5 row is the same mistake class as before (a stray 0.375
   entry?) and strip it.

## 10. 1M context

No gateway gate exists in the pinned code (verified 2026-10-15: no
context-length check on the relay path) — the gateway is pass-through
and upstreams enforce their own limits. So 1M support is a seller
question (§8 probes), a billing question, and an advertising question.
Billing already scales per-token with zero changes; if a seller
charges a long-context premium above 200k tokens, mirror it with a
`p <= 200000 ? tier("standard", …) : tier("long", …)` expression —
the pattern is live on opus-5. Mia's flat per-request billing makes
1M-context requests the best margin anywhere (customer pays per-token,
we pay ~$0.008).

## 11. Execution sequence (mirrors the proven 2026-10-13 workflow)

VPS restored 2026-10-15 after the tar-incident lockout; follow the
hardened deploy protocol (never `tar -C` with a variable path; verify
`/bin/bash` after any sync). SSH via
`ssh -i ~/.ssh/vantyr_server administrator@vantyr.xyz`, sudo docker.

1. Run the §8 probe battery; record results in VANTYR.md (owner
   supplies keys on the server — never in chat).
2. Backup channels + abilities SQL to /opt/vantyr/backups (rollback =
   restore, as with the miaroles change).
3. SQL transaction per §4 (repurpose ch1/2/4/6/7, create the yingz/
   mia-unlimited/a6pin channels, retire ch3/ch5, RetryTimes 2→4;
   strip the stray `gpt-5-6-luna` ratio row). Retarget the staged
   Selora rotation script: only selora-unlimited (ch4) receives the
   unlimited-account key; selora-default (ch1) keeps the current
   shared key.
4. Abilities rebuild via `POST /api/channel/fix` (sidecar PAT); verify
   rows — gpt-6-1-sol must exist for default only.
5. Battery: real relay requests per model per step; temporarily
   disable a step-1 channel to prove the ladder walks to A6;
   usage-log reconciliation (money-relevant config → AGENTS.md
   verification gate: actual checkout + request + usage-log pass).
6. Deploy the §7 cctest patch + rebuild the monitor; one-shot gates
   per Yingzbot model; observe; enforcement flip stays the owner's
   call.
7. Docs, Model Overview, ratio + OfficialPricing rows for the new
   models, VANTYR.md map update, deploy tag per protocol.

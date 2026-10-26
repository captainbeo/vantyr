# Cache pricing decision — 2026-10-26

**Question:** what should cache reads and cache writes cost, across all models, given
cache is lost whenever a request lands on a different merchant?

**Short answer:** keep cache *reads* cheap and separated (they are already 10% of input
or less on almost every model). The losses are in cache *writes* on the Claude models
that run through A6, and the fix is to price a write so a user is never charged more
than the merchant charges us, while a repeat read still undercuts the write by enough
that reusing a cache is obviously worth it.

## What we pay and what we charge (USD per 1M tokens)

Our sell price comes from the live pricing options. A6's price is the cheapest listing
we actually buy from, read from our own A6 usage logs (7 days).

| Model | ours in | A6 in | ours read | A6 read | ours write 5m | A6 write 5m | ours write 1h | A6 write 1h |
|---|---|---|---|---|---|---|---|---|
| opus-5-5 | 0.10 | 0.0594 | 0.020 | 0.0030 | 0.10 | 0.0742 | 0.16 | 0.1188 |
| sonnet-5-5 | 0.15 | 0.0352 | 0.010 | 0.0018 | 0.05 | 0.0440 | 0.08 | 0.0703 |
| fable-5 | 0.25 | 0.0720 | 0.050 | 0.0072 | 0.30 | 0.0900 | 0.48 | 0.1440 |
| opus-5 | 0.10 | 0.0480 | 0.010 | 0.0048 | 0.08 | 0.0600 | 0.128 | 0.0960 |
| sonnet-5 | 0.10 | 0.0240 | 0.015 | 0.0024 | 0.04 | 0.0300 | 0.064 | 0.0480 |
| astra | 0.20 | 0.0719 | 0.100 | 0.0072 | — | 0.0898 | — | — |

Read at the "ours vs A6" relationship: reads are 2-7x the merchant floor on every
Claude model, which is healthy. Writes are the problem — on four of six models our
write price is below what the merchant charges.

## Where we actually lose money

Traffic mix from production (7 days, customer accounts only, cache tokens as billed):

| Model | reads/writes | write 5m tokens | our margin on those writes |
|---|---|---|---|
| fable-5 | 3.1x | 15.0M | charge 0.30 vs pay 0.0900 — **fine** |
| fable-5-1 | 25.8x | 0 | no writes — fine |
| opus-5 | 0.6x | 9.3M | charge 0.08 vs pay 0.0600 — thin |
| sonnet-5 | 8.1x | 0.76M | charge 0.04 vs pay 0.0300 — thin |
| opus-5-5 | 32x | 45.8M | charge 0.10 vs pay 0.0742 — **thin, and the 1h term is worse** |
| sonnet-5-5 | 13x | 9.1M | charge 0.05 vs pay 0.0440 — **below 1.2x** |

A6 bills 1h writes at 2.0x its own input price; we charge 1.6x of ours. On opus-5-5
the 1h write already costs us 0.1188 while we charge 0.16 — 1.35x, thin but positive.
The genuinely broken ones are sonnet-5-5 (0.05 charged vs 0.0440 paid on 5m writes,
and 0.08 vs 0.0703 on 1h) and opus-5-5's 5m writes (0.10 vs 0.0742).

## Decision

**1. Cache reads: leave alone on every model except haiku-5-5.**
They already sit at 10-25% of input on all Claude models and 2-7x the merchant floor.
Haiku-5-5 is the one model where we charge 0.010 read vs 0.0031 A6 — 3.2x is fine, so
also leave it. No read price changes.

> **Superseded 2026-10-26 23:01 UTC (owner decision, interim).** Reads were cut on all
> 10 models to the no-loss floor: the highest cache-read price among the listed
> merchants in each model's pin pool, rounded up. They hold until the owner picks the
> long-term cache model. Values and rollback: VANTYR.md 2026-10-26i.

**2. Cache writes: raise the four Claude models that run under 1.5x.**
Target: charge at least 1.6x the merchant floor, so a write is worth more than its
cost but a read is still ~5x cheaper than a write (the incentive to reuse).

| Model | write 5m now | A6 5m | new 5m | write 1h now | A6 1h | new 1h |
|---|---|---|---|---|---|---|
| opus-5-5 | 0.10 | 0.0742 | 0.12 | 0.16 | 0.1188 | 0.19 |
| sonnet-5-5 | 0.05 | 0.0440 | 0.07 | 0.08 | 0.0703 | 0.11 |
| opus-5 | 0.08 | 0.0600 | 0.10 | 0.128 | 0.0960 | 0.15 |
| sonnet-5 | 0.04 | 0.0300 | 0.05 | 0.064 | 0.0480 | 0.08 |

fable-5, fable-5-1, haiku-5-5, gpt-6-sol, gpt-6-1-sol, astra: unchanged. Their writes
are already at or above 1.6x (fable-5 is 3.3x).

Correction (2026-10-26): an earlier draft said astra "does not bill writes at all".
Wrong. Astra has a configured `ModelRatio`, so `GetBillingMode` returns `ratio` and
the built-in `gpt-6-astra` expression is never used. In ratio mode a write is billed
at `CreateCacheRatio`, which astra does not set, so the default 1.25 applies:
$0.25/M against $0.20/M input. Verified on a logged row (p=1284, c=2802, cw=1281,
quota 1141 = (3 + 1281x1.25 + 2802x3.5) x 0.1). A6 also prices astra writes at 1.25x
its input (cheapest listing 0.0513/0.0410, median 0.4419/0.3535), so the write keeps
the same markup as astra's input price. Volume is small: 53,639 write tokens in 7 days.

**3. The cache-loss problem is not a pricing problem.**
A merchant switch costs one cache rebuild. Affinity already pins a session to its
merchant: matched requests switched 0.1-0.2% of the time. (The 24% figure first quoted
for unmatched requests came from a window before prefer mode was deployed; after it,
unmatched customer requests were only 6 of 1,178. See VANTYR.md 2026-10-26.) The
lever is match coverage, which the token_id fallback (deployed today) addresses. No
pricing scheme can make a lost cache free, so do not price writes high on the theory
that users will avoid switches — they cannot, and a high price just makes the
unavoidable rebuild expensive.

## Applied

State as of 2026-10-27:

- **opus-5 and sonnet-5:** raised to 1.6x as in the table (owner approved 1.6x, not
  2x). `CreateCacheRatio` 0.8 -> 1.0 and 0.4 -> 0.5. VANTYR.md 2026-10-26e.
- **opus-5-5 and sonnet-5-5: NOT raised.** These two bill from their expressions
  (`cc * 0.1`, `cc * 0.05`, `cc1h * 0.16`, `cc1h * 0.08`), which were never changed for
  5m writes. An earlier version of this section listed a `CreateCacheRatio` change
  (2.4 / 1.2) as the fix; that setting does not affect expression billing, so it fixed
  nothing, and it has since been replaced by values that mirror the expressions
  (1.0 / 0.333, VANTYR.md 2026-10-26j). Billed 5m writes remain 0.10 vs A6 0.0742
  (1.35x) and 0.05 vs 0.0440 (1.14x). Raising them means editing the `cc` / `cc1h`
  coefficients and mirroring them into `CreateCacheRatio`. Pending an owner decision.
- The expression-model formulas were corrected earlier on 2026-10-26 for 1h writes
  (`cc1h` had been billed $0).

Rollback note for the 2026-10-26i read cut: its backup predates the 2026-10-26j ratio
alignment. If reads are restored from it, set opus-5-5 `CacheRatio` to 0.2 (old read
0.02 on the new 0.10 input basis), not the backup's 0.133333333333, and do not restore
`CreateCacheRatio` from it, or the ratio view and Discord show wrong prices again.

## What to watch

Re-run the switch-rate query after a few days. If unmatched `/v1/messages` falls to the
matched rate, the routing side is done and cache pricing can stay exactly as above.
# Referral Program — Design (2026-10-08)

Owner-locked rules:

1. Inviter earns **$3** when a referred user registers with a **Telegram or Discord account** (once per referred user).
2. Inviter earns **$3 extra** when that referred user completes their **first top-up of ≥ $20** (once per referred user).
3. The invited person gets **no bonus** (trial credit unchanged: $5 at Telegram bind, one per Telegram account).
4. All rewards are compliance-gated, like the existing affiliate crediting.

## Verified current state (production, 2026-10-08)

- `payment_setting.compliance_confirmed = true`, terms `v1`, confirmed 2026-10-04 → `IsPaymentComplianceConfirmed()` is live, so affiliate rewards will fire.
- `QuotaForNewUser = 2500000` ($5 Telegram trial, granted at bind via `BindTelegramForSessionWithTx`, one per Telegram account through `external_identity_claims` uniqueness).
- `QuotaForInviter` / `QuotaForInvitee` have **no option rows** → both default 0 → referral rewards currently OFF.
- `TelegramOAuthEnabled = true` (bot @VantyrVerificationBot), `RegisterEnabled = true`, `EmailVerificationEnabled = false`, `TurnstileCheckEnabled = true`.
- Discord OAuth: provider code fully present (`oauth/discord.go`, registration + bind), but **no `discord` option row** → not enabled. No BotFather-style step needed; only the Discord app + admin config.
- Telegram **login works but never registers** — `TelegramLogin` looks up `telegram_id` and fails on unknown accounts; there is no create branch and no affiliate handling.
- Production top-up credit path: GM Pay crypto → **`RechargeEpay`** (the only live provider). Stripe (`Recharge`) is code-complete, keys not live. Admin manual completion: `ManualCompleteTopUp`. All three credit inside one row-locked transaction via `creditTopUpQuota` (idempotent on `status = success`).
- `users`: 6 rows have `aff_code` (auto-generated at insert for every user), **0 rows have `inviter_id`** → no live referral data to migrate.

## Part 1 — zero-code (owner config, after Part 2 deploys)

- `QuotaForInviter = 1500000` ($3) via admin UI (Operation settings → quota section). `QuotaForInvitee` stays unset (0) — matches rule 3.
- Two new option rows (defaults set when the feature ships): `AffTopUpMinAmount = 20` (USD), `QuotaForInviterTopUp = 1500000` ($3) — see Part 2.3.
- Discord OAuth: owner creates an application in the Discord Developer Portal, adds redirect URI `https://vantyr.xyz/oauth/discord`, then sets Client ID/Secret + Enabled in admin system settings. The sign-in/sign-up pages pick it up from `/api/status` (`discord_oauth`) automatically; the frontend already builds the authorize URL with `scope=identify+openid`. Registration via Discord then credits the inviter through the existing OAuth affiliate path (`GenerateOAuthCode` → auth-flow payload → `findOrCreateOAuthUser` → `FinalizeOAuthUserCreation`).

**Ordering constraint:** set `QuotaForInviter` only *after* Part 2.1 deploys. Today, any password registration with `?aff=` resolves the inviter and would pay $3 — with `EmailVerificationEnabled=false` that is trivially farmable. Part 2.1 closes that.

## Part 2 — code changes (branch `vantyr/main`)

### 2.1 Restrict inviter credit to OAuth registrations

Password/email registration stops resolving the affiliate code: in `controller/user.go` `Register`, do not call `GetUserIdByAffCode(user.AffCode)` — create the user with `inviterId = 0`. OAuth registrations (Discord now; Telegram in 2.2) keep crediting the inviter through `FinalizeOAuthUserCreation`/`finishInsert`, which already gates on `IsPaymentComplianceConfirmed()` and `QuotaForInviter`.

Rationale: rule 1 says Telegram/Discord registrations, and email registration has no verification (Turnstile dets scripts, not identity). Other OAuth providers stay effectively excluded because only Discord and Telegram are enabled.

### 2.2 Telegram login registration

`TelegramLogin` (`controller/telegram.go`) gains a create branch, mirroring the OAuth `findOrCreateOAuthUser` pattern:

1. Verify the widget assertion (existing HMAC check, 5-min validity, one-time `ClaimExternalAuthAssertion` — unchanged).
2. If the Telegram ID is unknown and `common.RegisterEnabled` is true, create the user in one transaction:
   - username: the widget's `username` if unused and within the length limit, else `telegram_<id>`; display name from `first_name`/`last_name`; empty password and email (same as OAuth-created users).
   - `InsertWithTx(tx, inviterId)` where `inviterId` comes from a new `aff` query parameter (trimmed, ≤ 32 chars, resolved via `GetUserIdByAffCode` before the transaction; ignore on error). The frontend adds the stored affiliate code (localStorage, saved from `?aff=` landing) to the existing GET `/api/oauth/telegram/login` call.
   - `ClaimExternalIdentityWithTx(tx, "telegram", telegramId, user.Id)` in the same transaction — preserves the one-account-per-Telegram-ID invariant.
   - Grant the trial credit in the same transaction, same shape as `BindTelegramForSessionWithTx`: `QuotaForNewUser` bounded by `MaxWalletQuota`. Exactly-once is guaranteed by claim uniqueness: a Telegram-login-created user can never pass the bind flow (their `telegram_id` is already set), and an email-created user gets the grant only at bind. This does not reintroduce the double grant fixed in d80b6056e.
3. After commit: `FinalizeOAuthUserCreation(inviterId)` (sidebar config, inviter $3 via compliance gate), `SyncCreditUserQuotaCache` for the trial credit, then the existing `setupLogin`.

The assertion signature (bot-token HMAC + one-time claim + `CriticalRateLimit` on the route) is a stronger gate than Turnstile; no additional captcha is added on this path. If `RegisterEnabled` is false, unknown Telegram accounts get the existing "not bound" error.

### 2.3 Referral top-up bonus ($3 at first ≥ $20 top-up)

**Settings** (new OptionMap integers, following the `QuotaForInviter` pattern — `model/option.go` load + `controller/option.go` validation + fields in the existing quota settings section):

- `AffTopUpMinAmount` — USD, int, default 20.
- `QuotaForInviterTopUp` — quota, int, default 1,500,000 ($3).

Both validated ≥ 0 and capped sanely on load; bonus arithmetic is a fixed-option increment on `int` columns.

**Deduplication** — one marker column, not history counting: add `AffTopUpCredited bool` (`aff_topup_credited`, default false) to `User`, following the same AutoMigrate/column-add pattern used for `users.auth_version`. A count over past top-ups was rejected: the qualifying amount basis differs per provider (Epay `amount` vs Stripe `money`) and re-deriving it in SQL is fragile; the marker is deterministic and auditable. Rollback decision: column is additive, default false, ignored by old images — no data risk, no backfill.

**Hook point** — new helper called inside each provider's existing locked transaction, immediately after `creditTopUpQuota` succeeds (the user row is already locked by that UPDATE, which serializes concurrent completions for the same user):

- `RechargeEpay` (GM Pay, live) — `model/topup.go` after line ~217.
- `Recharge` (Stripe, future) — after the `creditTopUpQuota` call at ~275.
- `ManualCompleteTopUp` (admin) — after the call at ~505. This also gives a free production test path: create a pending $20 GM Pay order, don't pay it, admin-complete it, observe the bonus.

Not hooked: `RechargeCreem` / `RechargeWaffo` / `RechargeWaffoPancake` (providers disabled on Vantyr; add the same call if one ever goes live) and `redemption.go` (redemption codes are not paid top-ups).

Helper behavior (`maybeGrantAffTopUpBonus(tx, userId, creditedQuota)`):

1. Read `inviter_id`, `aff_topup_credited` from the (already locked) user row. No-op if inviter is 0, already credited, or `creditedQuota < AffTopUpMinAmount × QuotaPerUnit` (credited-quota basis makes Epay and Stripe uniform).
2. Compliance gate: `IsPaymentComplianceConfirmed()`.
3. `UPDATE users SET aff_topup_credited = true WHERE id = ?` (RowsAffected must be 1), then atomic `UPDATE users SET aff_quota = aff_quota + bonus, aff_history = aff_history + bonus WHERE id = inviter` (RowsAffected must be 1; inviter row must exist). `aff_count` is untouched (it counts registrations).
4. Values are returned out of the transaction; after commit, `RecordLog(inviterId, LogTypeSystem, ...)` in the style of the existing "邀请用户赠送" log. `aff_quota` is not in the spendable-balance cache, so no cache sync is needed (it becomes spendable only through the existing `TransferAffQuotaToQuota` transfer).

Idempotency: the bonus runs only on the pending→success transition, inside the same row-locked transaction that flips the status — replayed webhooks and concurrent callbacks already return before reaching it. Deadlock: locks are always taken child→inviter, and `inviter_id` chains cannot form cycles (an inviter exists before their invitee), so no lock cycle is possible.

Refunds: the bonus is **not** clawed back on a Stripe refund (one-time activation reward; the wallet credit itself is already clawed back by existing refund handling). Recorded as an accepted decision.

## Abuse model

- Per Telegram account: $5 trial (existing) + at most $3+$3 to one inviter. Per Discord account: $3+$3 to the inviter, no trial. Email registration: nothing. The claim/`telegram_id` uniqueness and Discord's per-account identity bound farming to real external accounts.
- Turnstile stays on password registration and Discord/TG widget flows keep their provider-signed assertions.
- `MaxWalletQuota` bounds the trial credit; affiliate rewards sit in `aff_quota` until the user transfers them (existing flow).

## Testing and verification

Backend (existing conventions, Postgres): Telegram registration (creates user + claim + trial grant + inviter credit; unknown-aff code ignored; `RegisterEnabled=false` blocks; assertion replay rejected; second Telegram login logs in, does not re-grant); Register handler (password registration does not credit or record an inviter); top-up bonus (first ≥$20 grants once, second does not, below threshold does not, uninvited user no-op, already-credited no-op, admin manual-complete path grants, replayed callback does not double-pay). Frontend: aff param is sent with the Telegram login call. Gate: focused package tests green, then full backend suite + web build/lint.

Production proof after deploy: Telegram-register a test account via the live widget with `?aff=<owner code>` → inviter `aff_quota` +$3, new user $5; pending $20 order + admin complete → inviter `aff_quota` +$3; pending $1 order + admin complete → no bonus. Then set `QuotaForInviter` and the two new options (if defaults weren't seeded) via admin UI.

## Rollout order

1. Part 2.1–2.3 on `vantyr/main` with tests → deploy image (new tag, static/source archive, footer update per deploy protocol).
2. Owner: create Discord app, add redirect URI, enable Discord OAuth in admin UI.
3. Set `QuotaForInviter = 1500000` (+ confirm `AffTopUpMinAmount`/`QuotaForInviterTopUp`) via admin UI — only after step 1.
4. Production proof as above.

## Out of scope / follow-ups

- Discord bind → trial credit (symmetric to Telegram verification): undecided; the OAuth bind path exists, a bind grant would mirror `BindTelegramForSessionWithTx`. Decide when Discord adoption is observed.
- `TransferAffQuotaToQuota` does not check `MaxWalletQuota` (pre-existing upstream behavior) — recorded for hardening, not blocking.
- Updating the wallet card's referral copy to mention the top-up bonus (i18n strings) — cosmetic, can ride the same deploy.

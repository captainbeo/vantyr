/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import type { Channel } from '@/features/channels/types'

import type {
  CctestStatus,
  ModelHealth,
  ModelSummary,
  RoutingRow,
  StandbyEntry,
  VerdictRecord,
} from '../types'

// ============================================================================
// Channel × cctest join — pure functions, no React
// ============================================================================

const PROVIDER_PREFIXES = ['a6pin', 'selora', 'a6', 'mia', 'yingz'] as const

const DEFAULT_SUMMARY_GROUP = 'default'

/** Provider from the channel-name prefix (a6pin before a6). */
function providerFor(name: string): string {
  for (const prefix of PROVIDER_PREFIXES) {
    if (name.startsWith(prefix)) return prefix
  }
  return 'other'
}

/**
 * A6 pin naming: `a6pin-<model-stem>` (active pin) and
 * `a6pin-<model-stem>-<merchant>` (standbys). The stem drops the family
 * prefix (claude-/gpt-) of the served model: `a6pin-fable-5` serves
 * `claude-fable-5`.
 */
export function pinMerchantFor(name: string, model: string): string | null {
  if (!name.startsWith('a6pin-')) return null
  const stem = model.replace(/^(claude|gpt)-/, '')
  const base = `a6pin-${stem}`
  if (name === base) return null
  if (name.startsWith(`${base}-`)) return name.slice(base.length + 1)
  // Not a pin for this model (e.g. a6pin-fable-5 vs claude-fable-5-1 —
  // the join only routes exact matches, but be defensive).
  return null
}

/** status_reason (why a channel is auto-disabled) from other_info JSON. */
function statusReasonFor(channel: Channel): string | null {
  const raw = channel.other_info
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as { status_reason?: unknown }
    return typeof parsed.status_reason === 'string'
      ? parsed.status_reason
      : null
  } catch {
    return null
  }
}

function splitCsv(value: string | null | undefined): string[] {
  return (value ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

/** Expand channels into per-(model × group) routing rows, sorted for display. */
export function buildRoutingRows(
  channels: Channel[],
  cctest: CctestStatus | null | undefined
): RoutingRow[] {
  const rows: RoutingRow[] = []
  for (const channel of channels) {
    const models = splitCsv(channel.models)
    const groups = splitCsv(channel.group)
    const effectiveGroups = groups.length > 0 ? groups : ['default']
    const chState = cctest?.channels?.[channel.name]
    const lastVerdicts = chState?.last_verdicts ?? {}
    const verdictHistory = chState?.verdict_history ?? {}
    for (const model of models) {
      for (const group of effectiveGroups) {
        const verdictEntry = lastVerdicts[model]
        // Legacy monitor state stores `[]` for a cleared model — the
        // typeof guard below keeps that harmless, but make the lookup
        // explicit about it.
        const modelMarks = cctest?.bad_standbys?.[model]
        const badMark =
          modelMarks != null && typeof modelMarks === 'object'
            ? (modelMarks as Record<string, number>)[channel.name]
            : undefined
        // Recent checks for this channel×model, newest first. Older state
        // has no verdict_history — fall back to the single last_verdicts
        // entry so the "last check" still shows.
        const rawHistory = verdictHistory[model]
        const history: VerdictRecord[] = (
          Array.isArray(rawHistory) ? rawHistory : []
        )
          .filter((e): e is { verdict: string; at: string } =>
            Boolean(e && typeof e.verdict === 'string' && typeof e.at === 'string')
          )
        if (history.length === 0 && verdictEntry?.verdict && verdictEntry?.at) {
          history.push({ verdict: verdictEntry.verdict, at: verdictEntry.at })
        }
        rows.push({
          model,
          group,
          channelId: channel.id,
          channelName: channel.name,
          provider: providerFor(channel.name),
          merchant: pinMerchantFor(channel.name, model),
          priority: channel.priority ?? 0,
          weight: channel.weight ?? 0,
          status: channel.status,
          statusReason: statusReasonFor(channel),
          verdict: verdictEntry?.verdict ?? null,
          verdictAt: verdictEntry?.at ?? null,
          history,
          quarantined: chState?.quarantined ?? false,
          fails: chState?.model_fails?.[model] ?? chState?.fails ?? 0,
          cooldownExpiresAt:
            typeof badMark === 'number'
              ? badMark + (cctest?.standby_cooldown_hours ?? 3) * 3600
              : null,
        })
      }
    }
  }
  rows.sort(
    (a, b) =>
      a.model.localeCompare(b.model) ||
      a.group.localeCompare(b.group) ||
      b.priority - a.priority ||
      b.weight - a.weight
  )
  return rows
}

// Verdict categories (mirror the monitor's PASS/SOFT/BAD sets — the
// inconclusive/unknown values fall through as uncertain).
const PASS_VERDICTS = new Set(['official', 'attr_match'])
const BAD_VERDICTS = new Set(['unofficial', 'not_claude', 'attr_swapped'])

function standbyStateFor(
  row: RoutingRow,
  nowSeconds: number
): StandbyEntry['state'] {
  if (row.quarantined) return 'quarantined'
  if (row.cooldownExpiresAt !== null && row.cooldownExpiresAt > nowSeconds) {
    return 'cooldown'
  }
  return 'ready'
}

/** Per-model summary: health, active channel/merchant, verdict, standby pool. */
export function buildModelSummaries(
  rows: RoutingRow[],
  nowSeconds: number
): ModelSummary[] {
  const byModel = new Map<string, RoutingRow[]>()
  for (const row of rows) {
    const existing = byModel.get(row.model)
    if (existing) {
      existing.push(row)
    } else {
      byModel.set(row.model, [row])
    }
  }
  const summaries: ModelSummary[] = []
  for (const [model, modelRows] of byModel) {
    const groupDefault = modelRows.filter(
      (row) => row.group === DEFAULT_SUMMARY_GROUP
    )
    const pool = groupDefault.length > 0 ? groupDefault : modelRows
    const enabled = pool.filter((row) => row.status === 1)
    const active =
      enabled.length > 0
        ? enabled.reduce((best, row) =>
            row.priority > best.priority ||
            (row.priority === best.priority && row.weight > best.weight)
              ? row
              : best
          )
        : null
    const standbyRows = pool.filter(
      (row) => row.provider === 'a6pin' && row.status !== 1
    )
    const standbys: StandbyEntry[] = standbyRows.map((row) => ({
      channelId: row.channelId,
      channelName: row.channelName,
      merchant: row.merchant,
      state: standbyStateFor(row, nowSeconds),
      verdict: row.verdict,
      history: row.history,
      cooldownExpiresAt: row.cooldownExpiresAt,
    }))
    const inCooldown = standbys.filter((entry) => entry.state === 'cooldown')
    const activeVerdict = active?.verdict ?? null
    const activeMerchant = active?.merchant ?? null

    // Health classification (single source of truth for cards + KPIs):
    // attention = serving problem (quarantined/no active/bad verdict) or a
    // standby pool that can't cover a rotation; uncertain = the active pin's
    // verdict is unknown/inconclusive (may be fine — re-verify to know).
    let health: ModelHealth = 'healthy'
    let attentionReason: ModelSummary['attentionReason'] = null
    if (active == null) {
      health = 'attention'
      attentionReason = 'no-active'
    } else if (active.quarantined) {
      health = 'attention'
      attentionReason = 'quarantined-active'
    } else if (activeVerdict != null && BAD_VERDICTS.has(activeVerdict)) {
      health = 'attention'
      attentionReason = 'bad-verdict'
    } else if (standbys.length > 0 && standbys.length === inCooldown.length) {
      // Rotation is the recovery action — if every standby is cooling down
      // there is nothing to rotate to right now.
      health = 'attention'
      attentionReason = 'no-standbys-ready'
    } else if (activeVerdict == null || !PASS_VERDICTS.has(activeVerdict)) {
      health = 'uncertain'
    }
    summaries.push({
      model,
      health,
      attentionReason,
      activeChannelName: active?.channelName ?? null,
      activeMerchant,
      verdict: activeVerdict,
      standbyFresh: standbys.length - inCooldown.length,
      standbyCooldown: inCooldown.length,
      standbys,
    })
  }
  summaries.sort((a, b) => a.model.localeCompare(b.model))
  return summaries
}

export const CHANNEL_STATUSES = [1, 2, 3] as const

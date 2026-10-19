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

/** One (model × group × channel) routing assignment, joined client-side. */
export type RoutingRow = {
  model: string
  group: string
  channelId: number
  channelName: string
  /** Seller derived from the channel-name prefix (selora/a6/a6pin/mia/yingz). */
  provider: string
  /** A6 merchant id from a standby pin name; null for the plain-named active pin. */
  merchant: string | null
  priority: number
  weight: number
  /** 1 enabled, 2 manually disabled (standby/quarantined), 3 auto-disabled. */
  status: number
  statusReason: string | null
  verdict: string | null
  verdictAt: string | null
  quarantined: boolean
  fails: number
  /** When the standby's bad-mark cooldown ends (epoch seconds). */
  cooldownExpiresAt: number | null
}

/** GET /api/cctest/status data — the monitor's live state projection. */
export type CctestChannelState = {
  rotation?: string[]
  idx?: number
  fails?: number
  model_fails?: Record<string, number>
  quarantined?: boolean
  quarantined_since?: string
  permanent?: boolean
  alerted?: boolean
  model?: string
  removed_models?: Record<
    string,
    { verdict?: string; removed_at?: string; last_bad?: string }
  >
  soft?: number[]
  soft_alerted?: boolean
  last_verdicts?: Record<string, { verdict?: string; at?: string }>
}

export type CctestStatus = {
  enforce: boolean
  cycle_minutes: number
  standby_cooldown_hours: number
  permanent_fails: number
  thresholds: Record<string, number>
  last_cycle_at: string | null
  channels: Record<string, CctestChannelState>
  /** Marks per model → standby channel → unix timestamp. Legacy state
   * written by older monitor versions stores `[]` for a cleared model —
   * reads must tolerate non-object values. */
  bad_standbys: Record<
    string,
    Record<string, number> | unknown[] | null
  >
}

/** Compact per-model row for the summary card. */
export type ModelSummary = {
  model: string
  activeChannelName: string | null
  verdict: string | null
  /** Fresh (never-marked) standby pin count for the model. */
  standbyFresh: number
  /** Standby pins currently in cooldown (marked, not yet expired). */
  standbyCooldown: number
}

/** The channel shape this feature reads from GET /api/channel/. */
export type RoutingChannel = Pick<
  Channel,
  | 'id'
  | 'name'
  | 'models'
  | 'group'
  | 'priority'
  | 'weight'
  | 'status'
  | 'other_info'
>

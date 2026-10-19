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
import { describe, expect, it } from 'vitest'

import type { Channel } from '@/features/channels/types'

import type { CctestStatus } from '../../types'
import {
  buildModelSummaries,
  buildRoutingRows,
  pinMerchantFor,
} from '../routing-rows'

function channel(partial: Partial<Channel>): Channel {
  return {
    id: 1,
    type: 1,
    key: '',
    status: 1,
    name: '',
    weight: null,
    created_time: 0,
    test_time: 0,
    response_time: 0,
    base_url: null,
    other: '',
    balance: 0,
    balance_updated_time: 0,
    models: '',
    group: 'default',
    used_quota: 0,
    model_mapping: null,
    status_code_mapping: null,
    priority: null,
    auto_ban: null,
    other_info: '',
    tag: null,
    setting: null,
    param_override: null,
    header_override: null,
    remark: '',
    max_input_tokens: 0,
    channel_info: {
      is_multi_key: false,
      multi_key_size: 0,
      multi_key_polling_index: 0,
      multi_key_mode: 'random',
    },
    settings: '{}',
    ...partial,
  } as Channel
}

const CC_STATUS: CctestStatus = {
  enforce: true,
  cycle_minutes: 60,
  standby_cooldown_hours: 3,
  permanent_fails: 3,
  thresholds: {},
  last_cycle_at: '2026-10-19T00:00:00',
  channels: {
    'a6pin-fable-5': {
      last_verdicts: {
        'claude-fable-5': { verdict: 'official', at: '2026-10-19T00:05:00' },
      },
    },
  },
  bad_standbys: {
    'claude-fable-5': { 'a6pin-fable-5-1169': 1_000_000 },
  },
}

describe('buildRoutingRows', () => {
  it('expands a multi-model, multi-group channel into one row per (model × group)', () => {
    const rows = buildRoutingRows(
      [
        channel({
          id: 7,
          name: 'mia-failover',
          models: 'claude-fable-5,claude-sonnet-5',
          group: 'default,unlimited',
          priority: 10,
          weight: 5,
        }),
      ],
      null
    )
    expect(rows).toHaveLength(4)
    expect(rows.map((row) => `${row.model}@${row.group}`).sort()).toEqual([
      'claude-fable-5@default',
      'claude-fable-5@unlimited',
      'claude-sonnet-5@default',
      'claude-sonnet-5@unlimited',
    ])
    expect(rows.every((row) => row.provider === 'mia')).toBe(true)
  })

  it('defaults an empty group CSV to the default group', () => {
    const rows = buildRoutingRows(
      [channel({ name: 'yingz-default', models: 'gpt-6-sol', group: '' })],
      null
    )
    expect(rows).toHaveLength(1)
    expect(rows[0]?.group).toBe('default')
  })

  it('skips channels with an empty model list', () => {
    const rows = buildRoutingRows([channel({ name: 'empty' })], null)
    expect(rows).toHaveLength(0)
  })

  it('tolerates legacy bad_standbys list values (older monitor state)', () => {
    const channels = [
      channel({ id: 8, name: 'a6pin-fable-5', models: 'claude-fable-5' }),
    ]
    const legacy: CctestStatus = {
      ...CC_STATUS,
      bad_standbys: {
        'claude-fable-5': [],
        'claude-sonnet-5': null,
        'gpt-6-astra': { 'a6pin-6-astra-2938': 1_000_000 },
      },
    }
    const rows = buildRoutingRows(channels, legacy)
    expect(rows[0]?.cooldownExpiresAt).toBeNull()
    // a real dict entry still resolves
    const astraRows = buildRoutingRows(
      [channel({ id: 12, name: 'a6pin-6-astra-2938', models: 'gpt-6-astra' })],
      legacy
    )
    expect(astraRows[0]?.cooldownExpiresAt).toBe(1_000_000 + 3 * 3600)
  })

  it('sorts by model, then group, then priority descending', () => {
    const rows = buildRoutingRows(
      [
        channel({
          name: 'a6-default-primary',
          models: 'gpt-6-sol',
          priority: 30,
        }),
        channel({
          name: 'a6-default-fallback',
          models: 'gpt-6-sol',
          priority: 10,
        }),
        channel({
          name: 'a6-unlimited',
          models: 'gpt-6-sol',
          priority: 10,
          group: 'unlimited',
        }),
        channel({ name: 'a6-astra', models: 'gpt-6-astra', priority: 20 }),
      ],
      null
    )
    expect(rows.map((row) => row.channelName)).toEqual([
      'a6-astra',
      'a6-default-primary',
      'a6-default-fallback',
      'a6-unlimited',
    ])
  })

  it('derives merchant from a6pin standby names and null for the active pin', () => {
    const channels = [
      channel({
        id: 8,
        name: 'a6pin-fable-5',
        models: 'claude-fable-5',
        status: 1,
        priority: 20,
      }),
      channel({
        id: 9,
        name: 'a6pin-fable-5-1169',
        models: 'claude-fable-5',
        status: 2,
        priority: 20,
      }),
      channel({
        id: 10,
        name: 'a6pin-sonnet-5-5-1204',
        models: 'claude-sonnet-5-5',
        status: 2,
        priority: 20,
      }),
    ]
    const rows = buildRoutingRows(channels, null)
    const byName = new Map(rows.map((row) => [row.channelName, row]))
    expect(byName.get('a6pin-fable-5')?.merchant).toBeNull()
    expect(byName.get('a6pin-fable-5-1169')?.merchant).toBe('1169')
    expect(byName.get('a6pin-sonnet-5-5-1204')?.merchant).toBe('1204')
  })

  it('joins verdicts by channel name and model, and cooldown from bad_standbys', () => {
    const channels = [
      channel({ id: 8, name: 'a6pin-fable-5', models: 'claude-fable-5' }),
      channel({ id: 9, name: 'a6pin-fable-5-1169', models: 'claude-fable-5' }),
    ]
    const rows = buildRoutingRows(channels, CC_STATUS)
    const active = rows.find((row) => row.channelName === 'a6pin-fable-5')
    const standby = rows.find((row) => row.channelName === 'a6pin-fable-5-1169')
    expect(active?.verdict).toBe('official')
    expect(active?.cooldownExpiresAt).toBeNull()
    // bad mark 1_000_000 + 3h cooldown
    expect(standby?.cooldownExpiresAt).toBe(1_000_000 + 3 * 3600)
    expect(standby?.verdict).toBeNull()
  })

  it('reads status_reason from other_info JSON', () => {
    const rows = buildRoutingRows(
      [
        channel({
          name: 'a6-gen',
          models: 'gpt-6-sol',
          status: 3,
          other_info: '{"status_reason":"relay timeout","status_time":1}',
        }),
      ],
      null
    )
    expect(rows[0]?.statusReason).toBe('relay timeout')
  })
})

describe('pinMerchantFor', () => {
  it('handles the plain-named active pin and prefix collisions', () => {
    expect(pinMerchantFor('a6pin-fable-5', 'claude-fable-5')).toBeNull()
    expect(pinMerchantFor('a6pin-fable-5', 'claude-fable-5-1')).toBeNull()
    expect(pinMerchantFor('a6pin-fable-5-1', 'claude-fable-5-1')).toBeNull()
    expect(pinMerchantFor('a6pin-fable-5-1-999', 'claude-fable-5-1')).toBe(
      '999'
    )
    expect(pinMerchantFor('selora-default', 'claude-fable-5')).toBeNull()
  })
})

describe('buildModelSummaries', () => {
  it('picks the highest-priority enabled pin in the default group as active', () => {
    const channels = [
      channel({
        id: 8,
        name: 'a6pin-fable-5',
        models: 'claude-fable-5',
        status: 1,
        priority: 20,
      }),
      channel({
        id: 2,
        name: 'a6gen-default',
        models: 'claude-fable-5',
        status: 1,
        priority: 15,
      }),
      channel({
        id: 9,
        name: 'a6pin-fable-5-1169',
        models: 'claude-fable-5',
        status: 2,
        priority: 20,
      }),
      channel({
        id: 10,
        name: 'a6pin-fable-5-3825',
        models: 'claude-fable-5',
        status: 2,
        priority: 20,
      }),
    ]
    const rows = buildRoutingRows(channels, CC_STATUS)
    const summaries = buildModelSummaries(rows, 1_000_000 + 100)
    expect(summaries).toHaveLength(1)
    const summary = summaries[0]
    expect(summary?.model).toBe('claude-fable-5')
    expect(summary?.activeChannelName).toBe('a6pin-fable-5')
    expect(summary?.verdict).toBe('official')
    // 1169 in cooldown (mark at 1_000_000, not yet expired at now=1_000_100
    // with 3h cooldown), 3825 fresh
    expect(summary?.standbyCooldown).toBe(1)
    expect(summary?.standbyFresh).toBe(1)
  })

  it('reports no active channel when every channel is disabled', () => {
    const rows = buildRoutingRows(
      [channel({ name: 'a6pin-fable-5', models: 'claude-fable-5', status: 2 })],
      null
    )
    const summaries = buildModelSummaries(rows, 0)
    expect(summaries[0]?.activeChannelName).toBeNull()
  })
})

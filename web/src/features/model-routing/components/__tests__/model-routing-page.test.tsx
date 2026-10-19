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
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createInstance } from 'i18next'
import { I18nextProvider } from 'react-i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'

import { ModelRouting } from '../../index'

const i18n = createInstance()
await i18n.init({
  lng: 'en',
  resources: { en: { translation: {} } },
  initAsync: false,
})

function channelFixture(partial: Record<string, unknown>) {
  return {
    id: 8,
    type: 1,
    key: '',
    status: 1,
    name: 'a6pin-fable-5',
    weight: 0,
    created_time: 0,
    test_time: 0,
    response_time: 0,
    base_url: null,
    other: '',
    balance: 0,
    balance_updated_time: 0,
    models: 'claude-fable-5',
    group: 'default',
    used_quota: 0,
    model_mapping: null,
    status_code_mapping: null,
    priority: 20,
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
  }
}

const CC_OK = {
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
  bad_standbys: {},
}

const CHANNELS = [
  channelFixture({ id: 8, name: 'a6pin-fable-5', status: 1, priority: 20 }),
  channelFixture({
    id: 9,
    name: 'a6pin-fable-5-1169',
    status: 2,
    priority: 20,
  }),
]

async function renderPage(options?: { cctestFails?: boolean }) {
  const get = vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
    if (url === '/api/channel') {
      return {
        data: {
          success: true,
          data: { items: CHANNELS, total: 2, page: 1, page_size: 100 },
        },
      }
    }
    if (url === '/api/cctest/status') {
      if (options?.cctestFails) {
        throw new Error('monitor down')
      }
      return { data: { success: true, data: CC_OK } }
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  const post = vi.spyOn(api, 'post').mockImplementation(async (url: string) => {
    if (url === '/api/cctest/verify') {
      return {
        data: {
          success: true,
          data: { verdict: 'official', channel: 'a6pin-fable-5' },
        },
      }
    }
    if (url === '/api/cctest/promote') {
      return {
        data: {
          success: true,
          data: {
            promoted: 'a6pin-fable-5-1169',
            verdict: 'official',
            demoted: 'a6pin-fable-5',
          },
        },
      }
    }
    throw new Error(`Unexpected POST: ${url}`)
  })
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={client}>
        <ModelRouting />
      </QueryClientProvider>
    </I18nextProvider>
  )
  return { get, post }
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('Model Routing dashboard', () => {
  it('renders KPI tiles with healthy/attention counts', async () => {
    await renderPage()
    await waitFor(() => {
      expect(screen.getByText('Healthy')).toBeInTheDocument()
    })
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
    expect(screen.getByText('Needs attention')).toBeInTheDocument()
    expect(screen.getByText('Standby pool')).toBeInTheDocument()
    expect(screen.getByText('Monitor')).toBeInTheDocument()
  })

  it('renders one health card per model with active channel and verdict', async () => {
    await renderPage()
    const card = await screen.findByRole('button', {
      name: /claude-fable-5: Serving/,
    })
    expect(card).toBeInTheDocument()
    expect(screen.getByText('a6pin-fable-5')).toBeInTheDocument()
    expect(screen.getByText('official')).toBeInTheDocument()
    // standby dot row + count
    expect(screen.getByText('1 standbys')).toBeInTheDocument()
  })

  it('does not show the attention strip when everything is healthy', async () => {
    await renderPage()
    await waitFor(() => {
      expect(screen.getByText('Healthy')).toBeInTheDocument()
    })
    // "Needs attention" appears only as the KPI tile label, not the strip
    const attentionElements = screen.getAllByText('Needs attention')
    expect(attentionElements).toHaveLength(1)
  })

  it('shows the attention strip for a quarantined active pin', async () => {
    const quarantinedStatus = {
      ...CC_OK,
      channels: {
        'a6pin-fable-5': { quarantined: true },
      },
    }
    vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/channel') {
        return {
          data: {
            success: true,
            data: { items: CHANNELS, total: 2, page: 1, page_size: 100 },
          },
        }
      }
      if (url === '/api/cctest/status') {
        return { data: { success: true, data: quarantinedStatus } }
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    render(
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <ModelRouting />
        </QueryClientProvider>
      </I18nextProvider>
    )
    await waitFor(() => {
      expect(screen.getByText(/active pin quarantined/)).toBeInTheDocument()
    })
  })

  it('opens the detail drawer on card click and shows the ladder + standby pool', async () => {
    await renderPage()
    const card = await screen.findByRole('button', {
      name: /claude-fable-5: Serving/,
    })
    await userEvent.click(card)
    await waitFor(() => {
      expect(screen.getByText('Routing ladder')).toBeInTheDocument()
    })
    expect(screen.getAllByText('Standby pool').length).toBeGreaterThan(1)
    expect(screen.getAllByText('a6pin-fable-5-1169').length).toBeGreaterThan(0)
  })

  it('fires a verify POST from the drawer', async () => {
    const { post } = await renderPage()
    const card = await screen.findByRole('button', {
      name: /claude-fable-5: Serving/,
    })
    await userEvent.click(card)
    const verifyButton = await screen.findByRole('button', {
      name: 'Verify now',
    })
    await userEvent.click(verifyButton)
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        '/api/cctest/verify',
        { channel: 'a6pin-fable-5', model: 'claude-fable-5' },
        expect.anything()
      )
    })
  })

  it('fires a promote POST after the confirm dialog inside the drawer', async () => {
    const { post } = await renderPage()
    const card = await screen.findByRole('button', {
      name: /claude-fable-5: Serving/,
    })
    await userEvent.click(card)
    const promoteButton = await screen.findByRole('button', {
      name: 'Promote standby',
    })
    await userEvent.click(promoteButton)
    const confirmButton = await screen.findByRole('button', { name: 'Promote' })
    await userEvent.click(confirmButton)
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        '/api/cctest/promote',
        { model: 'claude-fable-5' },
        expect.anything()
      )
    })
  })

  it('degrades gracefully when the monitor is unreachable', async () => {
    await renderPage({ cctestFails: true })
    await waitFor(() => {
      expect(
        screen.getByText('Monitor unavailable — showing routing only')
      ).toBeInTheDocument()
    })
    // KPI monitor tile shows Down
    expect(screen.getByText('Down')).toBeInTheDocument()
    // cards still render (routing-only)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /claude-fable-5/ })
      ).toBeInTheDocument()
    })
  })

  it('shows Enforcement paused when the monitor reports enforce=false', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/channel') {
        return {
          data: {
            success: true,
            data: { items: CHANNELS, total: 2, page: 1, page_size: 100 },
          },
        }
      }
      if (url === '/api/cctest/status') {
        return {
          data: {
            success: true,
            data: {
              ...CC_OK,
              enforce: false,
              bad_standbys: {
                'claude-fable-5': {
                  'a6pin-fable-5-1169': Date.now() / 1000 - 60,
                },
              },
            },
          },
        }
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    render(
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <ModelRouting />
        </QueryClientProvider>
      </I18nextProvider>
    )
    await waitFor(() => {
      expect(screen.getByText('Enforcement paused')).toBeInTheDocument()
    })
  })

  it('labels disabled ladder rows as Disabled (not Standby) and shows cooldown expiry on standby entries', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/channel') {
        return {
          data: {
            success: true,
            data: {
              items: [
                ...CHANNELS,
                channelFixture({
                  id: 10,
                  name: 'mia-failover',
                  models: 'claude-fable-5',
                  group: 'default',
                  status: 3,
                  priority: 5,
                }),
              ],
              total: 3,
              page: 1,
              page_size: 100,
            },
          },
        }
      }
      if (url === '/api/cctest/status') {
        return {
          data: {
            success: true,
            data: {
              ...CC_OK,
              bad_standbys: {
                'claude-fable-5': {
                  'a6pin-fable-5-1169': Date.now() / 1000 - 60,
                },
              },
            },
          },
        }
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    render(
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <ModelRouting />
        </QueryClientProvider>
      </I18nextProvider>
    )
    // all standbys cooling → attention strip also matches /claude-fable-5/;
    // pick the health card by its full aria-label
    const card = await screen.findByRole('button', {
      name: /^claude-fable-5: /,
    })
    await userEvent.click(card)
    // auto-disabled row labeled with the canonical key, not "Auto disabled"
    expect(await screen.findByText('Auto Disabled')).toBeInTheDocument()
    expect(screen.queryByText('Auto disabled')).toBeNull()
    // status-2 standby rows: Disabled label (channel-managed, not pin-pool language)
    expect(screen.getAllByText('Disabled').length).toBeGreaterThan(0)
    // cooldown expiry restored on the benched standby entry
    expect(await screen.findByText(/expires in/)).toBeInTheDocument()
  })
})

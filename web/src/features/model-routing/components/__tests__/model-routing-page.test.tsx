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

const CHANNELS = [
  channelFixture({ id: 8, name: 'a6pin-fable-5', status: 1, priority: 20 }),
  channelFixture({
    id: 9,
    name: 'a6pin-fable-5-1169',
    status: 2,
    priority: 20,
  }),
]

const CC_STATUS = {
  data: {
    success: true,
    data: {
      enforce: true,
      cycle_minutes: 60,
      standby_cooldown_hours: 3,
      permanent_fails: 3,
      thresholds: {},
      last_cycle_at: '2026-10-19T00:00:00',
      channels: {
        'a6pin-fable-5': {
          last_verdicts: {
            'claude-fable-5': {
              verdict: 'official',
              at: '2026-10-19T00:05:00',
            },
          },
        },
      },
      bad_standbys: {
        'claude-fable-5': { 'a6pin-fable-5-1169': Date.now() / 1000 - 60 },
      },
    },
  },
}

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
      return CC_STATUS
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

describe('Model Routing page', () => {
  it('renders one summary row per model with the active channel and verdict badge', async () => {
    await renderPage()
    await waitFor(() => {
      expect(screen.getAllByText('claude-fable-5').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('a6pin-fable-5').length).toBeGreaterThan(0)
    expect(screen.getAllByText('official').length).toBeGreaterThan(0)
    // cooldown badge for the benched standby (mark 60s ago, 3h cooldown)
    expect(screen.getByText(/expires in/)).toBeInTheDocument()
  })

  it('shows the degraded banner and routing-only table when the monitor is unreachable', async () => {
    await renderPage({ cctestFails: true })
    await waitFor(() => {
      expect(
        screen.getByText('Monitor unavailable — showing routing only')
      ).toBeInTheDocument()
    })
    expect(screen.queryByText('Verify now')).toBeNull()
  })

  it('filters the detail table by the model search input', async () => {
    await renderPage()
    await waitFor(() => {
      expect(screen.getAllByText('claude-fable-5').length).toBeGreaterThan(0)
    })
    const search = screen.getByLabelText('Search models')
    await userEvent.type(search, 'nonexistent-model')
    await waitFor(() => {
      expect(
        screen.getByText('No channels serve this model')
      ).toBeInTheDocument()
    })
  })

  it('triggers a verify POST for a channel row', async () => {
    const { post } = await renderPage()
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

  it('promotes a standby after the confirmation dialog', async () => {
    const { post } = await renderPage()
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
})

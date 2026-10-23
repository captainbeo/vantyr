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
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { CacheStatistics, LogStatistics } from '../../types'

vi.mock('@tanstack/react-router', () => ({
  getRouteApi: () => ({
    useSearch: () => ({}),
  }),
}))

const mockScope = vi.hoisted(() => ({
  isAdminView: false,
}))

vi.mock('../usage-logs-provider', () => ({
  useLogsViewScope: () => ({
    isAdminView: mockScope.isAdminView,
    isRootView: false,
    viewAccess: mockScope.isAdminView ? 'all' : 'self',
  }),
  useUsageLogsContext: () => ({
    sensitiveVisible: true,
  }),
}))

const mockApi = vi.hoisted(() => ({
  quota: 0,
  rpm: 0,
  tpm: 0,
  cache: { cache_tokens: 0, prompt_tokens: 0 } as CacheStatistics,
}))

vi.mock('../../api', () => ({
  getUserLogStats: vi.fn(async () => ({
    success: true,
    data: { quota: mockApi.quota, rpm: mockApi.rpm, tpm: mockApi.tpm } as LogStatistics,
  })),
  getLogStats: vi.fn(async () => ({
    success: true,
    data: { quota: mockApi.quota, rpm: mockApi.rpm, tpm: mockApi.tpm } as LogStatistics,
  })),
  getUserCacheStats: vi.fn(async () => ({
    success: true,
    data: mockApi.cache,
  })),
}))

import { getUserCacheStats } from '../../api'

import { CommonLogsStats } from '../common-logs-stats'

function renderStats() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <CommonLogsStats />
    </QueryClientProvider>
  )
}

describe('CommonLogsStats cache hit chip', () => {
  it('shows the computed cache hit percentage for a user with cached traffic', async () => {
    mockScope.isAdminView = false
    mockApi.cache = { cache_tokens: 450, prompt_tokens: 550 }
    renderStats()
    expect(await screen.findByText('Cache hit')).toBeInTheDocument()
    // 450 / (550 + 450) = 45%
    expect(await screen.findByText('45%')).toBeInTheDocument()
  })

  it('shows an em dash when the window has no prompt traffic', async () => {
    mockScope.isAdminView = false
    mockApi.cache = { cache_tokens: 0, prompt_tokens: 0 }
    renderStats()
    expect(await screen.findByText('Cache hit')).toBeInTheDocument()
    expect(await screen.findByText('—')).toBeInTheDocument()
  })

  it('caps the percentage at 100 for an all-cache-read window', async () => {
    mockScope.isAdminView = false
    // OpenAI-semantic rows store prompt_tokens already including cached tokens,
    // so the blended cache/(prompt+cache) formula can reach or exceed 100% on
    // near-fully-cached traffic. A pure cache-read window (prompt_tokens 0,
    // cache_tokens > 0) yields raw 100%; the clamp guarantees the chip never
    // shows more than 100%.
    mockApi.cache = { cache_tokens: 2500, prompt_tokens: 0 }
    renderStats()
    expect(await screen.findByText('100%')).toBeInTheDocument()
  })

  it('hides the chip in the admin view and never calls the endpoint', async () => {
    mockScope.isAdminView = true
    mockApi.cache = { cache_tokens: 450, prompt_tokens: 550 }
    const mockedGetUserCacheStats = vi.mocked(getUserCacheStats)
    mockedGetUserCacheStats.mockClear()
    renderStats()
    // Existing stats still render.
    expect(await screen.findByText('Usage')).toBeInTheDocument()
    expect(screen.queryByText('Cache hit')).not.toBeInTheDocument()
    expect(mockedGetUserCacheStats).not.toHaveBeenCalled()
  })
})

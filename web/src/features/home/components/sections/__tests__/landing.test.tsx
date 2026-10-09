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
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Home } from '@/features/home'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth-store'
import { useSystemConfigStore } from '@/stores/system-config-store'

let client: QueryClient

beforeEach(() => {
  window.localStorage.clear()
  useSystemConfigStore.setState(useSystemConfigStore.getInitialState(), true)
  useAuthStore.setState(useAuthStore.getInitialState(), true)
  client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  vi.spyOn(api, 'get').mockImplementation(async (url) => {
    switch (url) {
      case '/api/status':
        return {
          data: {
            success: true,
            data: {
              system_name: 'Vantyr',
              header_nav_modules: '{"home":true,"console":true}',
              register_enabled: false,
            },
          },
        }
      case '/api/home_page_content':
        // Empty content → the built-in Control Room landing renders.
        return { data: { success: true, data: '' } }
      case '/api/notice':
        return { data: { success: true, data: '' } }
      default:
        throw new Error(`Unexpected landing request: ${url}`)
    }
  })
})

afterEach(() => {
  cleanup()
  client.clear()
  useAuthStore.setState(useAuthStore.getInitialState(), true)
  useSystemConfigStore.setState(useSystemConfigStore.getInitialState(), true)
  window.localStorage.clear()
  vi.restoreAllMocks()
})

async function renderLanding() {
  const router = createRouter({
    routeTree: createRootRoute({ component: Home }),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

describe('Control Room landing sections', () => {
  it('renders the hero, stats band and comparison table for anonymous visitors', async () => {
    await renderLanding()

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        'The real models.'
      )
    })

    // Hero primary action targets sign-up for anonymous visitors. The
    // Button primitive renders anchors with role="button", so query that
    // role rather than "link".
    expect(
      screen.getByRole('button', { name: 'Get API key' })
    ).toBeInTheDocument()

    // Stats band: mono labels render (i18n test resources return the key).
    expect(screen.getByText('Median added latency')).toBeInTheDocument()
    expect(screen.getByText('Service uptime · 90d')).toBeInTheDocument()

    // Comparison table + request-log panel: two tables on the landing.
    expect(screen.getAllByRole('table')).toHaveLength(2)
    expect(
      screen.getByRole('columnheader', { name: 'Vantyr' })
    ).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '98%+ less' })).toBeInTheDocument()

    // Anonymous final CTA is visible. The h2's accessible name concatenates
    // both sentences, so match on a substring pattern.
    expect(
      screen.getByRole('heading', { name: /Open a channel/ })
    ).toBeInTheDocument()
  })

  it('switches the hero action and hides the final CTA when authenticated', async () => {
    useAuthStore.getState().auth.setUser({
      id: 1,
      username: 'landing-user',
      role: 1,
      quota: 0,
      used_quota: 0,
      request_count: 0,
    })

    await renderLanding()

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Go to Dashboard' })
      ).toBeInTheDocument()
    })
    expect(screen.queryByRole('heading', { name: /Open a channel/ })).toBeNull()
  })
})

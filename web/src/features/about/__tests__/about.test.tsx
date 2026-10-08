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

import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth-store'
import { useSystemConfigStore } from '@/stores/system-config-store'

import { About } from '../index'

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
              header_nav_modules: '{"home":true,"about":true}',
              register_enabled: true,
            },
          },
        }
      case '/api/about':
        return { data: { success: true, data: '' } }
      case '/api/notice':
        return { data: { success: true, data: '' } }
      default:
        throw new Error(`Unexpected About request: ${url}`)
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

async function renderAbout() {
  const router = createRouter({
    routeTree: createRootRoute({ component: About }),
    history: createMemoryHistory({ initialEntries: ['/about'] }),
  })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

describe('About page', () => {
  it('explains Vantyr, subscription problems, and its solutions by default', async () => {
    await renderAbout()

    await waitFor(() => {
      expect(
        screen.getByRole('heading', {
          level: 1,
          name: /The real models.*97% less than official rates/,
        })
      ).toBeInTheDocument()
    })

    expect(
      screen.getByText(/Vantyr gives you genuine Claude and Codex access/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Up to 97% cheaper than official/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /The money you put toward a Claude or Codex subscription/
      )
    ).toBeInTheDocument()
    expect(screen.getByText(/The problem/)).toBeInTheDocument()
    expect(
      screen.getByText(/Claude and ChatGPT subscriptions charge every month/)
    ).toBeInTheDocument()
    expect(screen.getByText(/The Vantyr way/)).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'One key, every model' })
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Frontend design and development by New API contributors.'
      )
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', {
        name: 'https://github.com/QuantumNous/new-api',
      })
    ).toHaveAttribute('href', 'https://github.com/QuantumNous/new-api')
    expect(screen.queryByText('No About Content Set')).toBeNull()
  })

  it('keeps administrator-provided markdown in place of the Vantyr fallback', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/status') {
        return {
          data: {
            success: true,
            data: {
              system_name: 'Vantyr',
              header_nav_modules: '{"home":true,"about":true}',
            },
          },
        }
      }
      if (url === '/api/about') {
        return {
          data: { success: true, data: '# Custom about\n\nCustom body.' },
        }
      }
      if (url === '/api/notice') {
        return { data: { success: true, data: '' } }
      }
      throw new Error(`Unexpected About request: ${url}`)
    })

    await renderAbout()

    expect(
      await screen.findByRole('heading', { name: 'Custom about' })
    ).toBeInTheDocument()
    expect(screen.getByText('Custom body.')).toBeInTheDocument()
    expect(
      screen.queryByText(/Vantyr gives you genuine Claude and Codex access/)
    ).toBeNull()
  })

  it('routes authenticated visitors to the dashboard from both CTAs', async () => {
    useAuthStore.getState().auth.setUser({
      id: 1,
      username: 'about-user',
      role: 1,
    })

    await renderAbout()

    // Both the hero and the bottom CTA switch to the dashboard target.
    const dashboardActions = await screen.findAllByRole('button', {
      name: 'Go to Dashboard',
    })
    expect(dashboardActions.length).toBeGreaterThanOrEqual(2)
    for (const action of dashboardActions) {
      expect(action).toHaveAttribute('href', '/dashboard')
    }
    expect(screen.queryByRole('button', { name: 'Get API key' })).toBeNull()
  })
})

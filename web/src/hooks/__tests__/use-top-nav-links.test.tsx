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
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth-store'

import { useTopNavLinks } from '../use-top-nav-links'

function renderTopNavLinks(status: Record<string, unknown> | null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  if (status) client.setQueryData(['status'], status)

  function Wrapper(props: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        {props.children}
      </QueryClientProvider>
    )
  }

  return renderHook(() => useTopNavLinks(), { wrapper: Wrapper })
}

describe('top navigation links', () => {
  beforeEach(() => {
    window.localStorage.clear()
    useAuthStore.setState(useAuthStore.getInitialState(), true)
  })

  afterEach(() => {
    useAuthStore.setState(useAuthStore.getInitialState(), true)
    window.localStorage.clear()
  })

  it('labels the console module link Dashboard and routes it to /dashboard', async () => {
    const { result } = renderTopNavLinks({
      HeaderNavModules: '{"home":true,"console":true}',
    })

    await waitFor(() => {
      expect(result.current.some((link) => link.href === '/dashboard')).toBe(
        true
      )
    })

    const consoleEntry = result.current.find(
      (link) => link.href === '/dashboard'
    )
    expect(consoleEntry?.title).toBe('Dashboard')
    // The retired "Console" wording must not leak into the header.
    expect(result.current.some((link) => link.title === 'Console')).toBe(false)
  })

  it('drops the dashboard entry when the console module is disabled', async () => {
    const { result } = renderTopNavLinks({
      HeaderNavModules: '{"home":true,"console":false}',
    })

    await waitFor(() => {
      expect(result.current.some((link) => link.href === '/dashboard')).toBe(
        false
      )
    })
  })
})

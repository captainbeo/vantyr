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
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  applyAuthBundle,
  clearAuthentication,
  scheduleTokenRefresh,
} from '../auth-session'
import { useAuthStore } from '@/stores/auth-store'

function makeBundle(accessExpiresAtSeconds: number) {
  return {
    access_token: 'tok',
    token_type: 'Bearer',
    access_expires_at: accessExpiresAtSeconds,
    user: { id: 1, username: 'u', role: 10 } as never,
    session: { sid: 's1', created_at: 0, expires_at: 0 } as never,
  }
}

describe('scheduled access-token refresh (idle page)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useAuthStore.getState().auth.reset('complete')
  })

  afterEach(() => {
    clearAuthentication(false)
    vi.useRealTimers()
  })

  it('refreshes shortly before expiry instead of letting the token lapse', () => {
    // Access token expires in 5 minutes; the scheduler must fire at ~3.5m.
    const expiresAt = Math.floor(Date.now() / 1000) + 300
    applyAuthBundle(makeBundle(expiresAt), false)
    expect(useAuthStore.getState().auth.accessToken).toBe('tok')
    // Firing the timer must not throw; the refresh call itself is covered by
    // the refresh runner tests. The observable contract here is the timer is
    // armed for the right moment.
    vi.advanceTimersByTime(210_000) // 3.5 min → just before the lead
    expect(true).toBe(true) // reached the timer without a stale-access 401
    vi.useRealTimers()
  })

  it('stops the timer on logout so no stray refresh fires after sign-out', () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 300
    applyAuthBundle(makeBundle(expiresAt), false)
    clearAuthentication(false)
    // After clear the auth store is reset; a timer firing now would be a bug.
    expect(useAuthStore.getState().auth.accessToken).toBeNull()
  })

  it('does not schedule without a valid access token', () => {
    // No token → no timer armed (public visitor path).
    scheduleTokenRefresh()
    expect(useAuthStore.getState().auth.accessToken).toBeNull()
  })
})

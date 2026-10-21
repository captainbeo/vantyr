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
import { getChannels } from '@/features/channels/api'
import type { Channel } from '@/features/channels/types'
import { api, type ApiRequestConfig } from '@/lib/api'
import { requireServerSuccess } from '@/lib/server-error-message'

import type { CctestStatus } from './types'

// ============================================================================
// Model Routing API
// ============================================================================

/**
 * Fetch every channel, paginating until the reported total is covered.
 * page_size is capped at 100 server-side and production runs 40+ channels.
 */
export async function fetchAllChannels(): Promise<Channel[]> {
  const collected: Channel[] = []
  let page = 1
  for (;;) {
    const res = await getChannels({ p: page, page_size: 100 })
    const data = requireServerSuccess(res).data
    collected.push(...(data?.items ?? []))
    if (
      !data ||
      collected.length >= data.total ||
      (data.items ?? []).length === 0
    ) {
      return collected
    }
    page += 1
  }
}

export async function getCctestStatus(): Promise<CctestStatus> {
  const res = await api.get('/api/cctest/status', {
    // The monitor may be parked/unreachable: degrade on the page instead
    // of toasting, and never let a 401 from it trigger a refresh loop.
    skipErrorHandler: true,
    skipAuthRefresh: true,
  } satisfies ApiRequestConfig)
  return requireServerSuccess(res.data).data as CctestStatus
}

export type VerifyResponse = {
  verdict: string
  channel: string
}

export async function verifyNow(
  channel: string,
  model: string
): Promise<VerifyResponse> {
  const res = await api.post(
    '/api/cctest/verify',
    { channel, model },
    // A check takes a cctest round-trip (~30-90s): allow a long wait and
    // let the caller surface failures per-action.
    { timeout: 120_000, skipBusinessError: true } satisfies ApiRequestConfig
  )
  return requireServerSuccess(res.data).data as VerifyResponse
}

export type PromoteResponse = {
  promoted: string | null
  verdict: string | null
  demoted: string
}

export async function promoteStandby(
  model: string,
  merchant?: string
): Promise<PromoteResponse> {
  const res = await api.post(
    '/api/cctest/promote',
    merchant ? { model, merchant } : { model },
    // Promotion runs a synchronous standby verification after the swap.
    { timeout: 120_000, skipBusinessError: true } satisfies ApiRequestConfig
  )
  return requireServerSuccess(res.data).data as PromoteResponse
}

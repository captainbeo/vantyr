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
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, test, vi } from 'vitest'

import { useTopupInfo } from '../use-topup-info'

vi.mock('../../api', () => ({
  getTopupInfo: vi.fn(),
}))

import { getTopupInfo } from '../../api'

const mockedGetTopupInfo = vi.mocked(getTopupInfo)

function apiResponse(payMethods: unknown) {
  return {
    success: true,
    message: '',
    data: {
      enable_online_topup: true,
      enable_stripe_topup: false,
      enable_creem_topup: false,
      enable_waffo_topup: false,
      enable_waffo_pancake_topup: false,
      enable_redemption: true,
      payment_compliance_confirmed: true,
      pay_methods: payMethods,
      min_topup: 1,
      stripe_min_topup: 1,
      amount_options: [],
      discount: {},
    },
  }
}

describe('useTopupInfo pay-method parsing', () => {
  test('keeps the subtitle from the raw API pay_methods JSON', async () => {
    mockedGetTopupInfo.mockResolvedValue(
      apiResponse([
        {
          name: 'USDT / USDC',
          subtitle: 'Network: Aptos, BSC, Ethereum, Plasma, Polygon, Solana, TRON',
          icon: 'SiTether',
          type: 'alipay',
          min_topup: '1',
        },
        {
          name: 'USDT / USDC',
          subtitle: 'Network: Arbitrum, Base, TON/GRAM, X-Layer',
          icon: 'SiTether',
          type: 'bepusdt',
          min_topup: '1',
        },
      ]) as Awaited<ReturnType<typeof getTopupInfo>>
    )

    const { result } = renderHook(() => useTopupInfo())

    await waitFor(() => expect(result.current.loading).toBe(false))

    const methods = result.current.topupInfo?.pay_methods ?? []
    expect(methods).toHaveLength(2)
    expect(methods[0]?.subtitle).toBe(
      'Network: Aptos, BSC, Ethereum, Plasma, Polygon, Solana, TRON'
    )
    expect(methods[1]?.subtitle).toBe(
      'Network: Arbitrum, Base, TON/GRAM, X-Layer'
    )
  })

  test('omits subtitle when the server entry has none', async () => {
    mockedGetTopupInfo.mockResolvedValue(
      apiResponse([{ name: 'Stripe', type: 'stripe', min_topup: '1' }]) as Awaited<
        ReturnType<typeof getTopupInfo>
      >
    )

    const { result } = renderHook(() => useTopupInfo())

    await waitFor(() => expect(result.current.loading).toBe(false))

    const methods = result.current.topupInfo?.pay_methods ?? []
    expect(methods).toHaveLength(1)
    expect(methods[0]?.subtitle).toBeUndefined()
  })
})

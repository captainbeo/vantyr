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
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

import type { PresetAmount, TopupInfo } from '../../types'
import { RechargeFormCard } from '../recharge-form-card'

function buildTopupInfo(overrides: Partial<TopupInfo> = {}): TopupInfo {
  return {
    enable_online_topup: true,
    enable_stripe_topup: true,
    stripe_usd_enabled: true,
    pay_methods: [],
    min_topup: 1,
    stripe_min_topup: 1,
    amount_options: [5],
    discount: {},
    ...overrides,
  }
}

type HarnessProps = {
  topupInfo?: TopupInfo
  stripeCurrency?: 'eur' | 'usd'
  onStripeCurrencyChange?: (currency: 'eur' | 'usd') => void
}

function CurrencyToggleHarness(props: HarnessProps) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return (
    <QueryClientProvider client={queryClient}>
      <RechargeFormCard
        topupInfo={props.topupInfo ?? buildTopupInfo()}
        presetAmounts={[{ value: 5 } satisfies PresetAmount]}
        selectedPreset={5}
        onSelectPreset={() => {}}
        topupAmount={5}
        onTopupAmountChange={() => {}}
        paymentAmount={5}
        calculating={false}
        onPaymentMethodSelect={() => {}}
        paymentLoading={null}
        redemptionCode=''
        onRedemptionCodeChange={() => {}}
        onRedeem={() => {}}
        redeeming={false}
        stripeUsdEnabled={props.topupInfo?.stripe_usd_enabled ?? true}
        stripeCurrency={props.stripeCurrency ?? 'eur'}
        onStripeCurrencyChange={props.onStripeCurrencyChange ?? (() => {})}
      />
    </QueryClientProvider>
  )
}

describe('Stripe currency toggle', () => {
  test('renders EUR and USD buttons when the USD price is configured', () => {
    render(<CurrencyToggleHarness />)

    expect(screen.getByRole('button', { name: /EUR/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /USD/ })).toBeInTheDocument()
  })

  test('marks the selected currency as pressed and the other as not', () => {
    render(<CurrencyToggleHarness stripeCurrency='usd' />)

    expect(screen.getByRole('button', { name: /USD/ })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(screen.getByRole('button', { name: /EUR/ })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
  })

  test('clicking USD notifies the wallet so the amount recalculates', async () => {
    const user = userEvent.setup()
    const onStripeCurrencyChange = vi.fn()
    render(
      <CurrencyToggleHarness onStripeCurrencyChange={onStripeCurrencyChange} />
    )

    await user.click(screen.getByRole('button', { name: /USD/ }))

    expect(onStripeCurrencyChange).toHaveBeenCalledWith('usd')
  })

  test('is hidden when the USD price is not configured', () => {
    render(
      <CurrencyToggleHarness
        topupInfo={buildTopupInfo({ stripe_usd_enabled: false })}
        stripeCurrency='eur'
      />
    )

    expect(
      screen.queryByRole('button', { name: /EUR/ })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /USD/ })
    ).not.toBeInTheDocument()
  })
})

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
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

import type { PresetAmount, TopupInfo } from '../../types'
import { RechargeFormCard } from '../recharge-form-card'

function buildTopupInfo(overrides: Partial<TopupInfo> = {}): TopupInfo {
  return {
    enable_online_topup: true,
    enable_stripe_topup: false,
    stripe_usd_enabled: false,
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
  onPaymentMethodSelect?: (method: unknown) => void
}

function PayMethodSubtitleHarness(props: HarnessProps) {
  return (
    <RechargeFormCard
      topupInfo={props.topupInfo ?? buildTopupInfo()}
      presetAmounts={[{ value: 5 } satisfies PresetAmount]}
      selectedPreset={5}
      onSelectPreset={() => {}}
      topupAmount={5}
      onTopupAmountChange={() => {}}
      paymentAmount={5}
      calculating={false}
      onPaymentMethodSelect={props.onPaymentMethodSelect ?? (() => {})}
      paymentLoading={null}
      redemptionCode=''
      onRedemptionCodeChange={() => {}}
      onRedeem={() => {}}
      redeeming={false}
      stripeUsdEnabled={false}
      stripeCurrency='eur'
      onStripeCurrencyChange={() => {}}
    />
  )
}

describe('Pay method subtitle', () => {
  test('renders the subtitle line under the method name when configured', () => {
    render(
      <PayMethodSubtitleHarness
        topupInfo={buildTopupInfo({
          pay_methods: [
            {
              name: 'USDT / USDC',
              subtitle: 'Network: Aptos, BSC, Ethereum',
              type: 'alipay',
              min_topup: 1,
            },
          ],
        })}
      />
    )

    const nameElement = screen.getByText('USDT / USDC')
    expect(nameElement).toBeInTheDocument()
    const subtitleElement = screen.getByText(
      'Network: Aptos, BSC, Ethereum'
    )
    expect(subtitleElement).toBeInTheDocument()

    // The subtitle renders as a smaller secondary line inside the same button
    const button = nameElement.closest('button')
    expect(button).not.toBeNull()
    expect(button).toContainElement(subtitleElement)
  })

  test('omits the subtitle line when no subtitle is configured', () => {
    render(
      <PayMethodSubtitleHarness
        topupInfo={buildTopupInfo({
          pay_methods: [
            { name: 'USDT / USDC', type: 'alipay', min_topup: 1 },
          ],
        })}
      />
    )

    expect(screen.getByText('USDT / USDC')).toBeInTheDocument()
    expect(
      screen.queryByText(/Network:/i)
    ).not.toBeInTheDocument()
  })

  test('renders the Stripe method full-width instead of in a narrow grid cell', () => {
    render(
      <PayMethodSubtitleHarness
        topupInfo={buildTopupInfo({
          pay_methods: [
            {
              name: 'Card / iDEAL | WERO / Apple + Google Pay / PayPal and more',
              subtitle: 'powered by Stripe',
              type: 'stripe',
              min_topup: 1,
            },
          ],
        })}
      />
    )

    // The full-width stripe button must render its full name + italic subtitle
    // in one row-spanning element, not truncated inside a grid cell.
    const nameElement = screen.getByText(
      'Card / iDEAL | WERO / Apple + Google Pay / PayPal and more'
    )
    const button = nameElement.closest('button')
    expect(button).not.toBeNull()
    expect(button?.className).toContain('col-span-2')
    expect(button).toContainElement(
      screen.getByText('powered by Stripe')
    )
  })

  test('selecting a method passes the subtitle through to the handler', async () => {
    const user = userEvent.setup()
    const onPaymentMethodSelect = vi.fn()
    render(
      <PayMethodSubtitleHarness
        onPaymentMethodSelect={onPaymentMethodSelect}
        topupInfo={buildTopupInfo({
          pay_methods: [
            {
              name: 'USDT / USDC',
              subtitle: 'Network: Arbitrum, Base, TON/GRAM, X-Layer',
              type: 'bepusdt',
              min_topup: 1,
            },
          ],
        })}
      />
    )

    await user.click(screen.getByRole('button', { name: /USDT \/ USDC/ }))

    expect(onPaymentMethodSelect).toHaveBeenCalledTimes(1)
    expect(onPaymentMethodSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'USDT / USDC',
        subtitle: 'Network: Arbitrum, Base, TON/GRAM, X-Layer',
        type: 'bepusdt',
      })
    )
  })
})

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
import { describe, expect, test } from 'vitest'

import { PAYMENT_TYPES } from '../../constants'
import type { PaymentMethod } from '../../types'
import { PaymentConfirmDialog } from '../dialogs/payment-confirm-dialog'

const EXACT_AMOUNT_NOTICE =
  'On the payment page, send the exact amount shown, after exchange fees, before the timer runs out.'

function renderConfirmDialog(paymentMethod: PaymentMethod) {
  render(
    <PaymentConfirmDialog
      open
      onOpenChange={() => {}}
      onConfirm={() => {}}
      topupAmount={10}
      paymentAmount={10}
      paymentMethod={paymentMethod}
      calculating={false}
      processing={false}
    />
  )
}

describe('Crypto exact-amount notice', () => {
  test('GM Pay crypto method shows the exact-amount notice', () => {
    renderConfirmDialog({ name: 'USDT / USDC', type: PAYMENT_TYPES.ALIPAY })

    expect(screen.getByRole('alert')).toHaveTextContent(EXACT_AMOUNT_NOTICE)
  })

  test('BEpusdt crypto method shows the exact-amount notice', () => {
    renderConfirmDialog({ name: 'USDT / USDC', type: PAYMENT_TYPES.BEPUSDT })

    expect(screen.getByRole('alert')).toHaveTextContent(EXACT_AMOUNT_NOTICE)
  })

  test('Stripe method does not show the exact-amount notice', () => {
    renderConfirmDialog({
      name: 'Card / iDEAL / Klarna / PayPal and more',
      type: PAYMENT_TYPES.STRIPE,
    })

    expect(
      screen.getByText('Confirm Payment', { selector: 'h2' })
    ).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

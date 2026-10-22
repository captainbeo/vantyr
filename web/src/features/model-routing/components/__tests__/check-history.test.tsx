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
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createInstance } from 'i18next'
import { I18nextProvider } from 'react-i18next'
import { afterEach, describe, expect, it } from 'vitest'

import { CheckHistory } from '../check-history'

const i18n = createInstance()
await i18n.init({
  lng: 'en',
  resources: { en: { translation: {} } },
  initAsync: false,
})

function renderHistory(history: { verdict: string; at: string }[]) {
  return render(
    <I18nextProvider i18n={i18n}>
      <CheckHistory history={history} />
    </I18nextProvider>
  )
}

afterEach(() => {
  cleanup()
})

describe('CheckHistory', () => {
  it('shows "No checks yet" when there is no history', () => {
    renderHistory([])
    expect(screen.getByText('No checks yet')).toBeInTheDocument()
  })

  it('shows the latest check inline and no expand toggle for a single check', () => {
    renderHistory([{ verdict: 'attr_match', at: '2026-10-21T12:00:00Z' }])
    expect(screen.getAllByText('attr_match')).toHaveLength(1)
    // single entry: the button is disabled (nothing to expand)
    const toggle = screen.getByRole('button')
    expect(toggle).toBeDisabled()
  })

  it('expands to reveal earlier checks on click and collapses again', async () => {
    const user = userEvent.setup()
    renderHistory([
      { verdict: 'attr_match', at: '2026-10-21T12:00:00Z' },
      { verdict: 'unofficial', at: '2026-10-20T12:00:00Z' },
      { verdict: 'attr_match', at: '2026-10-19T12:00:00Z' },
    ])
    const toggle = screen.getByRole('button')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    // earlier verdicts hidden until expanded
    expect(screen.queryByText('unofficial')).not.toBeInTheDocument()

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('unofficial')).toBeInTheDocument()
    // 3 records total: latest inline + all 3 in the list
    expect(screen.getAllByText('attr_match').length).toBeGreaterThanOrEqual(3)

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('unofficial')).not.toBeInTheDocument()
  })
})

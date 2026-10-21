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
import { afterEach, describe, expect, it } from 'vitest'

import { CommunityFloat } from '../community-float'

afterEach(() => {
  cleanup()
})

describe('CommunityFloat', () => {
  it('renders a collapsed toggle labelled Community', () => {
    render(<CommunityFloat />)

    const toggle = screen.getByRole('button', { name: 'Open community links' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveTextContent('Community')
  })

  it('reveals Discord and Telegram links when the toggle is clicked', async () => {
    const user = userEvent.setup()
    render(<CommunityFloat />)

    await user.click(
      screen.getByRole('button', { name: 'Open community links' })
    )

    expect(
      screen.getByRole('button', { name: 'Close community links' })
    ).toHaveAttribute('aria-expanded', 'true')

    const discord = screen.getByRole('link', { name: /Discord/ })
    expect(discord).toHaveAttribute('href', 'https://discord.gg/BNBdHZqGFb')
    expect(discord).toHaveAttribute('target', '_blank')

    const telegram = screen.getByRole('link', { name: /Telegram/ })
    expect(telegram).toHaveAttribute('href', 'https://t.me/vantyrapi')
  })

  it('collapses the panel again on Escape', async () => {
    const user = userEvent.setup()
    render(<CommunityFloat />)

    await user.click(
      screen.getByRole('button', { name: 'Open community links' })
    )
    await user.keyboard('{Escape}')

    expect(
      screen.getByRole('button', { name: 'Open community links' })
    ).toHaveAttribute('aria-expanded', 'false')
  })
})

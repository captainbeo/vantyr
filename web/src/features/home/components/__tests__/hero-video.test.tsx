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
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HeroVideo } from '@/features/home/components/hero-video'

// HTMLMediaElement methods (play/pause) are not implemented in jsdom.
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('HeroVideo', () => {
  it('renders the click-to-play poster, not the video, before interaction', () => {
    render(<HeroVideo />)

    // Poster: play button with its accessible label; no <video> mounted yet
    // (click-to-play keeps the landing light — nothing loads until opt-in).
    expect(
      screen.getByRole('button', { name: 'Play the sign-up video' })
    ).toBeInTheDocument()
    expect(screen.queryByRole('video' as never, { hidden: true })).toBeNull()
    expect(document.querySelector('video')).toBeNull()
  })

  it('keeps a 16:9 box via aspect-video so the poster is never height-collapsed', () => {
    const { container } = render(<HeroVideo />)

    // Regression: the poster button is absolutely positioned; without an
    // aspect ratio on the wrapper the box collapsed to ~2px and the video
    // was invisible on the live homepage.
    const box = container.querySelector("[data-slot='hero-video']")
    expect(box).not.toBeNull()
    expect(box?.className).toContain('aspect-video')
  })

  it('mounts the localized video element after clicking play', () => {
    render(<HeroVideo />)

    fireEvent.click(
      screen.getByRole('button', { name: 'Play the sign-up video' })
    )

    const video = document.querySelector('video')
    expect(video).not.toBeNull()
    // Test i18n resolves to 'en'; English is the map default.
    expect(video?.getAttribute('src')).toBe('/static/video/vantyr-signup-en.mp4')
    expect(video?.hasAttribute('controls')).toBe(true)
  })
})

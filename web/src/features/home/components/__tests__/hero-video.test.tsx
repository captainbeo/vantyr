/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

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

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
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { IntroReveal } from '@/features/home/components/brand/intro-reveal'

// jsdom: window.scrollTo is not implemented (logs "Not implemented" on
// every call). Stub it at this browser-API boundary so the end-of-intro
// scroll shift can run; assertions read the arguments it received.
const scrollTo = vi.fn()
window.scrollTo = scrollTo

// jsdom: scrollY is a read-only 0 getter. Make it writable per test.
function setScrollY(y: number) {
  Object.defineProperty(window, 'scrollY', {
    configurable: true,
    writable: true,
    value: y,
  })
}

function scrollToFraction(f: number) {
  // The intro finishes at window.scrollY = window.innerHeight * 0.9.
  setScrollY(Math.round(window.innerHeight * 0.9 * f))
  window.dispatchEvent(new Event('scroll'))
}

beforeEach(() => {
  scrollTo.mockClear()
  setScrollY(0)
  // jsdom has no WebGL2RenderingContext, so the probe returns false
  // before ever calling getContext. Spying lets the first test assert
  // that no 3D canvas context was requested in a no-WebGL environment.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext')
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('IntroReveal', () => {
  it('renders overlay, wordmark, tagline, scroll hint and flat-mark fallback when WebGL2 is unavailable', async () => {
    render(<IntroReveal />)

    // Overlay: fixed, above the public header, never catches input.
    const overlay = document.querySelector('.bg-void')
    expect(overlay).not.toBeNull()
    expect(overlay?.className).toContain('pointer-events-none')
    expect(overlay?.className).toContain('z-50')

    // Spacer supplies the scroll distance for the transition.
    const spacer = document.querySelector("[class*='90svh']")
    expect(spacer).not.toBeNull()
    expect(spacer?.getAttribute('aria-hidden')).toBe('true')

    await waitFor(() => {
      expect(screen.getByText('VANTYR')).toBeInTheDocument()
    })
    // i18n test resources return the key itself.
    expect(screen.getByText('Endless coding with AI')).toBeInTheDocument()
    expect(screen.getByText('Scroll')).toBeInTheDocument()

    // No WebGL2 → no 3D canvas context is ever requested and the flat
    // mark image is shown instead (decorative: empty alt, so query by
    // class rather than role).
    expect(HTMLCanvasElement.prototype.getContext).not.toHaveBeenCalled()
    const still = document.querySelector('img.h-40')
    expect(still).not.toBeNull()
    expect(still?.getAttribute('src')).toBeTruthy()
  })

  it('fades the overlay while scrolling, then removes the intro and shifts the scroll position without a jump', async () => {
    // jsdom has no layout: give the spacer a deterministic height so the
    // end-of-intro shift is observable. 0.9 screen of scroll distance at
    // 90svh would be equal in a browser; 500px is an explicit fixture.
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(500)

    render(<IntroReveal />)

    await waitFor(() => {
      expect(screen.getByText('VANTYR')).toBeInTheDocument()
    })

    // Mid-scroll: overlay is partway through its fade.
    scrollToFraction(0.5)
    await waitFor(() => {
      const overlay = document.querySelector('.bg-void') as HTMLElement
      const opacity = Number(overlay.style.opacity)
      expect(opacity).toBeGreaterThan(0)
      expect(opacity).toBeLessThan(1)
    })

    // Scroll past the finish threshold: the intro subtracts the spacer
    // height (500) from the current scroll position (a full screen).
    setScrollY(window.innerHeight)
    window.dispatchEvent(new Event('scroll'))
    await waitFor(() => {
      expect(scrollTo).toHaveBeenLastCalledWith(0, window.innerHeight - 500)
    })

    // Done: the intro (overlay + spacer) is removed from the DOM.
    await waitFor(() => {
      expect(document.querySelector('.bg-void')).toBeNull()
      expect(document.querySelector("[class*='90svh']")).toBeNull()
    })
    expect(screen.queryByText('VANTYR')).toBeNull()

    // Scrolling back up afterwards never brings the intro back.
    setScrollY(0)
    window.dispatchEvent(new Event('scroll'))
    expect(screen.queryByText('VANTYR')).toBeNull()
    expect(document.querySelector('.bg-void')).toBeNull()
  })
})

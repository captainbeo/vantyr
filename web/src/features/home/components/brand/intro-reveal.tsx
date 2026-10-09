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
import { ClientOnly } from '@tanstack/react-router'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import mark from '@/assets/vantyr-mark.png'

// The 3D mark needs WebGL2. Loaded lazily so the three.js stack stays out
// of the landing bundle until this scene actually mounts.
const Logo3D = lazy(() =>
  import('./vantyr-logo-3d').then((m) => ({ default: m.VantyrLogo3D }))
)

// Session marker: once the intro has played (or been scrolled through),
// it never replays for the rest of the tab session.
const INTRO_SESSION_KEY = 'vantyr.intro-seen'

const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

function supportsWebGL2(): boolean {
  try {
    // The class probe short-circuits environments without WebGL at all
    // (test runners, exotic embeddings) so getContext is never called
    // there — jsdom logs "Not implemented" for it.
    if (typeof WebGL2RenderingContext === 'undefined') return false
    const canvas = document.createElement('canvas')
    return !!canvas.getContext('webgl2')
  } catch {
    return false
  }
}

/**
 * Opening scene of the homepage: a full-screen void with the spinning 3D
 * mark. Scrolling through the first screen fades the void away and
 * reveals the site. Plays once per page load: when finished, the intro is
 * removed and the scroll position is shifted so the page doesn't jump, so
 * scrolling up stays on the site. Ported from the Lovable brand design.
 */
export function IntroReveal() {
  const { t } = useTranslation()
  const spacer = useRef<HTMLDivElement>(null)
  const overlay = useRef<HTMLDivElement>(null)
  const logo = useRef<HTMLDivElement>(null)
  const hint = useRef<HTMLDivElement>(null)
  // The intro is a visit greeting, not a route transition: it plays on the
  // FIRST landing of a browsing session and never again while that tab
  // session lives, so returning to Home via the header does not replay it.
  // Cleared only by a fresh tab/browser (sessionStorage semantics).
  const [done, setDone] = useState(() => {
    try {
      return window.sessionStorage.getItem(INTRO_SESSION_KEY) === '1'
    } catch {
      return false
    }
  })
  // Probed after mount: environments without WebGL2 (and test runners)
  // keep the flat mark instead of mounting a dead canvas.
  const [canRender3D, setCanRender3D] = useState(false)

  useEffect(() => {
    setCanRender3D(supportsWebGL2())
  }, [])

  useEffect(() => {
    if (done) return
    let raf = 0
    let finished = false
    const update = () => {
      raf = 0
      if (finished) return
      const p = Math.min(1, window.scrollY / (window.innerHeight * 0.9))
      const o = overlay.current
      const l = logo.current
      if (!o || !l) return
      if (p >= 1) {
        finished = true
        // Capture the pre-removal position: the compensating scroll must
        // be computed from where the user is now, not from wherever the
        // browser leaves the scroller after the spacer leaves the layout.
        const y = window.scrollY
        const h = spacer.current?.offsetHeight ?? 0
        o.style.display = 'none'
        if (spacer.current) spacer.current.style.display = 'none'
        // Shift one frame after the removal's layout pass, not
        // synchronously: Chrome's scroll anchoring also compensates for
        // the spacer disappearing at the next layout, and composing with
        // a synchronous scrollTo double-shifts and clamps to the top.
        // Writing after the layout is idempotent where anchoring already
        // compensated and still correct in browsers without it.
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            window.scrollTo(0, Math.max(0, y - h))
            try {
              window.sessionStorage.setItem(INTRO_SESSION_KEY, '1')
            } catch {
              // Storage can be unavailable (private mode quirks); the intro
              // simply replays next visit — never a reason to break the page.
            }
            setDone(true)
          })
        })
        return
      }
      o.style.opacity = String(1 - smooth(0.35, 1, p))
      l.style.opacity = String(1 - smooth(0.15, 0.75, p))
      l.style.transform = `translate3d(0, ${-p * 12}vh, 0) scale(${1 + p * 0.45})`
      if (hint.current) {
        hint.current.style.opacity = String(1 - smooth(0, 0.2, p))
      }
    }
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update)
    }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [done])

  if (done) return null

  const still = (
    <img
      src={mark}
      alt=''
      className='h-40 w-40 object-contain md:h-56 md:w-56'
    />
  )

  return (
    <>
      {/* Scroll distance for the transition */}
      <div ref={spacer} aria-hidden className='h-[90svh]' />
      <div
        ref={overlay}
        aria-hidden
        className='bg-void pointer-events-none fixed inset-0 z-50'
      >
        <div
          ref={logo}
          className='absolute inset-0 flex flex-col items-center justify-center will-change-transform'
        >
          <div className='flex h-[62svh] w-full max-w-3xl items-center justify-center'>
            <ClientOnly fallback={still}>
              {canRender3D ? (
                <Suspense fallback={still}>
                  <Logo3D shadow={false} />
                </Suspense>
              ) : (
                still
              )}
            </ClientOnly>
          </div>
          <span className='font-display text-foreground text-2xl font-semibold tracking-[0.4em] md:text-3xl'>
            VANTYR
          </span>
          <span className='label-mono mt-3'>{t('Endless coding with AI')}</span>
        </div>
        <div
          ref={hint}
          className='absolute inset-x-0 bottom-8 flex flex-col items-center gap-2'
        >
          <span className='label-mono'>{t('Scroll')}</span>
          <span className='animate-blink bg-primary h-8 w-px' />
        </div>
      </div>
    </>
  )
}

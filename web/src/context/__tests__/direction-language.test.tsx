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
import { act, cleanup, render } from '@testing-library/react'
import { createInstance } from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DirectionProvider, useDirection } from '../direction-provider'

// The dayjs locale modules import cleanly under vitest; mock the locale
// application so this suite exercises only the direction contract.
vi.mock('@/lib/dayjs', () => ({
  applyDayjsLocale: vi.fn(),
  default: { extend: vi.fn(), locale: vi.fn() },
}))

const i18n = createInstance()
await i18n.use(initReactI18next).init({
  resources: {
    en: { translation: { hi: 'hello' } },
    ar: { translation: { hi: 'مرحبا' } },
    de: { translation: { hi: 'hallo' } },
  },
  lng: 'en',
  fallbackLng: 'en',
  supportedLngs: ['en', 'ar', 'de'],
  interpolation: { escapeValue: false },
})

type DirectionContext = ReturnType<typeof useDirection>
let captured: DirectionContext | null = null

function Probe() {
  captured = useDirection()
  return null
}

function renderProbe() {
  const utils = render(
    <I18nextProvider i18n={i18n}>
      <DirectionProvider>
        <Probe />
      </DirectionProvider>
    </I18nextProvider>
  )
  return {
    context: () => {
      expect(captured).not.toBeNull()
      return captured as DirectionContext
    },
    unmount: () => utils.unmount(),
  }
}

const DIR_COOKIE_RESET = 'dir=; path=/; max-age=0'

describe('direction follows interface language', () => {
  beforeEach(async () => {
    document.documentElement.removeAttribute('dir')
    document.documentElement.removeAttribute('lang')
    document.cookie = DIR_COOKIE_RESET
    await i18n.changeLanguage('en')
  })

  afterEach(() => {
    cleanup()
    captured = null
  })

  it('LTR language renders ltr direction on <html>', async () => {
    const probe = renderProbe()
    await act(async () => {
      await i18n.changeLanguage('de')
    })
    expect(document.documentElement.getAttribute('dir')).toBe('ltr')
    expect(probe.context().dir).toBe('ltr')
  })

  it('switching to Arabic flips direction to rtl', async () => {
    const probe = renderProbe()
    await act(async () => {
      await i18n.changeLanguage('ar')
    })
    expect(document.documentElement.getAttribute('dir')).toBe('rtl')
    expect(probe.context().dir).toBe('rtl')
  })

  it('switching back to an LTR language restores ltr', async () => {
    renderProbe()
    await act(async () => {
      await i18n.changeLanguage('ar')
    })
    await act(async () => {
      await i18n.changeLanguage('en')
    })
    expect(document.documentElement.getAttribute('dir')).toBe('ltr')
  })

  it('manual override beats language direction and survives remount', async () => {
    const probe = renderProbe()
    await act(async () => {
      await i18n.changeLanguage('ar')
    })
    expect(document.documentElement.getAttribute('dir')).toBe('rtl')
    await act(async () => {
      probe.context().setDir('ltr')
    })
    expect(document.documentElement.getAttribute('dir')).toBe('ltr')
    expect(document.cookie).toContain('dir=ltr')
    probe.unmount()

    // fresh mount (simulated reload) honors the manual cookie over language
    const probe2 = renderProbe()
    await act(async () => {})
    expect(probe2.context().dir).toBe('ltr')
    await act(async () => {
      probe2.context().resetDir()
    })
    expect(document.documentElement.getAttribute('dir')).toBe('rtl')
  })

  it('resetDir clears override so language drives direction again', async () => {
    const probe = renderProbe()
    await act(async () => {
      await i18n.changeLanguage('ar')
    })
    await act(async () => {
      probe.context().setDir('ltr')
    })
    await act(async () => {
      probe.context().resetDir()
    })
    expect(document.documentElement.getAttribute('dir')).toBe('rtl')
  })
})

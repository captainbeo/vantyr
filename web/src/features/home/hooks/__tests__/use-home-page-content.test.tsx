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
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { createInstance } from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useHomePageContent } from '../use-home-page-content'

vi.mock('../../api', () => ({
  getHomePageContent: vi.fn(),
}))
vi.mock('@/lib/handle-server-error', () => ({
  handleServerError: vi.fn(),
}))

const { getHomePageContent } = await import('../../api')

const i18n = createInstance()
await i18n.use(initReactI18next).init({
  lng: 'en',
  fallbackLng: 'en',
  supportedLngs: ['en', 'de'],
  resources: {
    en: { translation: { hi: 'hello' } },
    de: { translation: { hi: 'hallo' } },
  },
  interpolation: { escapeValue: false },
})

let captured: ReturnType<typeof useHomePageContent> | null = null

function Probe() {
  captured = useHomePageContent()
  return null
}

function renderProbe() {
  render(
    <I18nextProvider i18n={i18n}>
      <Probe />
    </I18nextProvider>
  )
}

const LANGUAGE_MAP = JSON.stringify({
  en: '# Welcome',
  de: '# Willkommen',
})

describe('useHomePageContent language variants', () => {
  beforeEach(() => {
    vi.mocked(getHomePageContent).mockReset()
    localStorage.clear()
  })

  afterEach(async () => {
    cleanup()
    captured = null
    await i18n.changeLanguage('en')
  })

  it('renders the plain string when the option is not a language map', async () => {
    vi.mocked(getHomePageContent).mockResolvedValue({
      success: true,
      data: '# Plain guide',
    })
    renderProbe()
    await waitFor(() => {
      expect(captured).not.toBeNull()
      expect(captured?.isLoaded).toBe(true)
    })
    expect(captured?.content).toBe('# Plain guide')
    expect(captured?.isUrl).toBe(false)
  })

  it('selects the variant for the active language and switches on change', async () => {
    vi.mocked(getHomePageContent).mockResolvedValue({
      success: true,
      data: LANGUAGE_MAP,
    })
    renderProbe()
    await waitFor(() => {
      expect(captured).not.toBeNull()
      expect(captured?.isLoaded).toBe(true)
    })
    expect(captured?.content).toBe('# Welcome')

    await act(async () => {
      await i18n.changeLanguage('de')
    })
    expect(captured?.content).toBe('# Willkommen')
  })

  it('falls back to English for a language without a variant', async () => {
    vi.mocked(getHomePageContent).mockResolvedValue({
      success: true,
      data: LANGUAGE_MAP,
    })
    await act(async () => {
      await i18n.changeLanguage('de')
    })
    renderProbe()
    await waitFor(() => {
      expect(captured).not.toBeNull()
      expect(captured?.isLoaded).toBe(true)
    })
    expect(captured?.content).toBe('# Willkommen')
  })

  it('renders empty when the API returns no data', async () => {
    vi.mocked(getHomePageContent).mockResolvedValue({
      success: true,
      data: '',
    })
    renderProbe()
    await waitFor(() => {
      expect(captured).not.toBeNull()
      expect(captured?.isLoaded).toBe(true)
    })
    expect(captured?.content).toBe('')
  })
})

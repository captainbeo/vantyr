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
import { afterEach, describe, expect, it } from 'vitest'

import {
  applyDocumentTitleToDom,
  buildDocumentTitle,
} from '../dom-utils'

const SEO_TITLE = 'Vantyr — Claude, GPT & Codex API at a fraction of official prices'

const resetDocument = () => {
  document.title = SEO_TITLE
  document.head
    .querySelectorAll('meta[name="title"]')
    .forEach((m) => m.remove())
  const meta = document.createElement('meta')
  meta.setAttribute('name', 'title')
  meta.setAttribute('content', SEO_TITLE)
  document.head.appendChild(meta)
  document.querySelector('meta[name="title"]')?.setAttribute('content', SEO_TITLE)
}

afterEach(resetDocument)

describe('buildDocumentTitle', () => {
  it('returns null for the landing route so the static SEO title survives runtime branding', () => {
    expect(buildDocumentTitle('Vantyr', '/')).toBeNull()
  })

  it('returns null for public marketing routes that carry their own SEO titles', () => {
    expect(buildDocumentTitle('Vantyr', '/pricing')).toBeNull()
    expect(buildDocumentTitle('Vantyr', '/rankings')).toBeNull()
    expect(buildDocumentTitle('Vantyr', '/about')).toBeNull()
    expect(buildDocumentTitle('Vantyr', '/pricing/claude-sonnet')).toBeNull()
  })

  it('appends Console for authenticated app routes', () => {
    expect(buildDocumentTitle('Vantyr', '/dashboard')).toBe('Vantyr — Console')
    expect(buildDocumentTitle('Vantyr', '/wallet')).toBe('Vantyr — Console')
    expect(buildDocumentTitle('Vantyr', '/keys')).toBe('Vantyr — Console')
  })

  it('keeps a system name that already reads as a full title', () => {
    expect(buildDocumentTitle('Vantyr — API Console', '/dashboard')).toBe(
      'Vantyr — API Console'
    )
  })

  it('returns null for an empty system name without touching the title', () => {
    expect(buildDocumentTitle('  ', '/dashboard')).toBeNull()
  })
})

describe('applyDocumentTitleToDom', () => {
  it('keeps the SEO document title untouched on the landing route', () => {
    resetDocument()
    applyDocumentTitleToDom('Vantyr', '/')
    expect(document.title).toBe(SEO_TITLE)
    expect(
      (document.querySelector('meta[name="title"]') as HTMLMetaElement).content
    ).toBe(SEO_TITLE)
  })

  it('replaces the title on app routes and syncs the meta title', () => {
    resetDocument()
    applyDocumentTitleToDom('Vantyr', '/dashboard')
    expect(document.title).toBe('Vantyr — Console')
    expect(
      (document.querySelector('meta[name="title"]') as HTMLMetaElement).content
    ).toBe('Vantyr — Console')
  })

  it('is a no-op when the title already matches', () => {
    resetDocument()
    document.title = 'Vantyr — Console'
    applyDocumentTitleToDom('Vantyr', '/dashboard')
    expect(document.title).toBe('Vantyr — Console')
  })
})

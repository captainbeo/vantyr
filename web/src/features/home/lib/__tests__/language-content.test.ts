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
import { describe, expect, it } from 'vitest'

import { selectHomePageContent } from '../language-content'

describe('selectHomePageContent', () => {
  it('returns plain markdown unchanged for any language', () => {
    const md = '# Welcome\n\nGet started guide.'
    expect(selectHomePageContent(md, 'de')).toBe(md)
    expect(selectHomePageContent(md, 'ar')).toBe(md)
    expect(selectHomePageContent(md, undefined)).toBe(md)
  })

  it('returns HTML and iframe URLs unchanged (not treated as maps)', () => {
    const html = '<!doctype html><html><body>hi</body></html>'
    const url = 'https://example.com/home'
    expect(selectHomePageContent(html, 'de')).toBe(html)
    expect(selectHomePageContent(url, 'es')).toBe(url)
  })

  it('picks the variant matching the active language', () => {
    const map = JSON.stringify({
      en: '# Welcome',
      de: '# Willkommen',
      ar: '# مرحبا',
    })
    expect(selectHomePageContent(map, 'de')).toBe('# Willkommen')
    expect(selectHomePageContent(map, 'ar')).toBe('# مرحبا')
    expect(selectHomePageContent(map, 'en')).toBe('# Welcome')
  })

  it('falls back to English when the language has no variant', () => {
    const map = JSON.stringify({ en: '# Welcome', de: '# Willkommen' })
    expect(selectHomePageContent(map, 'tr')).toBe('# Welcome')
    expect(selectHomePageContent(map, 'xx')).toBe('# Welcome')
  })

  it('falls back to the only available variant when English is missing', () => {
    const map = JSON.stringify({ de: '# Willkommen' })
    expect(selectHomePageContent(map, 'es')).toBe('# Willkommen')
  })

  it('skips empty variants and falls back to a non-empty one', () => {
    const map = JSON.stringify({ en: '', de: '  ', es: '# Hola' })
    expect(selectHomePageContent(map, 'de')).toBe('# Hola')
    expect(selectHomePageContent(map, 'en')).toBe('# Hola')
  })

  it('maps camelCase interface codes to their locale variants', () => {
    const map = JSON.stringify({
      en: '# Welcome',
      zhCN: '# 欢迎',
      zhTW: '# 歡迎',
    })
    expect(selectHomePageContent(map, 'zhCN')).toBe('# 欢迎')
    expect(selectHomePageContent(map, 'zh-TW')).toBe('# 歡迎')
  })

  it('treats non-map JSON as plain content', () => {
    expect(selectHomePageContent('["a", "b"]', 'de')).toBe('["a", "b"]')
    const nonLangObject = JSON.stringify({ foo: 'bar' })
    expect(selectHomePageContent(nonLangObject, 'de')).toBe(nonLangObject)
  })

  it('returns empty for empty or missing input', () => {
    expect(selectHomePageContent('', 'de')).toBe('')
    expect(selectHomePageContent(undefined, 'de')).toBe('')
    expect(selectHomePageContent(null, 'de')).toBe('')
    expect(selectHomePageContent('   ', 'de')).toBe('')
  })
})

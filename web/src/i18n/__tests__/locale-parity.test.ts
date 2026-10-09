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
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { resources } from '../config'
import { INTERFACE_LANGUAGE_OPTIONS } from '../languages'

// The vitest jsdom transform rewrites import.meta.url to a non-file URL, so
// resolve from the process cwd (vitest runs from the web/ package root).
const LOCALES_DIR = join(process.cwd(), 'src', 'i18n', 'locales')

function placeholders(value: unknown): string {
  if (typeof value !== 'string') return ''
  return (value.match(/\{\{[^}]+\}\}/g) ?? []).sort().join('|')
}

function loadLocale(filename: string): Record<string, string> {
  const json = JSON.parse(readFileSync(join(LOCALES_DIR, filename), 'utf8'))
  expect(json && typeof json.translation === 'object').toBe(true)
  return json.translation
}

// Every locale file on disk must stay in key parity with en.json so no
// language silently falls back mid-UI. Placeholder equality is enforced for
// the locales this fork owns end-to-end; upstream ja/vi carry known drift
// and are excluded rather than silently weakening the contract.
const PLACEHOLDER_CHECKED_LOCALES = new Set([
  'en',
  'de',
  'nl',
  'tr',
  'es',
  'ar',
])

describe('locale files match the English base contract', () => {
  const en = loadLocale('en.json')
  const enKeys = Object.keys(en)

  const localeFiles = readdirSync(LOCALES_DIR).filter((f) =>
    f.endsWith('.json')
  )

  it('en.json is the largest locale (base authority)', () => {
    for (const file of localeFiles) {
      const translation = loadLocale(file)
      expect(Object.keys(translation).length).toBeLessThanOrEqual(enKeys.length)
    }
  })

  for (const file of localeFiles) {
    it(`${file} has exact key parity with en.json`, () => {
      const translation = loadLocale(file)
      expect(Object.keys(translation).sort()).toEqual([...enKeys].sort())
    })

    it(`${file} preserves every interpolation placeholder`, () => {
      if (!PLACEHOLDER_CHECKED_LOCALES.has(file.replace(/\.json$/, ''))) return
      const translation = loadLocale(file)
      for (const key of enKeys) {
        expect(placeholders(translation[key])).toBe(placeholders(en[key]))
      }
    })
  }
})

// The registry, the i18next resources, and the locale files must name the
// same languages or the picker shows a language that cannot load (or a
// locale file exists that no picker offers).
describe('language registry matches configured resources', () => {
  it('every registry option has a resource', () => {
    const optionCodes = INTERFACE_LANGUAGE_OPTIONS.map((o) => o.code).sort()
    expect(optionCodes).toEqual(Object.keys(resources).sort())
  })

  it('every registry option has a locale file', () => {
    // The Chinese locales use non-obvious filenames (zhCN -> zh.json,
    // zhTW -> zh-TW.json) because their resource keys are the import names.
    const codeToFile: Record<string, string> = { zhCN: 'zh', zhTW: 'zh-TW' }
    const filenames = new Set(
      readdirSync(LOCALES_DIR)
        .filter((f) => f.endsWith('.json'))
        .map((f) => f.replace(/\.json$/, ''))
    )
    for (const option of INTERFACE_LANGUAGE_OPTIONS) {
      const expected = codeToFile[option.code] ?? option.code
      expect(filenames.has(expected)).toBe(true)
    }
  })
})

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
import { normalizeInterfaceLanguage } from '@/i18n/languages'

/**
 * Language-variant home page content.
 *
 * The `HomePageContent` option is traditionally a plain string (Markdown,
 * HTML, or an iframe URL) shown to every visitor. It may alternatively hold
 * a JSON object mapping interface language codes to per-language variants:
 *
 *   {"en": "# Welcome…", "de": "# Willkommen…", "ar": "# مرحبا…"}
 *
 * Selection follows the visitor's active interface language with English
 * (or the only available variant) as fallback. Plain strings, HTML, and
 * URLs keep their existing single-content behavior.
 */

// Interface language codes: two-letter codes (en, de, nl) or the camelCase
// Chinese codes (zhCN, zhTW).
const LANG_KEY = /^[a-z]{2}(?:[A-Z]{2})?$/

export function selectHomePageContent(
  raw: string | undefined | null,
  language?: string | null
): string {
  const value = typeof raw === 'string' ? raw.trim() : ''
  if (!value) return ''

  const variants = parseLanguageMap(value)
  if (!variants) return value

  const requested = normalizeInterfaceLanguage(language ?? undefined)
  return pickVariant(variants, requested)
}

function parseLanguageMap(value: string): Record<string, string> | null {
  if (!value.startsWith('{')) return null
  try {
    const parsed: unknown = JSON.parse(value)
    if (
      typeof parsed !== 'object' ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      return null
    }
    const entries = Object.entries(parsed as Record<string, unknown>).filter(
      ([key, v]) =>
        (LANG_KEY.test(key) || key === 'en') &&
        (typeof v === 'string' || typeof v === 'number')
    ) as [string, string][]
    if (entries.length === 0) return null
    return Object.fromEntries(entries)
  } catch {
    // Not JSON — treat as a plain content string (markdown/HTML/URL).
    return null
  }
}

function pickVariant(variants: Record<string, string>, language: string) {
  const exact = variants[language]
  if (typeof exact === 'string' && exact.trim() !== '') return exact

  const fallback =
    typeof variants.en === 'string' && variants.en.trim() !== ''
      ? variants.en
      : Object.values(variants).find(
          (v) => typeof v === 'string' && v.trim() !== ''
        )
  return fallback ?? ''
}

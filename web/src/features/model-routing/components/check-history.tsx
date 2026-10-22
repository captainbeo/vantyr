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
import { ChevronDown, History } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { StatusBadge } from '@/components/status-badge'
import { toIntlLocale } from '@/i18n/languages'
import { formatTimestampRelative } from '@/lib/format'
import { cn } from '@/lib/utils'

import type { VerdictRecord } from '../types'

// ============================================================================
// Check history — inline latest check + click-to-expand the last few checks
// for one merchant/channel. Used by the routing ladder and the standby pool.
// ============================================================================

const PASS_VERDICTS = new Set(['official', 'attr_match'])
const SOFT_VERDICTS = new Set(['official_flawed', 'reversed'])
const BAD_VERDICTS = new Set(['unofficial', 'not_claude', 'attr_swapped'])

function verdictVariant(
  verdict: string | null
): 'success' | 'warning' | 'danger' | 'neutral' {
  if (verdict == null) return 'neutral'
  if (PASS_VERDICTS.has(verdict)) return 'success'
  if (SOFT_VERDICTS.has(verdict)) return 'warning'
  if (BAD_VERDICTS.has(verdict)) return 'danger'
  return 'neutral'
}

function toSeconds(iso: string): number | undefined {
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return undefined
  return Math.floor(ms / 1000)
}

function absoluteAt(iso: string): string {
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return iso
  return new Date(ms).toLocaleString()
}

export function CheckHistory(props: { history: VerdictRecord[] }) {
  const { t, i18n } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const history = props.history

  if (history.length === 0) {
    return (
      <span className='text-muted-foreground/70 text-[11px]'>
        {t('No checks yet')}
      </span>
    )
  }

  const latest = history[0]
  const locale = toIntlLocale(i18n.resolvedLanguage || i18n.language)
  const relative = formatTimestampRelative(toSeconds(latest.at), 'seconds', locale)
  const hasMore = history.length > 1

  return (
    <div className='flex flex-col gap-1'>
      <button
        type='button'
        onClick={() => hasMore && setExpanded((v) => !v)}
        disabled={!hasMore}
        aria-expanded={hasMore ? expanded : undefined}
        className={cn(
          'text-muted-foreground flex items-center gap-1.5 text-left text-[11px]',
          hasMore
            ? 'hover:text-foreground cursor-pointer'
            : 'cursor-default'
        )}
      >
        <StatusBadge
          variant={verdictVariant(latest.verdict)}
          label={latest.verdict}
          copyable={false}
        />
        <span className='shrink-0'>{relative}</span>
        {hasMore && (
          <ChevronDown
            className={cn(
              'size-3 shrink-0 transition-transform',
              expanded && 'rotate-180'
            )}
            aria-hidden='true'
          />
        )}
      </button>

      {expanded && hasMore && (
        <ol className='border-border/60 flex flex-col gap-1 border-l pl-2'>
          {history.map((entry) => (
            <li
              key={`${entry.at}-${entry.verdict}`}
              className='text-muted-foreground flex items-center gap-1.5 text-[11px]'
            >
              <History className='size-3 shrink-0' aria-hidden='true' />
              <StatusBadge
                variant={verdictVariant(entry.verdict)}
                label={entry.verdict}
                copyable={false}
              />
              <span className='shrink-0' title={absoluteAt(entry.at)}>
                {formatTimestampRelative(toSeconds(entry.at), 'seconds', locale)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

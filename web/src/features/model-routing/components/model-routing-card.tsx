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
import {
  AlertTriangle,
  ChevronRight,
  HelpCircle,
  ShieldCheck,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/utils'

import type { ModelSummary } from '../types'

// ============================================================================
// Model health card — one card per model in the dashboard grid. Click opens
// the detail drawer (full ladder + standby pool + actions).
// ============================================================================

const HEALTH_DOT_CLASSES: Record<ModelSummary['health'], string> = {
  healthy: 'bg-success',
  attention: 'bg-warning',
  uncertain: 'bg-muted-foreground/50',
}

function standbyDotClass(
  state: ModelSummary['standbys'][number]['state']
): string {
  if (state === 'ready') return 'bg-success'
  if (state === 'cooldown') return 'bg-warning'
  return 'bg-destructive'
}

export function ModelRoutingCard(props: {
  summary: ModelSummary
  onOpen: (model: string) => void
}) {
  const { t } = useTranslation()
  const s = props.summary

  let healthLabel = t('Uncertain')
  if (s.health === 'healthy') healthLabel = t('Serving')
  else if (s.health === 'attention') healthLabel = t('Needs attention')

  return (
    <button
      type='button'
      onClick={() => props.onOpen(s.model)}
      className='group bg-card hover:border-primary/40 focus-visible:ring-ring flex w-full flex-col gap-3 rounded-xl border p-4 text-start transition-colors outline-none focus-visible:ring-2'
      aria-label={`${s.model}: ${healthLabel}`}
    >
      <div className='flex items-start justify-between gap-2'>
        <div className='min-w-0'>
          <div className='text-foreground truncate font-mono text-sm font-semibold'>
            {s.model}
          </div>
          <div className='text-muted-foreground mt-1 flex items-center gap-1.5 text-xs'>
            <span
              className={cn(
                'size-1.5 shrink-0 rounded-full',
                HEALTH_DOT_CLASSES[s.health]
              )}
            />
            {healthLabel}
          </div>
        </div>
        <ChevronRight
          aria-hidden='true'
          className='text-muted-foreground/50 group-hover:text-primary size-4 shrink-0 transition-colors'
        />
      </div>

      <div className='text-muted-foreground space-y-1 text-xs'>
        {s.activeChannelName ? (
          <div className='flex items-center gap-1.5'>
            <span className='text-muted-foreground/60 w-14 shrink-0'>
              {t('serving via')}
            </span>
            <span className='text-foreground/90 truncate font-mono'>
              {s.activeChannelName}
            </span>
          </div>
        ) : (
          <div className='text-destructive flex items-center gap-1.5'>
            <AlertTriangle className='size-3.5 shrink-0' />
            {t('No active channel')}
          </div>
        )}
        {s.activeMerchant && (
          <div className='flex items-center gap-1.5'>
            <span className='text-muted-foreground/60 w-14 shrink-0'>
              {t('merchant')}
            </span>
            <span className='text-foreground/90 truncate font-mono'>
              {t('{{id}} (A6 merchant)', { id: s.activeMerchant })}
            </span>
          </div>
        )}
      </div>

      <div className='flex items-center justify-between gap-2 border-t pt-3'>
        <div className='flex min-w-0 items-center gap-1.5'>
          {s.verdict != null ? (
            <span
              className={cn(
                'inline-flex items-center gap-1 text-xs',
                verdictTextClass(s.verdict)
              )}
            >
              {verdictIcon(s.verdict)}
              <span className='truncate font-mono'>{s.verdict}</span>
            </span>
          ) : (
            <span className='text-muted-foreground/60 text-xs'>
              {t('Not checked')}
            </span>
          )}
        </div>
        {s.standbys.length > 0 && (
          <span
            className='text-muted-foreground flex shrink-0 items-center gap-1 text-xs'
            title={t('{{ready}} ready, {{cooldown}} on cooldown', {
              ready: s.standbyFresh,
              cooldown: s.standbyCooldown,
            })}
          >
            <span className='flex items-center gap-0.5'>
              {s.standbys.map((standby) => (
                <span
                  key={standby.channelId}
                  className={cn(
                    'size-1.5 rounded-full',
                    standbyDotClass(standby.state)
                  )}
                />
              ))}
            </span>
            {t('{{count}} standbys', { count: s.standbys.length })}
          </span>
        )}
      </div>
    </button>
  )
}

const PASS_VERDICTS = new Set(['official', 'attr_match', 'attr_upgraded'])
const BAD_VERDICTS = new Set(['unofficial', 'not_claude', 'attr_swapped'])

function verdictTextClass(verdict: string): string {
  if (PASS_VERDICTS.has(verdict)) return 'text-success'
  if (BAD_VERDICTS.has(verdict)) return 'text-destructive'
  return 'text-warning'
}

function verdictIcon(verdict: string) {
  if (PASS_VERDICTS.has(verdict)) {
    return <ShieldCheck className='size-3.5 shrink-0' />
  }
  if (BAD_VERDICTS.has(verdict)) {
    return <AlertTriangle className='size-3.5 shrink-0' />
  }
  return <HelpCircle className='size-3.5 shrink-0' />
}

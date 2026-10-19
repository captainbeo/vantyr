import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/utils'

import type { ModelSummary } from '../types'

// ============================================================================
// Needs-attention strip — one line per problem model, click jumps into the
// detail drawer. Shown only when at least one model needs attention.
// ============================================================================

export function AttentionStrip(props: {
  summaries: ModelSummary[]
  onOpen: (model: string) => void
}) {
  const { t } = useTranslation()
  const attention = props.summaries.filter(
    (summary) => summary.health === 'attention'
  )
  if (attention.length === 0) {
    return null
  }

  return (
    <div className='border-warning/40 bg-warning/5 flex flex-col gap-1 rounded-xl border p-3 sm:p-4'>
      <div className='text-warning flex items-center gap-2 text-sm font-semibold'>
        <AlertTriangle className='size-4 shrink-0' />
        {t('Needs attention')}
      </div>
      <ul className='mt-1 flex flex-col gap-0.5'>
        {attention.map((summary) => (
          <li key={summary.model}>
            <button
              type='button'
              onClick={() => props.onOpen(summary.model)}
              className='hover:bg-warning/10 focus-visible:ring-ring flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start outline-none focus-visible:ring-2'
            >
              <span className='text-foreground truncate font-mono text-xs font-medium'>
                {summary.model}
              </span>
              <span
                className={cn(
                  'text-muted-foreground min-w-0 flex-1 truncate text-xs'
                )}
              >
                — {reasonText(summary, t)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function reasonText(summary: ModelSummary, t: (key: string) => string): string {
  switch (summary.attentionReason) {
    case 'quarantined-active':
      return t('active pin quarantined — traffic fell back down the ladder')
    case 'no-active':
      return t('no enabled channel serves this model')
    case 'bad-verdict':
      return t(
        'active merchant failed verification — promote a standby or re-pin'
      )
    case 'no-standbys-ready':
      return t('every standby is in cooldown — rotation unavailable')
    default:
      return t('check details')
  }
}

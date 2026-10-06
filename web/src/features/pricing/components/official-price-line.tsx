import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/utils'

import {
  formatOfficialUsd,
  getOfficialComparison,
} from '../lib/official-price'
import type { PricingModel } from '../types'

/**
 * 'Official API price vs ours' comparison line with a live discount badge.
 * Renders nothing when the model has no official price data. The discount
 * is derived from live ratios, so it updates as soon as prices change.
 */
export function OfficialPriceLine(props: {
  model: PricingModel
  variant?: 'inline' | 'block'
  className?: string
}) {
  const { t } = useTranslation()
  const comparison = getOfficialComparison(props.model)
  if (!comparison) return null

  const badge =
    comparison.discountPercent > 0 ? (
      <span className='text-emerald-600 dark:text-emerald-400 font-medium whitespace-nowrap'>
        {t('{{count}}% cheaper than official', {
          count: comparison.discountPercent,
        })}
      </span>
    ) : null

  if (props.variant === 'block') {
    const parts = [
      `${t('Input')} ${formatOfficialUsd(comparison.input)}`,
      `${t('Output')} ${formatOfficialUsd(comparison.output)}`,
    ]
    if (comparison.cache != null) {
      parts.push(`${t('Cache Read')} ${formatOfficialUsd(comparison.cache)}`)
    }
    return (
      <div
        className={cn(
          'bg-muted/20 rounded-lg border px-3 py-2.5',
          props.className
        )}
      >
        <div className='flex flex-wrap items-baseline justify-between gap-x-2'>
          <span className='text-muted-foreground/70 text-sm'>
            {t('Official API price')}
          </span>
          {badge}
        </div>
        <div className='text-muted-foreground mt-1 font-mono text-sm tabular-nums break-words'>
          {parts.join(' · ')}{' '}
          <span className='text-muted-foreground/50 text-xs'>/1M</span>
        </div>
      </div>
    )
  }

  return (
    <span
      className={cn(
        'text-muted-foreground/70 block text-xs break-words',
        props.className
      )}
      title={t('Official API price')}
    >
      {t('Official API price')}: {formatOfficialUsd(comparison.input)} /{' '}
      {formatOfficialUsd(comparison.output)}
      {comparison.cache != null
        ? ` / ${formatOfficialUsd(comparison.cache)}`
        : ''}{' '}
      /1M
      {badge && <span className='ml-1.5'>{badge}</span>}
    </span>
  )
}

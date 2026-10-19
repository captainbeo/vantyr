import { Activity, AlertTriangle, Layers, RadioTower } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { IconBadge, type IconBadgeTone } from '@/components/ui/icon-badge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

import type { ModelSummary } from '../types'

// ============================================================================
// KPI row — dashboard headline tiles (stat-tile contract: label + value +
// description; status meaning always paired with icon + label, never color
// alone; proportional figures at display size)
// ============================================================================

type KpiTile = {
  id: string
  label: string
  value: string
  description: string
  icon: typeof Activity
  iconTone: IconBadgeTone
}

export function KpiTiles(props: {
  summaries: ModelSummary[]
  lastCycleAt: string | null
  monitorDown: boolean
  loading: boolean
}) {
  const { t } = useTranslation()

  if (props.loading) {
    return (
      <div className='grid grid-cols-2 gap-1.5 sm:gap-3 lg:grid-cols-4'>
        {[0, 1, 2, 3].map((index) => (
          <div
            key={index}
            className='bg-background/60 rounded-lg border px-2.5 py-3 sm:rounded-xl sm:px-4 sm:py-4'
          >
            <Skeleton className='h-4 w-20' />
            <Skeleton className='mt-2.5 h-7 w-12' />
            <Skeleton className='mt-2 h-3 w-24' />
          </div>
        ))}
      </div>
    )
  }

  const healthy = props.summaries.filter((s) => s.health === 'healthy').length
  const attention = props.summaries.filter(
    (s) => s.health === 'attention'
  ).length
  const standbyTotal = props.summaries.reduce(
    (sum, s) => sum + s.standbyFresh + s.standbyCooldown,
    0
  )
  const standbyCooldown = props.summaries.reduce(
    (sum, s) => sum + s.standbyCooldown,
    0
  )

  const lastCycleLabel = props.monitorDown
    ? t('Monitor unreachable')
    : (props.lastCycleAt ?? t('No cycle yet'))

  const tiles: KpiTile[] = [
    {
      id: 'healthy',
      label: t('Healthy'),
      value: `${healthy} / ${props.summaries.length}`,
      description: t('models serving verified genuine responses'),
      icon: Activity,
      iconTone: 'success',
    },
    {
      id: 'attention',
      label: t('Needs attention'),
      value: String(attention),
      description: t('models with a routing or verification problem'),
      icon: AlertTriangle,
      iconTone: attention > 0 ? 'warning' : 'neutral',
    },
    {
      id: 'standbys',
      label: t('Standby pool'),
      value: String(standbyTotal),
      description: t('{{ready}} ready · {{cooldown}} on cooldown', {
        ready: standbyTotal - standbyCooldown,
        cooldown: standbyCooldown,
      }),
      icon: Layers,
      iconTone: 'info',
    },
    {
      id: 'monitor',
      label: t('Monitor'),
      value: props.monitorDown ? t('Down') : t('Enforcing'),
      description: t('last cycle {{time}}', {
        time: lastCycleLabel,
      }),
      icon: RadioTower,
      iconTone: props.monitorDown ? 'destructive' : 'primary',
    },
  ]

  return (
    <div className='grid grid-cols-2 gap-1.5 sm:gap-3 lg:grid-cols-4'>
      {tiles.map((tile) => (
        <div
          key={tile.id}
          className={cn(
            'bg-background/60 flex flex-col gap-1 rounded-lg border px-2.5 py-2 sm:gap-1.5 sm:rounded-xl sm:px-4 sm:py-3.5'
          )}
        >
          <div className='text-muted-foreground flex items-center gap-1.5 text-[11px] font-medium sm:gap-2 sm:text-xs'>
            <IconBadge tone={tile.iconTone} size='xs'>
              <tile.icon className='size-3' />
            </IconBadge>
            <span className='line-clamp-1 leading-snug'>{tile.label}</span>
          </div>
          <div className='text-foreground text-lg font-semibold tracking-tight sm:text-2xl'>
            {tile.value}
          </div>
          <p className='text-muted-foreground/70 line-clamp-1 text-[11px] leading-relaxed sm:text-xs'>
            {tile.description}
          </p>
        </div>
      ))}
    </div>
  )
}

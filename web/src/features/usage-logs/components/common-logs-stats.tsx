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
import { useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { Skeleton } from '@/components/ui/skeleton'
import { formatLogQuota } from '@/lib/format'
import { requireServerSuccess } from '@/lib/server-error-message'
import { cn } from '@/lib/utils'

import { getLogStats, getUserCacheStats, getUserLogStats } from '../api'
import { DEFAULT_CACHE_STATS, DEFAULT_LOG_STATS } from '../constants'
import { buildApiParams } from '../lib/utils'
import { useLogsViewScope, useUsageLogsContext } from './usage-logs-provider'

const route = getRouteApi('/_authenticated/usage-logs/$section')

function StatBadge(props: {
  label: string
  value: string | number
  accent: string
}) {
  return (
    <span className='border-border/60 bg-muted/25 inline-flex h-7 items-center gap-2 rounded-md border px-2.5 text-xs shadow-xs'>
      <span className={cn('h-3.5 w-0.5 rounded-full', props.accent)} />
      <span className='text-muted-foreground'>{props.label}</span>
      <span className='text-foreground/85 font-mono font-semibold tabular-nums'>
        {props.value}
      </span>
    </span>
  )
}

export function CommonLogsStats() {
  const { t } = useTranslation()
  const { isAdminView: isAdmin } = useLogsViewScope()
  const searchParams = route.useSearch()
  const { sensitiveVisible } = useUsageLogsContext()

  const { data: stats, isLoading } = useQuery({
    queryKey: ['usage-logs-stats', isAdmin, searchParams],
    queryFn: async () => {
      const params = buildApiParams({
        page: 1,
        pageSize: 1,
        searchParams,
        columnFilters: [],
        isAdmin,
      })

      const result = isAdmin
        ? requireServerSuccess(await getLogStats(params))
        : requireServerSuccess(await getUserLogStats(params))

      return result.success
        ? result.data || DEFAULT_LOG_STATS
        : DEFAULT_LOG_STATS
    },
    placeholderData: (previousData) => previousData,
  })

  // Per-user cache hit rate. User view only: the endpoint is self-scoped by
  // design, and admins get no aggregate here (channel-level detail stays in
  // the admin log table).
  const { data: cacheStats, isLoading: cacheLoading } = useQuery({
    queryKey: ['usage-logs-cache-stats', searchParams],
    enabled: !isAdmin,
    queryFn: async () => {
      const params = buildApiParams({
        page: 1,
        pageSize: 1,
        searchParams,
        columnFilters: [],
        isAdmin: false,
      })
      const result = requireServerSuccess(await getUserCacheStats(params))
      return result.success ? result.data || DEFAULT_CACHE_STATS : DEFAULT_CACHE_STATS
    },
    placeholderData: (previousData) => previousData,
  })

  // Denominator semantics differ by relay format: Claude-native rows store
  // prompt_tokens with cache reads subtracted (so prompt+cache = total input),
  // while OpenAI-semantic rows store raw prompt_tokens that already include
  // cached tokens. The formula below is exact for Claude rows (Vantyr's
  // dominant traffic) and slightly overestimates for OpenAI rows; clamping to
  // [0, 100] keeps the mixed-usage blend sane.
  const cacheTokens = cacheStats?.cache_tokens || 0
  const cacheDenominator = (cacheStats?.prompt_tokens || 0) + cacheTokens
  const cacheHitRate =
    cacheDenominator > 0
      ? `${Math.min(100, Math.max(0, Math.round((cacheTokens / cacheDenominator) * 100)))}%`
      : '—'

  if (isLoading || (!isAdmin && cacheLoading)) {
    return (
      <div className='flex items-center gap-2'>
        <Skeleton className='h-7 w-[150px] rounded-md' />
        <Skeleton className='h-7 w-[100px] rounded-md' />
        <Skeleton className='h-7 w-[120px] rounded-md' />
        {!isAdmin && <Skeleton className='h-7 w-[110px] rounded-md' />}
      </div>
    )
  }

  return (
    <div className='flex flex-wrap items-center gap-2'>
      <StatBadge
        label={t('Usage')}
        value={sensitiveVisible ? formatLogQuota(stats?.quota || 0) : '••••'}
        accent='bg-sky-500/70'
      />
      <StatBadge
        label={t('RPM')}
        value={stats?.rpm || 0}
        accent='bg-rose-500/65'
      />
      <StatBadge
        label={t('TPM')}
        value={stats?.tpm || 0}
        accent='bg-slate-400/70'
      />
      {!isAdmin && (
        <StatBadge
          label={t('Cache hit')}
          value={cacheHitRate}
          accent='bg-emerald-500/70'
        />
      )}
    </div>
  )
}

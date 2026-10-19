import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Route as RouteIcon } from 'lucide-react'
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
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { ConfirmDialog } from '@/components/confirm-dialog'
import {
  StaticDataTable,
  type StaticDataTableColumn,
} from '@/components/data-table'
import { SectionPageLayout } from '@/components/layout'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { TitledCard } from '@/components/ui/titled-card'

import {
  fetchAllChannels,
  getCctestStatus,
  promoteStandby,
  verifyNow,
} from './api'
import { RoutingTable } from './components/routing-table'
import { buildModelSummaries, buildRoutingRows } from './lib/routing-rows'
import type { ModelSummary, RoutingRow } from './types'

// ============================================================================
// Model Routing — per-model channel ladder, merchant attribution,
// cctest verification status and standby cooldowns (admin)
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

function SummaryTable(props: {
  summaries: ModelSummary[]
  columns: StaticDataTableColumn<ModelSummary>[]
}) {
  const { t } = useTranslation()
  if (props.summaries.length === 0) {
    return (
      <p className='text-muted-foreground text-sm'>{t('No models found')}</p>
    )
  }
  return (
    <StaticDataTable
      data={props.summaries}
      columns={props.columns}
      getRowKey={(row) => row.model}
    />
  )
}

export function ModelRouting() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [verifyingChannelId, setVerifyingChannelId] = useState<number | null>(
    null
  )
  const [promoteConfirmModel, setPromoteConfirmModel] = useState<string | null>(
    null
  )

  const channelsQuery = useQuery({
    queryKey: ['model-routing', 'channels'],
    queryFn: fetchAllChannels,
    retry: false,
    staleTime: 60_000,
  })

  const cctestQuery = useQuery({
    queryKey: ['model-routing', 'cctest'],
    queryFn: getCctestStatus,
    retry: false,
    staleTime: 60_000,
    meta: { errorToast: false } as const,
  })

  const monitorDown = cctestQuery.isError

  const rows = useMemo(
    () => buildRoutingRows(channelsQuery.data ?? [], cctestQuery.data),
    [channelsQuery.data, cctestQuery.data]
  )
  const summaries = useMemo(
    () => buildModelSummaries(rows, Math.floor(Date.now() / 1000)),
    [rows]
  )

  const verifyMutation = useMutation({
    mutationFn: (row: RoutingRow) => verifyNow(row.channelName, row.model),
    onMutate: (row) => setVerifyingChannelId(row.channelId),
    onSuccess: (result, row) => {
      toast.success(
        t('{{model}} on {{channel}}: {{verdict}}', {
          model: row.model,
          channel: result.channel ?? row.channelName,
          verdict: result.verdict,
        })
      )
    },
    onError: (error) => {
      toast.error(t('Verification failed'))
      void error
    },
    onSettled: () => {
      setVerifyingChannelId(null)
      void queryClient.invalidateQueries({ queryKey: ['model-routing'] })
    },
  })

  const promoteMutation = useMutation({
    mutationFn: (model: string) => promoteStandby(model),
    onSuccess: (result) => {
      if (result.promoted) {
        toast.success(
          t('Promoted {{standby}} ({{verdict}})', {
            standby: result.promoted,
            verdict: result.verdict ?? t('inconclusive'),
          })
        )
      } else {
        toast.warning(
          t('No standby promoted — next standby will be tried next cycle')
        )
      }
    },
    onError: (error) => {
      toast.error(t('Standby promotion failed'))
      void error
    },
    onSettled: () => {
      setPromoteConfirmModel(null)
      void queryClient.invalidateQueries({ queryKey: ['model-routing'] })
    },
  })

  function handleVerify(row: RoutingRow) {
    verifyMutation.mutate(row)
  }

  const summaryColumns: StaticDataTableColumn<ModelSummary>[] = [
    {
      id: 'model',
      header: t('Model'),
      cell: (row) => <span className='font-mono text-sm'>{row.model}</span>,
    },
    {
      id: 'active',
      header: t('Active Channel'),
      cell: (row) =>
        row.activeChannelName ? (
          <span className='font-mono text-sm'>{row.activeChannelName}</span>
        ) : (
          <StatusBadge
            variant='danger'
            label={t('No active channel')}
            copyable={false}
          />
        ),
    },
    {
      id: 'verdict',
      header: t('Verification'),
      cell: (row) => {
        if (monitorDown) {
          return (
            <span className='text-muted-foreground text-sm'>
              {t('Monitor unavailable')}
            </span>
          )
        }
        if (row.verdict == null) {
          return (
            <span className='text-muted-foreground text-sm'>
              {t('Not checked')}
            </span>
          )
        }
        return (
          <StatusBadge
            variant={verdictVariant(row.verdict)}
            label={row.verdict}
            copyable={false}
          />
        )
      },
    },
    {
      id: 'standbys',
      header: t('Standbys'),
      cell: (row) =>
        row.standbyFresh + row.standbyCooldown > 0 ? (
          <span className='text-sm'>{formatStandbys(row)}</span>
        ) : (
          <span className='text-muted-foreground text-sm'>—</span>
        ),
    },
    {
      id: 'actions',
      header: '',
      cell: (row) => {
        if (monitorDown || row.standbyFresh + row.standbyCooldown === 0) {
          return null
        }
        const isThisRow =
          promoteMutation.isPending && promoteConfirmModel === row.model
        return (
          <Button
            variant='outline'
            size='sm'
            disabled={promoteMutation.isPending}
            onClick={() => setPromoteConfirmModel(row.model)}
          >
            {isThisRow ? t('Promoting…') : t('Promote standby')}
          </Button>
        )
      },
    },
  ]

  function formatStandbys(row: ModelSummary): React.ReactNode {
    const parts: React.ReactNode[] = []
    if (row.standbyFresh > 0) {
      parts.push(`${row.standbyFresh} ${t('ready')}`)
    }
    if (row.standbyCooldown > 0) {
      parts.push(`${row.standbyCooldown} ${t('on cooldown')}`)
    }
    return (
      <span className='text-muted-foreground text-sm'>{parts.join(' · ')}</span>
    )
  }

  return (
    <SectionPageLayout>
      <SectionPageLayout.Title>{t('Model Routing')}</SectionPageLayout.Title>
      <SectionPageLayout.Actions>
        <Button
          variant='outline'
          size='sm'
          onClick={() =>
            void queryClient.invalidateQueries({ queryKey: ['model-routing'] })
          }
        >
          <RefreshCw />
          {t('Refresh')}
        </Button>
      </SectionPageLayout.Actions>
      <SectionPageLayout.Content>
        <div className='mx-auto flex w-full max-w-7xl flex-col gap-4 sm:gap-5'>
          {monitorDown && (
            <TitledCard
              title={t('Monitor unavailable — showing routing only')}
              icon={<RouteIcon className='h-4 w-4' />}
              iconTone='warning'
              disableHoverEffect
            >
              <p className='text-muted-foreground text-sm'>
                {t(
                  'The cctest monitor status endpoint did not answer. Channel ladder, priorities and statuses are still shown; verification verdicts, cooldowns and actions are unavailable.'
                )}
              </p>
            </TitledCard>
          )}

          <TitledCard
            title={t('Per-model overview')}
            icon={<RouteIcon className='h-4 w-4' />}
            disableHoverEffect
          >
            {channelsQuery.isLoading ? (
              <Skeleton className='h-12 w-64' />
            ) : (
              <SummaryTable summaries={summaries} columns={summaryColumns} />
            )}
          </TitledCard>

          <TitledCard
            title={t('Routing ladder (all assignments)')}
            icon={<RouteIcon className='h-4 w-4' />}
            disableHoverEffect
          >
            {channelsQuery.isLoading ? (
              <Skeleton className='h-12 w-64' />
            ) : (
              <RoutingTable
                rows={rows}
                canVerify={!monitorDown}
                onVerify={handleVerify}
                verifyingChannelId={verifyingChannelId}
              />
            )}
          </TitledCard>

          <ConfirmDialog
            open={promoteConfirmModel !== null}
            onOpenChange={(open) => {
              if (!open) setPromoteConfirmModel(null)
            }}
            title={t('Promote standby')}
            desc={t(
              'Rotate {{model}} to a different merchant: the active pin is disabled immediately, the next standby is enabled and verified. Live routing changes now.',
              { model: promoteConfirmModel ?? '' }
            )}
            confirmText={t('Promote')}
            handleConfirm={() => {
              if (promoteConfirmModel) {
                promoteMutation.mutate(promoteConfirmModel)
              }
            }}
            isLoading={promoteMutation.isPending}
          />
        </div>
      </SectionPageLayout.Content>
    </SectionPageLayout>
  )
}

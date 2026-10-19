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
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Route as RouteIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { EmptyState } from '@/components/empty-state'
import { SectionPageLayout } from '@/components/layout'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { TitledCard } from '@/components/ui/titled-card'

import {
  fetchAllChannels,
  getCctestStatus,
  promoteStandby,
  verifyNow,
} from './api'
import { AttentionStrip } from './components/attention-strip'
import { KpiTiles } from './components/kpi-tiles'
import { ModelDetailDrawer } from './components/model-detail-drawer'
import { ModelRoutingCard } from './components/model-routing-card'
import { buildModelSummaries, buildRoutingRows } from './lib/routing-rows'
import type { ModelSummary, RoutingRow } from './types'

// ============================================================================
// Model Routing dashboard — KPI tiles, needs-attention strip, per-model
// health cards, detail drawer (ladder + standby pool + verify/promote)
// ============================================================================

function ModelCardGrid(props: {
  loading: boolean
  summaries: ModelSummary[]
  onOpen: (model: string) => void
}) {
  const { t } = useTranslation()
  if (props.loading) {
    return (
      <div className='grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2 xl:grid-cols-3'>
        {[0, 1, 2, 3, 4, 5].map((index) => (
          <Skeleton key={index} className='h-40 rounded-xl' />
        ))}
      </div>
    )
  }
  if (props.summaries.length === 0) {
    return <EmptyState title={t('No models found')} />
  }
  return (
    <div className='grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2 xl:grid-cols-3'>
      {props.summaries.map((summary) => (
        <ModelRoutingCard
          key={summary.model}
          summary={summary}
          onOpen={props.onOpen}
        />
      ))}
    </div>
  )
}

export function ModelRouting() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [verifyingChannelId, setVerifyingChannelId] = useState<number | null>(
    null
  )
  const [openModel, setOpenModel] = useState<string | null>(null)

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
  const loading = channelsQuery.isLoading

  const rows = useMemo(
    () => buildRoutingRows(channelsQuery.data ?? [], cctestQuery.data),
    [channelsQuery.data, cctestQuery.data]
  )
  const summaries = useMemo(
    () => buildModelSummaries(rows, Math.floor(Date.now() / 1000)),
    [rows]
  )
  const openSummary = useMemo(
    () => summaries.find((summary) => summary.model === openModel) ?? null,
    [summaries, openModel]
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
      void queryClient.invalidateQueries({ queryKey: ['model-routing'] })
    },
  })

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

          <KpiTiles
            summaries={summaries}
            lastCycleAt={cctestQuery.data?.last_cycle_at ?? null}
            monitorDown={monitorDown}
            enforce={cctestQuery.data?.enforce ?? true}
            loading={loading}
          />

          {!loading && (
            <AttentionStrip summaries={summaries} onOpen={setOpenModel} />
          )}

          <TitledCard
            title={t('Models')}
            icon={<RouteIcon className='h-4 w-4' />}
            disableHoverEffect
          >
            <ModelCardGrid
              loading={loading}
              summaries={summaries}
              onOpen={setOpenModel}
            />
          </TitledCard>

          <ModelDetailDrawer
            model={openModel}
            summary={openSummary}
            rows={rows}
            canVerify={!monitorDown}
            onVerify={(row) => verifyMutation.mutate(row)}
            onPromote={(model) => promoteMutation.mutate(model)}
            verifyPending={
              verifyMutation.isPending && verifyingChannelId !== null
            }
            promotePending={promoteMutation.isPending}
            onOpenChange={(next) => {
              if (!next) setOpenModel(null)
            }}
          />
        </div>
      </SectionPageLayout.Content>
    </SectionPageLayout>
  )
}

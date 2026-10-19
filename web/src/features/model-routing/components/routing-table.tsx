import i18next from 'i18next'
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

import {
  StaticDataTable,
  type StaticDataTableColumn,
} from '@/components/data-table'
import { EmptyState } from '@/components/empty-state'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toIntlLocale } from '@/i18n/languages'
import { formatNumber } from '@/lib/format'

import type { RoutingRow } from '../types'

// Channel status → badge variant (mirrors the Channels console).
const STATUS_VARIANTS: Record<number, 'success' | 'neutral' | 'warning'> = {
  1: 'success',
  2: 'neutral',
  3: 'warning',
}

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

function locale(): string | undefined {
  return toIntlLocale(i18next.resolvedLanguage || i18next.language)
}

function formatRemaining(seconds: number): string {
  const hours = seconds / 3600
  if (hours >= 1) {
    return `${formatNumber(Math.ceil(hours), locale())}h`
  }
  return `${formatNumber(Math.max(1, Math.ceil(seconds / 60)), locale())}m`
}

export function RoutingTable(props: {
  rows: RoutingRow[]
  canVerify: boolean
  onVerify: (row: RoutingRow) => void
  verifyingChannelId: number | null
}) {
  const { t } = useTranslation()
  const [modelFilter, setModelFilter] = useState('')
  const [groupFilter, setGroupFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')

  const groups = useMemo(
    () => [...new Set(props.rows.map((row) => row.group))].sort(),
    [props.rows]
  )

  const filtered = useMemo(
    () =>
      props.rows.filter((row) => {
        const modelMatch =
          modelFilter === '' ||
          row.model.toLowerCase().includes(modelFilter.toLowerCase())
        const groupMatch = groupFilter === 'all' || row.group === groupFilter
        let statusMatch = true
        if (statusFilter === 'enabled') statusMatch = row.status === 1
        else if (statusFilter === 'disabled') statusMatch = row.status !== 1
        return modelMatch && groupMatch && statusMatch
      }),
    [props.rows, modelFilter, groupFilter, statusFilter]
  )

  function cooldownCell(row: RoutingRow): React.ReactNode {
    if (row.cooldownExpiresAt === null) {
      return <span className='text-muted-foreground text-sm'>—</span>
    }
    const remaining = row.cooldownExpiresAt - Date.now() / 1000
    if (remaining <= 0) {
      return <StatusBadge variant='info' label={t('Cooldown expired')} />
    }
    return (
      <StatusBadge
        variant='warning'
        label={t('expires in {{hours}}', { hours: formatRemaining(remaining) })}
      />
    )
  }

  const columns: StaticDataTableColumn<RoutingRow>[] = [
    {
      id: 'model',
      header: t('Model'),
      cell: (row) => <span className='font-mono text-sm'>{row.model}</span>,
    },
    {
      id: 'group',
      header: t('Group'),
      cell: (row) => <StatusBadge variant='neutral' label={row.group} />,
    },
    {
      id: 'channel',
      header: t('Channel'),
      cell: (row) => (
        <span className='font-mono text-sm'>{row.channelName}</span>
      ),
    },
    {
      id: 'merchant',
      header: t('Merchant'),
      cell: (row) =>
        row.merchant ? (
          <span className='font-mono text-sm'>{row.merchant}</span>
        ) : (
          <span className='text-muted-foreground text-sm'>—</span>
        ),
    },
    {
      id: 'priority',
      header: t('Priority'),
      cell: (row) => <span className='font-mono text-sm'>{row.priority}</span>,
    },
    {
      id: 'status',
      header: t('Status'),
      cell: (row) => {
        let label = t('Auto disabled')
        if (row.status === 1) label = t('Enabled')
        else if (row.status === 2) label = t('Disabled')
        return (
          <StatusBadge
            variant={STATUS_VARIANTS[row.status] ?? 'neutral'}
            label={label}
            copyable={false}
          />
        )
      },
    },
    {
      id: 'verification',
      header: t('Verification'),
      cell: (row) => {
        if (row.quarantined) {
          return (
            <StatusBadge
              variant='danger'
              label={t('Quarantined')}
              copyable={false}
            />
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
      id: 'cooldown',
      header: t('Cooldown'),
      cell: cooldownCell,
    },
    {
      id: 'actions',
      header: '',
      cell: (row) =>
        props.canVerify && row.status === 1 ? (
          <Button
            variant='outline'
            size='sm'
            disabled={props.verifyingChannelId !== null}
            onClick={() => props.onVerify(row)}
          >
            {props.verifyingChannelId === row.channelId
              ? t('Verifying…')
              : t('Verify now')}
          </Button>
        ) : null,
    },
  ]

  return (
    <div className='space-y-3'>
      <div className='flex flex-wrap items-center gap-2'>
        <Input
          placeholder={t('Search models')}
          value={modelFilter}
          onChange={(event) => setModelFilter(event.target.value)}
          className='h-8 w-56'
          aria-label={t('Search models')}
        />
        <Select
          value={groupFilter}
          onValueChange={(value) => {
            if (value) setGroupFilter(value)
          }}
        >
          <SelectTrigger className='h-8 w-36' aria-label={t('Group')}>
            <SelectValue placeholder={t('All groups')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='all'>{t('All groups')}</SelectItem>
            {groups.map((group) => (
              <SelectItem key={group} value={group}>
                {group}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={statusFilter}
          onValueChange={(value) => {
            if (value) setStatusFilter(value)
          }}
        >
          <SelectTrigger className='h-8 w-36' aria-label={t('Status')}>
            <SelectValue placeholder={t('All statuses')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='all'>{t('All statuses')}</SelectItem>
            <SelectItem value='enabled'>{t('Enabled')}</SelectItem>
            <SelectItem value='disabled'>{t('Disabled')}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <StaticDataTable
        data={filtered}
        columns={columns}
        getRowKey={(row) => `${row.model}/${row.group}/${row.channelId}`}
        empty={filtered.length === 0}
        emptyContent={<EmptyState title={t('No channels serve this model')} />}
      />
    </div>
  )
}

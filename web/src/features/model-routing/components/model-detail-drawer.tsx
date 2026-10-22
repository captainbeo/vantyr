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
import {
  ArrowUpRight,
  BadgeCheck,
  ListOrdered,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ConfirmDialog } from '@/components/confirm-dialog'
import {
  sideDrawerContentClassName,
  SideDrawerSection,
  SideDrawerSectionHeader,
} from '@/components/drawer-layout'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { toIntlLocale } from '@/i18n/languages'
import { formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'

import { CheckHistory } from './check-history'
import type {
  MerchantHealth,
  ModelSummary,
  RoutingRow,
  StandbyEntry,
} from '../types'

// ============================================================================
// Model detail drawer — the drill-down: full routing ladder (ordered,
// grouped by tier), standby pool, and the two actions (verify, promote).
// The ladder doubles as the "table view" for the card grid.
// ============================================================================

const STATUS_VARIANTS: Record<number, 'success' | 'neutral' | 'warning'> = {
  1: 'success',
  2: 'neutral',
  3: 'warning',
}

const PASS_VERDICTS = new Set(['official', 'attr_match'])

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

function blockedReason(
  state: StandbyEntry['state'],
  t: (key: string) => string
): string {
  if (state === 'quarantined') {
    return t(
      'Quarantined — click "Verify this merchant" first; a passing check releases it and enables picking.'
    )
  }
  if (state === 'cooldown') {
    return t(
      'Cooling down after a failed check — verify it; a passing result makes it pickable now.'
    )
  }
  return t('Not pickable — this entry has no merchant id.')
}

function statusLabel(status: number, t: (key: string) => string): string {
  if (status === 1) return t('Enabled')
  if (status === 2) return t('Disabled')
  return t('Auto Disabled')
}

export function ModelDetailDrawer(props: {
  model: string | null
  summary: ModelSummary | null
  rows: RoutingRow[]
  canVerify: boolean
  onVerify: (row: RoutingRow) => void
  onPromote: (model: string, merchant?: string) => void
  onVerifyChannel: (channelName: string, model: string) => void
  verifyPending: boolean
  verifyPendingChannel: string | null
  promotePending: boolean
  merchantHealth: Record<string, MerchantHealth> | null
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pickedMerchant, setPickedMerchant] = useState<string | null>(null)
  const [groupFilter, setGroupFilter] = useState<string>('default')

  const open = props.model !== null && props.summary !== null

  const modelGroups = useMemo(
    () =>
      [
        ...new Set(
          props.rows
            .filter((row) => row.model === props.model)
            .map((row) => row.group)
        ),
      ].sort(),
    [props.rows, props.model]
  )
  // reset the filter when a different model opens (groups differ per model)
  useEffect(() => {
    if (modelGroups.length > 0 && !modelGroups.includes(groupFilter)) {
      setGroupFilter(modelGroups[0] ?? 'default')
    }
  }, [modelGroups, groupFilter])

  const modelRows = props.rows.filter(
    (row) => row.model === props.model && row.group === groupFilter
  )

  const activeRow = modelRows.find(
    (row) =>
      row.status === 1 && row.channelName === props.summary?.activeChannelName
  )

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (next) return
        setConfirmOpen(false)
        props.onOpenChange(false)
      }}
    >
      <SheetContent
        side='right'
        className={sideDrawerContentClassName('sm:max-w-2xl lg:max-w-3xl')}
      >
        <SheetHeader className='sr-only'>
          <SheetTitle>{props.model ?? ''}</SheetTitle>
          <SheetDescription>{t('Model routing details')}</SheetDescription>
        </SheetHeader>
        <div className='flex-1 overflow-y-auto px-4 pt-11 pb-5 sm:px-6 sm:pt-12 sm:pb-6'>
          {props.summary && (
            <div className='flex flex-col gap-6'>
              <SideDrawerSection>
                <div className='flex items-start justify-between gap-3'>
                  <div className='min-w-0'>
                    <h2 className='text-foreground truncate font-mono text-lg font-semibold'>
                      {props.model}
                    </h2>
                    <div className='text-muted-foreground mt-1.5 flex flex-wrap items-center gap-2 text-xs'>
                      {props.summary.activeChannelName ? (
                        <>
                          <span>{t('serving via')}</span>
                          <span className='text-foreground/90 font-mono'>
                            {props.summary.activeChannelName}
                          </span>
                          {props.summary.activeMerchant && (
                            <span className='text-muted-foreground/70'>
                              {t('merchant {{id}}', {
                                id: props.summary.activeMerchant,
                              })}
                            </span>
                          )}
                        </>
                      ) : (
                        <span className='text-destructive'>
                          {t('No active channel — traffic fails over')}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className='flex flex-wrap gap-2 pt-1'>
                  <Button
                    variant='outline'
                    size='sm'
                    disabled={
                      !props.canVerify || props.verifyPending || !activeRow
                    }
                    onClick={() => activeRow && props.onVerify(activeRow)}
                  >
                    <RefreshCw />
                    {props.verifyPending ? t('Verifying…') : t('Verify now')}
                  </Button>
                  {props.summary.standbys.length > 0 && props.canVerify && (
                    <Button
                      variant='outline'
                      size='sm'
                      disabled={props.promotePending}
                      onClick={() => setConfirmOpen(true)}
                    >
                      <ArrowUpRight />
                      {props.promotePending
                        ? t('Promoting…')
                        : t('Promote standby')}
                    </Button>
                  )}
                </div>
              </SideDrawerSection>

              <SideDrawerSection>
                <SideDrawerSectionHeader
                  title={t('Routing ladder')}
                  description={t(
                    'Requests walk this list top to bottom. The first enabled channel serves the request.'
                  )}
                  icon={<ListOrdered className='size-4' />}
                />
                {modelGroups.length > 1 && (
                  <div className='flex items-center gap-2'>
                    <span className='text-muted-foreground text-xs'>
                      {t('Group')}
                    </span>
                    <Select
                      value={groupFilter}
                      onValueChange={(value) => {
                        if (value) setGroupFilter(value)
                      }}
                    >
                      <SelectTrigger
                        className='h-7 w-32'
                        aria-label={t('Group')}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {modelGroups.map((group) => (
                          <SelectItem key={group} value={group}>
                            {group}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <LadderRows
                  rows={modelRows}
                  activeChannelName={
                    groupFilter === 'default'
                      ? props.summary.activeChannelName
                      : (modelRows.find((row) => row.status === 1)
                          ?.channelName ?? null)
                  }
                />
              </SideDrawerSection>

              {props.summary.standbys.length > 0 && (
                <SideDrawerSection>
                  <SideDrawerSectionHeader
                    title={t('Standby pool')}
                    description={t(
                      'Pinned merchant keys kept disabled. Verify a merchant, then use it to swap the active pin. A failed verification benches it for the cooldown.'
                    )}
                    icon={<BadgeCheck className='size-4' />}
                  />
                  <div className='flex flex-col gap-2'>
                    {props.summary.standbys.map((entry) => (
                      <StandbyRow
                        key={entry.channelId}
                        entry={entry}
                        merchantHealth={
                          entry.merchant != null
                            ? props.merchantHealth?.[entry.merchant]
                            : undefined
                        }
                        canAct={props.canVerify}
                        verifyingThis={
                          props.verifyPendingChannel === entry.channelName
                        }
                        pickingThis={
                          props.promotePending &&
                          pickedMerchant === entry.merchant
                        }
                        onVerify={() =>
                          props.onVerifyChannel(
                            entry.channelName,
                            props.model ?? ''
                          )
                        }
                        onUse={() => {
                          if (entry.merchant) {
                            setPickedMerchant(entry.merchant)
                            setConfirmOpen(true)
                          }
                        }}
                      />
                    ))}
                  </div>
                </SideDrawerSection>
              )}

              <ConfirmDialog
                open={confirmOpen && props.model !== null}
                onOpenChange={(open) => {
                  if (!open) setPickedMerchant(null)
                  setConfirmOpen(open)
                }}
                title={
                  pickedMerchant
                    ? t('Promote this merchant')
                    : t('Promote standby')
                }
                desc={
                  pickedMerchant
                    ? t(
                        'Rotate {{model}} to merchant {{merchant}}: the active pin is disabled immediately, this standby is enabled and verified. Live routing changes now.',
                        { model: props.model ?? '', merchant: pickedMerchant }
                      )
                    : t(
                        'Rotate {{model}} to a different merchant: the active pin is disabled immediately, the healthiest standby is enabled and verified. Live routing changes now.',
                        { model: props.model ?? '' }
                      )
                }
                confirmText={t('Promote')}
                handleConfirm={() => {
                  if (props.model) {
                    props.onPromote(props.model, pickedMerchant ?? undefined)
                  }
                }}
                isLoading={props.promotePending}
              />
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function LadderRows(props: {
  rows: RoutingRow[]
  activeChannelName: string | null
}) {
  const { t } = useTranslation()
  if (props.rows.length === 0) {
    return (
      <p className='text-muted-foreground text-sm'>
        {t('No channels serve this model')}
      </p>
    )
  }
  return (
    <ol className='flex flex-col gap-1.5'>
      {props.rows.map((row, index) => {
        const isActive = row.channelName === props.activeChannelName
        return (
          <li
            key={`${row.channelId}-${row.group}`}
            className={cn(
              'flex items-center justify-between gap-3 rounded-lg border px-3 py-2',
              isActive
                ? 'border-primary/40 bg-primary/5'
                : 'bg-muted/25 border-transparent'
            )}
          >
            <div className='flex min-w-0 items-center gap-2.5'>
              <span className='text-muted-foreground/60 w-4 shrink-0 font-mono text-xs tabular-nums'>
                {index + 1}
              </span>
              <div className='min-w-0'>
                <div
                  className={cn(
                    'truncate font-mono text-xs font-medium',
                    isActive ? 'text-foreground' : 'text-foreground/80'
                  )}
                >
                  {row.channelName}
                </div>
                <div className='text-muted-foreground mt-0.5 flex items-center gap-1.5 text-[11px]'>
                  <span>{row.provider}</span>
                  {row.merchant && (
                    <span className='text-muted-foreground/60'>
                      · {t('merchant {{id}}', { id: row.merchant })}
                    </span>
                  )}
                  <span className='text-muted-foreground/60'>
                    · P{row.priority}
                  </span>
                </div>
              </div>
            </div>
            <div className='flex shrink-0 flex-col items-end gap-1'>
              <div className='flex items-center gap-1.5'>
                <StatusBadge
                  variant={STATUS_VARIANTS[row.status] ?? 'neutral'}
                  label={statusLabel(row.status, t)}
                  copyable={false}
                />
              </div>
              <CheckHistory history={row.history} />
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function StandbyRow(props: {
  entry: StandbyEntry
  merchantHealth: MerchantHealth | undefined
  canAct: boolean
  verifyingThis: boolean
  pickingThis: boolean
  onVerify: () => void
  onUse: () => void
}) {
  const { t } = useTranslation()
  const e = props.entry
  const h = props.merchantHealth
  // A merchant is pickable when it has an id and is either ready, or in
  // cooldown but just re-verified clean (the green check is the operator's
  // evidence the merchant recovered — let them act on it). Quarantined pins
  // need a passing "Verify" first (which releases the quarantine) before the
  // button becomes usable; until then the action is the verify, not the pick.
  const verifiedPass = e.verdict != null && PASS_VERDICTS.has(e.verdict)
  const usable =
    e.merchant != null &&
    (e.state === 'ready' || (e.state === 'cooldown' && verifiedPass))

  return (
    <div className='bg-muted/40 flex flex-col gap-2 rounded-lg border px-3 py-2.5'>
      <div className='flex items-center justify-between gap-3'>
        <div className='min-w-0'>
          <div className='text-foreground truncate font-mono text-xs font-medium'>
            {e.channelName}
          </div>
          <div className='text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]'>
            <span>
              {e.merchant
                ? t('merchant {{id}}', { id: e.merchant })
                : t('standby pin')}
            </span>
            {h?.supplier && (
              <span className='text-muted-foreground/70'>· {h.supplier}</span>
            )}
            {h?.success_rate != null && (
              <span
                className={cn(h.healthy ? 'text-success' : 'text-destructive')}
              >
                ·{' '}
                {t('{{rate}}% success', {
                  rate: Math.round((h.success_rate ?? 0) / 100),
                })}
              </span>
            )}
            {h?.price_micros != null && (
              <span className='text-foreground/80'>
                ·{' '}
                {t('${{price}}/1M in', {
                  price: (h.price_micros / 1_000_000).toFixed(2),
                })}
              </span>
            )}
            {h && !h.healthy && (
              <span className='text-warning'>
                · {t('A6: not currently eligible')}
              </span>
            )}
          </div>
        </div>
        <div className='flex shrink-0 items-center gap-2'>
          <CheckHistory history={e.history} />
          {e.state === 'ready' && (
            <StatusBadge
              variant='success'
              label={t('Ready')}
              copyable={false}
            />
          )}
          {e.state === 'cooldown' && (
            <StatusBadge
              variant='warning'
              label={t('expires in {{hours}}', {
                hours: formatRemaining(
                  (e.cooldownExpiresAt ?? 0) - Date.now() / 1000
                ),
              })}
              copyable={false}
            />
          )}
          {e.state === 'quarantined' && (
            <StatusBadge
              variant='danger'
              icon={ShieldAlert}
              label={t('Quarantined')}
              copyable={false}
            />
          )}
        </div>
      </div>
      {e.state === 'quarantined' &&
        e.verdict != null &&
        PASS_VERDICTS.has(e.verdict) && (
          <p className='text-muted-foreground border-t pt-2 text-[11px]'>
            {t(
              'Passes re-check but stays quarantined — click "Verify this merchant" to release it (a passing check lifts the quarantine).'
            )}
          </p>
        )}
      {props.canAct && (
        <div className='flex items-center gap-2 border-t pt-2'>
          <Button
            variant='ghost'
            size='sm'
            className='h-7'
            disabled={props.verifyingThis}
            onClick={props.onVerify}
          >
            <RefreshCw />
            {props.verifyingThis ? t('Verifying…') : t('Verify this merchant')}
          </Button>
          <Button
            variant='outline'
            size='sm'
            className='h-7'
            disabled={!usable || props.pickingThis}
            onClick={props.onUse}
          >
            <ArrowUpRight />
            {props.pickingThis ? t('Promoting…') : t('Use this merchant')}
          </Button>
        </div>
      )}
      {props.canAct && !usable && (
        <p className='text-muted-foreground border-t pt-2 text-[11px]'>
          {blockedReason(e.state, t)}
        </p>
      )}
    </div>
  )
}

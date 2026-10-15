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
import { Infinity as InfinityIcon, CheckCircle2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { SectionPageLayout } from '@/components/layout'
import { TitledCard } from '@/components/ui/titled-card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { getUnlimitedUsageInfo } from './api'

// ============================================================================
// Unlimited Usage apply page
// ============================================================================

export function UnlimitedUsage() {
  const { t } = useTranslation()

  const info = useQuery({
    queryKey: ['unlimited', 'info'],
    queryFn: getUnlimitedUsageInfo,
    retry: false,
  })

  const data = info.data?.data
  const remaining = data?.remaining
  const capacity = data?.capacity
  const userHasActive = data?.user_has_active === true

  return (
    <SectionPageLayout>
      <SectionPageLayout.Title>
        {t('Apply for Unlimited Usage')}
      </SectionPageLayout.Title>
      <SectionPageLayout.Content>
        <div className='mx-auto flex w-full max-w-7xl flex-col gap-4 sm:gap-5'>
          {userHasActive ? (
            <TitledCard
              title={t('Unlimited active')}
              icon={<InfinityIcon className='h-4 w-4' />}
              iconTone='success'
              disableHoverEffect
            >
              <p className='text-muted-foreground text-sm'>
                {t(
                  'Your account already has an active unlimited subscription. No action needed — enjoy flat-rate usage on every model.'
                )}
              </p>
            </TitledCard>
          ) : (
            <TitledCard
              title={t('Available slots')}
              icon={<InfinityIcon className='h-4 w-4' />}
              disableHoverEffect
            >
              {info.isLoading || remaining === undefined ? (
                <Skeleton className='h-12 w-64' />
              ) : (
                <div className='flex flex-wrap items-baseline gap-x-3 gap-y-1'>
                  <span className='font-display text-3xl font-semibold'>
                    {remaining}
                    <span className='text-muted-foreground ml-1 font-mono text-base font-normal'>
                      / {capacity}
                    </span>
                  </span>
                  <span className='text-muted-foreground text-sm'>
                    {remaining > 0
                      ? t('slots currently available')
                      : t('all slots are taken — join the waiting list')}
                  </span>
                </div>
              )}
            </TitledCard>
          )}

          <TitledCard
            title={t('What unlimited usage includes')}
            icon={<CheckCircle2 className='h-4 w-4' />}
            disableHoverEffect
          >
            <ul className='text-muted-foreground space-y-2.5 text-sm'>
              <li>
                {t(
                  'Every model on the platform — Claude, GPT and more — at one flat monthly price, no per-token billing.'
                )}
              </li>
              <li>
                {t(
                  'Higher rate limits than pay-as-you-go accounts, tuned for sustained agent workloads.'
                )}
              </li>
              <li>
                {t(
                  'The same genuine upstream models as pay-as-you-go: no swapped or downgraded variants, ever.'
                )}
              </li>
              <li>
                {t(
                  'A fixed number of seats. Capacity is limited so every unlimited member keeps full speed.'
                )}
              </li>
            </ul>
          </TitledCard>

          <TitledCard
            title={t('How to apply')}
            icon={<CheckCircle2 className='h-4 w-4' />}
            disableHoverEffect
          >
            <ol className='text-muted-foreground list-decimal space-y-2.5 pl-5 text-sm'>
              <li>
                {t(
                  'Join our Discord server and open a ticket in the support channel.'
                )}
              </li>
              <li>
                {t(
                  'Tell us a little about your expected usage (models, requests per day, agent or interactive use).'
                )}
              </li>
              <li>
                {t(
                  'We review applications as slots free up and reply in the ticket with the payment link.'
                )}
              </li>
              <li>
                {t(
                  'Once payment completes, your account is upgraded automatically — usually within minutes.'
                )}
              </li>
            </ol>
            <div className='mt-4 flex flex-wrap items-center gap-3'>
              <Button
                variant='outline'
                render={
                  <a
                    href='https://discord.gg/BNBdHZqGFb'
                    target='_blank'
                    rel='noopener noreferrer'
                  />
                }
              >
                {t('Open a ticket on Discord')}
              </Button>
            </div>
          </TitledCard>
        </div>
      </SectionPageLayout.Content>
    </SectionPageLayout>
  )
}

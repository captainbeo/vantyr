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
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import mark from '@/assets/vantyr-mark.png'
import { Button } from '@/components/ui/button'
import { useStatus } from '@/hooks/use-status'

import { LiveDot, SectionCode, StatTileGrid } from './vantyr-sections'

interface HeroProps {
  className?: string
  isAuthenticated?: boolean
}

// Relay map sample lanes — decorative marketing data.
const POOLS = ['POOL 1', 'POOL 2', 'POOL 3'] as const
const UPSTREAMS = ['CODEX', 'CLAUDE'] as const

export function Hero(props: HeroProps) {
  const { t } = useTranslation()
  const { status } = useStatus()
  const docsUrl =
    (status?.docs_link as string | undefined) || 'https://docs.newapi.pro'

  const primaryHref = props.isAuthenticated ? '/dashboard' : '/sign-up'
  const primaryLabel = props.isAuthenticated
    ? t('Go to Dashboard')
    : t('Get API key')

  return (
    <section className='relative overflow-hidden border-b'>
      <div className='mx-auto grid max-w-7xl gap-12 px-5 py-16 md:py-24 lg:grid-cols-[1.1fr_1fr]'>
        <div>
          <SectionCode code='SYS-00'>
            {t('Genuine models · Vantyr pricing')}
          </SectionCode>
          <h1 className='font-display mt-5 text-5xl leading-[0.98] font-semibold md:text-7xl'>
            {t('The real models.')}
            <br />
            <span className='text-primary'>{t('98% off the bill.')}</span>
          </h1>
          <p className='text-muted-foreground mt-6 max-w-lg text-lg'>
            {t(
              'Every request reaches genuine Claude and Codex. No swapped, distilled or downgraded models, ever. You pay a fraction of official API rates, or go unlimited for one flat monthly price.'
            )}
          </p>

          <StatTileGrid className='mt-8 max-w-lg lg:grid-cols-2'>
            <div className='bg-background p-4'>
              <div className='label-mono'>{t('vs official API rates')}</div>
              <div className='font-display mt-1 text-3xl font-semibold'>
                {t('up to')} <span className='text-primary'>{t('98%')}</span>{' '}
                {t('less')}
              </div>
            </div>
            <div className='bg-background p-4'>
              <div className='label-mono'>{t('Unlimited usage')}</div>
              <div className='font-display mt-1 text-3xl font-semibold'>
                $180
                <span className='text-muted-foreground ml-1 font-mono text-sm font-normal'>
                  /mo
                </span>
              </div>
            </div>
          </StatTileGrid>

          <div className='mt-8 flex flex-wrap items-center gap-3'>
            <Button
              className='rounded-sm font-mono tracking-wider uppercase'
              render={<Link to={primaryHref} />}
            >
              {primaryLabel}
            </Button>
            <Button
              variant='outline'
              className='rounded-sm font-mono tracking-wider uppercase'
              render={
                <a href={docsUrl} target='_blank' rel='noopener noreferrer' />
              }
            >
              {t('Read the docs')}
            </Button>
            <LiveDot caption={t('Real models only')} />
          </div>

          <pre
            data-slot='glass-box'
            className='bg-card mt-10 max-w-lg overflow-hidden rounded-sm border p-4 font-mono text-[13px] leading-relaxed'
          >
            <span className='text-muted-foreground'># before</span>
            {'\n'}base_url ={' '}
            <span className='line-through opacity-50'>
              https://api.anthropic.com
            </span>
            {'\n'}
            <span className='text-muted-foreground'># after</span>
            {'\n'}base_url ={' '}
            <span className='text-primary'>https://vantyr.xyz</span>
          </pre>
        </div>

        {/* Relay map: the map itself, frameless — no panel box, no
         * header, no region latency strip. Sized like the old panel
         * (max-w ~26rem, 4/3) so it doesn't stretch the full column. */}
        <div className='relative mx-auto aspect-[4/3] w-full max-w-[26rem]'>
          <svg
            viewBox='0 0 400 300'
            className='absolute inset-0 h-full w-full'
            data-slot='relay-map'
            aria-hidden
          >
            {(
              [
                [60, 70],
                [60, 150],
                [60, 230],
              ] as const
            ).map(([x, y], i) => (
              <g key={POOLS[i]}>
                <path
                  d={`M${x + 40} ${y} C 160 ${y}, 160 150, 200 150`}
                  fill='none'
                  stroke='var(--border)'
                  strokeWidth='1.5'
                />
                <path
                  d={`M${x + 40} ${y} C 160 ${y}, 160 150, 200 150`}
                  fill='none'
                  stroke='var(--primary)'
                  strokeWidth='1.5'
                  className='animate-flow'
                />
                <rect
                  x={x - 40}
                  y={y - 14}
                  width='80'
                  height='28'
                  rx='2'
                  className='relay-chip'
                  fill='var(--secondary)'
                  stroke='var(--border)'
                />
                <text
                  x={x}
                  y={y + 4}
                  textAnchor='middle'
                  fontFamily='var(--font-mono-stack)'
                  fontSize='10'
                  fill='var(--muted-foreground)'
                >
                  {POOLS[i]}
                </text>
              </g>
            ))}
            {UPSTREAMS.map((label, i) => {
              const x = 340
              const y = i === 0 ? 100 : 200
              return (
                <g key={label}>
                  <path
                    d={`M240 150 C 290 150, 280 ${y}, ${x - 40} ${y}`}
                    fill='none'
                    stroke='var(--success)'
                    strokeWidth='1.5'
                    className='animate-flow'
                  />
                  <rect
                    x={x - 40}
                    y={y - 14}
                    width='80'
                    height='28'
                    rx='2'
                    className='relay-chip'
                    fill='var(--secondary)'
                    stroke='var(--border)'
                  />
                  <text
                    x={x}
                    y={y + 4}
                    textAnchor='middle'
                    fontFamily='var(--font-mono-stack)'
                    fontSize='10'
                    fill='var(--foreground)'
                  >
                    {label}
                  </text>
                </g>
              )
            })}
            <circle
              cx='220'
              cy='150'
              r='34'
              className='relay-hub'
              fill='var(--background)'
              stroke='var(--primary)'
              strokeWidth='1.5'
            />
            <circle
              cx='220'
              cy='150'
              r='44'
              fill='none'
              stroke='var(--primary)'
              strokeOpacity='0.25'
              strokeDasharray='2 4'
            />
          </svg>
          <img
            src={mark}
            alt=''
            className='absolute top-1/2 left-[55%] h-12 w-12 -translate-x-1/2 -translate-y-1/2'
          />
        </div>
      </div>
    </section>
  )
}

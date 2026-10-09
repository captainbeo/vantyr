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
import { useTranslation } from 'react-i18next'

import { SectionCode } from './vantyr-sections'

interface FeaturesProps {
  className?: string
}

interface ProblemDef {
  num: string
  tag: string
  problem: string
  fix: string
  desc: string
}

const COMPARE_COLS: readonly string[] = [
  'Official APIs',
  'Other providers',
  'Vantyr',
]

export function Features(_props: FeaturesProps) {
  const { t } = useTranslation()

  const problems: ProblemDef[] = [
    {
      num: '01',
      tag: 'Limits',
      problem: t('Daily, weekly and monthly caps'),
      fix: t('No usage limits. Ever.'),
      desc: t(
        'No daily, weekly or monthly ceilings. Code all night without hitting a wall mid-task.'
      ),
    },
    {
      num: '02',
      tag: 'Models',
      problem: t('Locked to one vendor'),
      fix: t('Every major model, one key.'),
      desc: t(
        'Claude and Codex behind one key. Switch models per project, or per request, by changing a single name.'
      ),
    },
    {
      num: '03',
      tag: 'Price',
      problem: t('Official API bills that scale with every token'),
      fix: t('At least 98% cheaper.'),
      desc: t(
        'A minimum of 98% below official Anthropic and OpenAI rates, or one flat $180/month for unlimited use.'
      ),
    },
    {
      num: '04',
      tag: 'Integrity',
      problem: t('Providers that quietly swap in cheaper models'),
      fix: t('Real models. Tested daily.'),
      desc: t(
        'No model swapping, distilling or downgrading. We test every model daily to confirm you get what you asked for.'
      ),
    },
    {
      num: '05',
      tag: 'Support',
      problem: t('Setup docs nobody answers questions about'),
      fix: t('Easy setup, real support.'),
      desc: t(
        'A step-by-step setup guide for Claude Code, Codex and SDKs, and a support team that answers any question.'
      ),
    },
    {
      num: '06',
      tag: 'Drop-in',
      problem: t('Rewriting code to change providers'),
      fix: t('Change one URL.'),
      desc: t(
        'Same request and response format as the official APIs. Your tools keep working, you just pay less.'
      ),
    },
  ]

  const compare: readonly (readonly string[])[] = [
    [
      t('Usage limits'),
      t('Daily / weekly caps'),
      t('Often throttled'),
      t('None'),
    ],
    [t('Price vs official'), '100%', t('Varies'), t('98%+ less')],
    [t('Models'), t('One vendor'), t('Mixed'), t('Claude + Codex, one key')],
    [t('Genuine models'), t('Yes'), t('Often swapped'), t('Yes, tested daily')],
    [t('Setup'), t('Per vendor'), t('Unclear'), t('One URL change + guide')],
    [t('Support'), t('Ticket queue'), t('Rare'), t('Answers any question')],
  ]

  return (
    <section className='border-b'>
      <div className='mx-auto max-w-7xl px-5 py-20'>
        <SectionCode code='WHY-00'>{t('What Vantyr fixes')}</SectionCode>
        <h2 className='font-display mt-3 max-w-3xl text-3xl font-semibold md:text-5xl'>
          {t(
            'Official APIs throttle you, bill you heavily and lock you to one vendor.'
          )}{' '}
          <span className='text-primary'>{t('Vantyr removes all three.')}</span>
        </h2>

        <div
          data-slot='tile-grid'
          className='bg-border mt-12 grid gap-px overflow-hidden rounded-sm border md:grid-cols-2 lg:grid-cols-3'
        >
          {problems.map((p) => (
            <div key={p.tag} className='bg-background p-6'>
              <div className='flex items-center justify-between'>
                <span className='text-primary font-mono text-sm'>{p.num}</span>
                <span className='label-mono'>{p.tag}</span>
              </div>
              <p className='text-muted-foreground decoration-destructive/60 mt-6 font-mono text-xs line-through'>
                {p.problem}
              </p>
              <h3 className='font-display mt-2 text-xl font-semibold'>
                {p.fix}
              </h3>
              <p className='text-muted-foreground mt-2 text-sm'>{p.desc}</p>
            </div>
          ))}
        </div>

        {/* Side-by-side comparison */}
        <div className='mt-20'>
          <SectionCode code='WHY-01'>{t('Side by side')}</SectionCode>
          <h2 className='font-display mt-3 text-3xl font-semibold md:text-4xl'>
            {t('Why choose Vantyr.')}
          </h2>
          <div
            data-slot='glass-box'
            className='bg-card mt-10 overflow-hidden rounded-sm border'
          >
            <table className='w-full font-mono text-[13px]'>
              <thead>
                <tr className='border-b'>
                  <th className='label-mono px-4 py-3 text-left font-normal'>
                    <span aria-hidden='true'>·</span>
                  </th>
                  {COMPARE_COLS.map((col) => (
                    <th
                      key={col}
                      className='label-mono px-4 py-3 text-left font-normal'
                    >
                      {col === 'Vantyr' ? (
                        <span className='text-primary'>{col}</span>
                      ) : (
                        col
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {compare.map((row) => (
                  <tr key={row[0]} className='border-b last:border-b-0'>
                    <td className='text-muted-foreground px-4 py-3'>
                      {row[0]}
                    </td>
                    <td className='px-4 py-3'>{row[1]}</td>
                    <td className='px-4 py-3'>{row[2]}</td>
                    <td className='text-primary px-4 py-3'>{row[3]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  )
}

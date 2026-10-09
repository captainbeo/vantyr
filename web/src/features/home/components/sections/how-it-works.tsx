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

interface HowItWorksProps {
  className?: string
}

interface StepDef {
  num: string
  title: string
  desc: string
}

export function HowItWorks(_props: HowItWorksProps) {
  const { t } = useTranslation()

  const steps: StepDef[] = [
    {
      num: '01',
      title: t('Issue a key'),
      desc: t(
        'Subscribe and get a single key. No provider accounts to juggle.'
      ),
    },
    {
      num: '02',
      title: t('Swap the base URL'),
      desc: t(
        'Point your SDK at Vantyr. Request and response shapes stay identical.'
      ),
    },
    {
      num: '03',
      title: t('Ship'),
      desc: t(
        'Requests are served by the upstream model over pooled capacity at a lower rate.'
      ),
    },
  ]

  return (
    <section className='border-b'>
      <div className='mx-auto max-w-7xl px-5 py-20'>
        <SectionCode code='SYS-01'>{t('Integration')}</SectionCode>
        <h2 className='font-display mt-3 text-3xl font-semibold md:text-4xl'>
          {t('Three steps. No rewrite.')}
        </h2>
        <ol
          data-slot='tile-grid'
          className='bg-border mt-10 grid list-none gap-px overflow-hidden rounded-sm border md:grid-cols-3'
        >
          {steps.map((s) => (
            <li key={s.num} className='bg-background p-6'>
              <div className='text-primary font-mono text-sm'>{s.num}</div>
              <h3 className='font-display mt-6 text-xl font-semibold'>
                {s.title}
              </h3>
              <p className='text-muted-foreground mt-2 text-sm'>{s.desc}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

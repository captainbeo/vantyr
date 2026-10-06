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

interface StatsProps {
  className?: string
}

interface StatDef {
  label: string
  value: string
  unit: string
}

export function Stats(_props: StatsProps) {
  const { t } = useTranslation()

  const stats: StatDef[] = [
    { label: t('Median added latency'), value: '38', unit: 'ms' },
    { label: t('Relay uptime · 90d'), value: '99.97', unit: '%' },
    { label: t('Off official rates'), value: '98', unit: '%+' },
    { label: t('Usage limits'), value: '0', unit: t('caps') },
  ]

  return (
    <section className='border-b' aria-label={t('Relay statistics')}>
      <div className='mx-auto grid max-w-7xl grid-cols-2 md:grid-cols-4'>
        {stats.map((s) => (
          <div
            key={s.label}
            className='border-r px-5 py-8 last:border-r-0 [&:nth-child(2)]:max-md:border-r-0 max-md:[&:nth-child(-n+2)]:border-b md:border-b-0'
          >
            <div className='label-mono'>{s.label}</div>
            <div className='mt-2 font-display text-4xl font-semibold'>
              {s.value}
              <span className='ml-1 text-lg text-primary'>{s.unit}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

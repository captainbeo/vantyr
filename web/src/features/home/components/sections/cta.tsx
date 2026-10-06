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

import { Button } from '@/components/ui/button'

import { ControlRoomPanel, LiveDot, SectionCode } from './vantyr-sections'

interface CTAProps {
  className?: string
  isAuthenticated?: boolean
}

// Sample request stream — decorative marketing data (model names are literals).
const LOG_ROWS: readonly (readonly string[])[] = [
  ['01:51:04.112', 'POST', '/v1/messages', 'claude-sonnet', '200', '412ms'],
  ['01:51:04.380', 'POST', '/v1/responses', 'codex', '200', '655ms'],
  ['01:51:04.902', 'POST', '/v1/messages', 'claude-opus', '200', '1.12s'],
  [
    '01:51:05.017',
    'POST',
    '/v1/chat/completions',
    'codex-mini',
    '200',
    '201ms',
  ],
  ['01:51:05.344', 'POST', '/v1/messages', 'claude-haiku', '200', '133ms'],
]

export function CTA(props: CTAProps) {
  const { t } = useTranslation()

  return (
    <>
      {/* Transparency: request log */}
      <section className='border-b'>
        <div className='mx-auto grid max-w-7xl gap-10 px-5 py-20 lg:grid-cols-[1fr_1.6fr]'>
          <div>
            <SectionCode code='SYS-02'>{t('Transparency')}</SectionCode>
            <h2 className='mt-3 font-display text-3xl font-semibold md:text-4xl'>
              {t('Every request, accounted for.')}
            </h2>
            <p className='mt-4 text-muted-foreground'>
              {t(
                'Per-request logs with model, status, latency and token cost. Nothing is stored beyond what billing needs.'
              )}
            </p>
          </div>
          <ControlRoomPanel
            title={t('stream · sample')}
            right={<LiveDot caption='● REC' tone='primary' />}
          >
            <table className='w-full font-mono text-[12px]'>
              <caption className='sr-only'>{t('Sample request log')}</caption>
              <tbody>
                {LOG_ROWS.map((row) => (
                  <tr key={row[0]} className='border-b last:border-b-0'>
                    <td className='px-4 py-2 text-muted-foreground'>{row[0]}</td>
                    <td className='px-2 py-2'>{row[1]}</td>
                    <td className='px-2 py-2'>{row[2]}</td>
                    <td className='px-2 py-2 text-primary'>{row[3]}</td>
                    <td className='px-2 py-2 text-success'>{row[4]}</td>
                    <td className='px-4 py-2 text-right text-muted-foreground'>
                      {row[5]}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ControlRoomPanel>
        </div>
      </section>

      {/* Final CTA */}
      {props.isAuthenticated ? null : (
        <section>
          <div className='mx-auto flex max-w-7xl flex-col items-start justify-between gap-6 px-5 py-16 md:flex-row md:items-center'>
            <h2 className='font-display text-3xl font-semibold md:text-4xl'>
              {t('Open a channel.')}{' '}
              <span className='text-primary'>{t('Keep coding.')}</span>
            </h2>
            <Button
              className='rounded-sm font-mono tracking-wider uppercase'
              render={<Link to='/pricing' />}
            >
              {t('View Pricing')}
            </Button>
          </div>
        </section>
      )}
    </>
  )
}

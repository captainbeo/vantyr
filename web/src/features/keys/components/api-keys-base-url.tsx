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
import { Globe } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { CopyButton } from '@/components/copy-button'
import { useApiInfo } from '@/features/dashboard/hooks/use-status-data'
import { useStatus } from '@/hooks/use-status'

/** Shorten "Anthropic-compatible" -> "Anthropic" for the toolbar row. */
function shortLabel(route: string): string {
  return route.replace(/-compatible$/i, '').trim()
}

export function ApiKeysBaseUrl() {
  const { t } = useTranslation()
  const { status } = useStatus()
  const { items } = useApiInfo()

  const serverAddress =
    (typeof status?.server_address === 'string' &&
      status.server_address.trim()) ||
    ''

  const rows = items.length
    ? items.map((item) => ({
        label: shortLabel(item.route),
        url: item.url,
        fullLabel: item.route,
      }))
    : [
        {
          label: t('API Base URL'),
          url: serverAddress || window.location.origin,
          fullLabel: t('API Base URL'),
        },
      ]

  return (
    <div className='bg-muted/40 flex h-8 min-w-0 items-center gap-2 rounded-lg border px-3'>
      <Globe
        className='text-muted-foreground size-3.5 shrink-0'
        aria-hidden='true'
      />
      <div className='flex min-w-0 items-center gap-x-4'>
        {rows.map((row) => (
          <div
            key={row.url}
            className='flex min-w-0 items-center gap-1.5'
          >
            <span className='text-muted-foreground shrink-0 text-[11px] leading-none'>
              {row.label}
            </span>
            <code className='truncate text-xs leading-none font-medium select-all'>
              {row.url}
            </code>
            <CopyButton
              value={row.url}
              size='icon'
              tooltip={t('Copy API URL')}
              aria-label={`${t('Copy API URL')}: ${row.fullLabel} (${row.url})`}
              className='size-6 shrink-0 [&_svg]:size-3'
            />
          </div>
        ))}
      </div>
    </div>
  )
}

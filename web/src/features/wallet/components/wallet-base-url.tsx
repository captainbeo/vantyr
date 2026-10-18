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

export function WalletBaseUrl() {
  const { t } = useTranslation()
  const { status } = useStatus()
  const { items } = useApiInfo()

  const serverAddress =
    (typeof status?.server_address === 'string' &&
      status.server_address.trim()) ||
    ''

  const primary = items.length ? items[0] : null
  const url = primary?.url || serverAddress || window.location.origin
  const label = primary?.route || t('API Base URL')

  return (
    <div className='bg-muted/40 flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2'>
      <Globe
        className='text-muted-foreground size-3.5 shrink-0'
        aria-hidden='true'
      />
      <div className='min-w-0 flex-1'>
        <div className='text-muted-foreground text-[11px] leading-4'>
          {label}
        </div>
        <code className='block truncate text-xs font-medium select-all'>
          {url}
        </code>
      </div>
      <CopyButton
        value={url}
        size='icon'
        tooltip={t('Copy API URL')}
        aria-label={`${t('Copy API URL')}: ${url}`}
        className='shrink-0'
      />
    </div>
  )
}

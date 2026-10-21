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

import { COMMUNITY_LINKS } from '@/components/community-links'
import { cn } from '@/lib/utils'

/**
 * Hero community buttons: one glass pill per channel, rendered under the
 * sign-up video. `data-slot='glass-box'` opts each button into the theme's
 * poured-glass surface (blur + sheen + hairline edge); the brand icon keeps
 * its brand tint while the label and arrow inherit the glass foreground.
 */
export function Community(props: { className?: string }) {
  const { t } = useTranslation()

  return (
    <div
      data-slot='community-buttons'
      className={cn('grid grid-cols-2 gap-3', props.className)}
    >
      {COMMUNITY_LINKS.map((link) => (
        <a
          key={link.key}
          href={link.href}
          target='_blank'
          rel='noopener noreferrer'
          aria-label={t(link.ctaKey)}
          title={t(link.ctaKey)}
          data-slot='glass-box'
          className={cn(
            'group flex items-center gap-3 rounded-sm border px-4 py-3',
            'transition-transform duration-200 hover:-translate-y-0.5',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
          )}
        >
          <link.icon
            className={cn('size-6 shrink-0', link.accentClass)}
            aria-hidden='true'
          />
          <span className='font-display min-w-0 flex-1 truncate text-sm font-semibold'>
            {t(link.nameKey)}
          </span>
          <span
            aria-hidden='true'
            className='text-muted-foreground shrink-0 transition-transform duration-200 group-hover:translate-x-0.5'
          >
            →
          </span>
        </a>
      ))}
    </div>
  )
}

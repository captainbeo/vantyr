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
import { useEffect, useState, type ComponentType, type SVGProps } from 'react'
import { useTranslation } from 'react-i18next'

import { COMMUNITY_LINKS } from '@/components/community-links'
import { cn } from '@/lib/utils'

const IconChatLines: ComponentType<SVGProps<SVGSVGElement>> = (props) => (
  <svg
    viewBox='0 0 24 24'
    fill='none'
    stroke='currentColor'
    strokeWidth='2'
    strokeLinecap='round'
    strokeLinejoin='round'
    aria-hidden='true'
    {...props}
  >
    <path d='M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z' />
  </svg>
)

const IconClose: ComponentType<SVGProps<SVGSVGElement>> = (props) => (
  <svg
    viewBox='0 0 24 24'
    fill='none'
    stroke='currentColor'
    strokeWidth='2'
    strokeLinecap='round'
    strokeLinejoin='round'
    aria-hidden='true'
    {...props}
  >
    <path d='M18 6 6 18M6 6l12 12' />
  </svg>
)

/**
 * Floating community widget for public pages: a fixed bottom-right pill that
 * expands into labeled Discord / Telegram links. Closed by default so it
 * never blocks content; the expanded panel also closes on Escape.
 */
export function CommunityFloat() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  return (
    <div className='fixed right-4 bottom-4 z-50 flex flex-col items-end gap-3 md:right-6 md:bottom-6'>
      <div
        role='group'
        aria-label={t('Community links')}
        // Collapsed = visually and accessibly hidden: opacity-0 leaves links
        // in the a11y tree, where they duplicate the page's other community
        // links and confuse screen-reader users. aria-hidden removes them
        // until the panel is actually open.
        aria-hidden={!open}
        className={cn(
          'bg-card/90 flex flex-col gap-1 overflow-hidden rounded-sm border p-2 shadow-lg backdrop-blur-xl transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]',
          open
            ? 'pointer-events-auto translate-y-0 opacity-100'
            : 'pointer-events-none translate-y-2 opacity-0'
        )}
      >
        {COMMUNITY_LINKS.map((link) => (
          <a
            key={link.key}
            href={link.href}
            target='_blank'
            rel='noopener noreferrer'
            className='hover:bg-muted flex items-center gap-3 rounded-sm px-3 py-2.5 transition-colors duration-150'
          >
            <span
              className={cn(
                'inline-flex size-8 shrink-0 items-center justify-center rounded-sm border',
                link.toneClass
              )}
            >
              <link.icon className='size-4' aria-hidden='true' />
            </span>
            <span className='min-w-0'>
              <span className='block text-sm leading-tight font-medium'>
                {t(link.labelKey)}
              </span>
              <span className='text-muted-foreground block text-xs leading-tight'>
                {t(link.handleKey)}
              </span>
            </span>
          </a>
        ))}
      </div>

      <button
        type='button'
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? t('Close community links') : t('Open community links')}
        className={cn(
          'bg-card/90 hover:border-primary/50 focus-visible:border-primary/50 inline-flex h-11 items-center gap-2.5 rounded-sm border px-4 shadow-lg backdrop-blur-xl transition-colors duration-200',
          'focus-visible:outline-none'
        )}
      >
        {open ? (
          <IconClose className='size-4' />
        ) : (
          <IconChatLines className='text-primary size-4' />
        )}
        <span className='font-mono text-[11px] tracking-wider uppercase'>
          {t('Community')}
        </span>
      </button>
    </div>
  )
}

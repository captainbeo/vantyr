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
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Shared "Control Room" primitives for the Vantyr marketing sections.
 *
 * Mirrors the Lovable design system: mono micro-labels with a signal
 * code prefix, hairline-grid stat tiles, and bordered panels. Colors all
 * flow through theme tokens so the sections render correctly under any
 * preset, not just `vantyr`.
 */

/** Mono section label: `<code> / Title`, code rendered in the accent. */
export function SectionCode(props: {
  code: string
  children: ReactNode
  className?: string
}) {
  return (
    <p className={cn('label-mono', props.className)}>
      <span className='text-primary'>{props.code}</span> / {props.children}
    </p>
  )
}

/**
 * Hairline grid of stat tiles: `grid gap-px bg-border` with background
 * children, so the 1px gaps read as borders.
 */
export function StatTileGrid(props: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'grid grid-cols-2 gap-px overflow-hidden rounded-sm border bg-border lg:grid-cols-4',
        props.className
      )}
    >
      {props.children}
    </div>
  )
}

/** Bordered panel with a mono header bar — the console "Panel" look. */
export function ControlRoomPanel(props: {
  title: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={cn('rounded-sm border bg-card', props.className)}>
      <header className='flex items-center justify-between gap-3 border-b px-4 py-2.5'>
        <span className='label-mono truncate'>{props.title}</span>
        {props.right}
      </header>
      <div className={props.bodyClassName}>{props.children}</div>
    </section>
  )
}

/** Live status dot: blinking accent/health marker with mono caption. */
export function LiveDot(props: { caption: string; tone?: 'ok' | 'primary' }) {
  const toneClass = props.tone === 'primary' ? 'bg-primary' : 'bg-success'
  return (
    <span className='flex items-center gap-2 font-mono text-[11px] tracking-wider text-muted-foreground uppercase'>
      <span className={cn('size-1.5 rounded-full', toneClass, 'animate-blink')} />
      {props.caption}
    </span>
  )
}

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
import type { ComponentType, SVGProps } from 'react'

import { IconDiscordSolid } from '@/assets/brand-icons/icon-discord-solid'
import { IconTelegramSolid } from '@/assets/brand-icons/icon-telegram-solid'

export interface CommunityLinkDef {
  key: 'discord' | 'telegram'
  href: string
  icon: ComponentType<SVGProps<SVGSVGElement>>
  /** i18n keys — always render through t(). */
  nameKey: string
  labelKey: string
  ctaKey: string
  handleKey: string
  /** Brand-tinted chip (floating panel) + icon accent, light/dark safe. */
  toneClass: string
  accentClass: string
}

// Permanent invite/targets — the same links the header and /docs guide carry.
export const COMMUNITY_LINKS: readonly CommunityLinkDef[] = [
  {
    key: 'discord',
    href: 'https://discord.gg/BNBdHZqGFb',
    icon: IconDiscordSolid,
    nameKey: 'Discord',
    labelKey: 'Discord community',
    ctaKey: 'Join Discord',
    handleKey: 'discord.gg/BNBdHZqGFb',
    toneClass:
      'border-[#5865F2]/30 bg-[#5865F2]/10 text-[#5865F2] dark:text-[#8b96f5]',
    accentClass: 'text-[#5865F2] dark:text-[#8b96f5]',
  },
  {
    key: 'telegram',
    href: 'https://t.me/vantyrapi',
    icon: IconTelegramSolid,
    nameKey: 'Telegram',
    labelKey: 'Telegram',
    ctaKey: 'Join Telegram',
    handleKey: '@vantyrapi',
    toneClass:
      'border-[#229ED9]/30 bg-[#229ED9]/10 text-[#1a8bbf] dark:text-[#54b7e4]',
    accentClass: 'text-[#1a8bbf] dark:text-[#54b7e4]',
  },
] as const

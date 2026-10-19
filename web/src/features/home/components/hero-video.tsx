/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

For commercial licensing, please contact support@quantumnous.com
*/
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/utils'

interface HeroVideoProps {
  className?: string
}

// The signup explainer video rendered by the Remotion project (separate
// repo, D:\worktrees\vantyr-video) — one file per interface language,
// served by Caddy from /static/video/. English is the fallback for any
// language without a rendered file.
const VIDEO_MAP: Record<string, string> = {
  en: '/static/video/vantyr-signup-en.mp4',
  fr: '/static/video/vantyr-signup-fr.mp4',
  ru: '/static/video/vantyr-signup-ru.mp4',
  ja: '/static/video/vantyr-signup-ja.mp4',
  vi: '/static/video/vantyr-signup-vi.mp4',
  zhCN: '/static/video/vantyr-signup-zh-CN.mp4',
  zhTW: '/static/video/vantyr-signup-zh-TW.mp4',
  de: '/static/video/vantyr-signup-de.mp4',
  nl: '/static/video/vantyr-signup-nl.mp4',
  tr: '/static/video/vantyr-signup-tr.mp4',
  es: '/static/video/vantyr-signup-es.mp4',
  ar: '/static/video/vantyr-signup-ar.mp4',
}

export function HeroVideo(props: HeroVideoProps) {
  const { i18n, t } = useTranslation()
  const [isPlaying, setIsPlaying] = useState(false)

  // Interface codes (zhCN/zhTW) are the map keys; files use the same tag.
  const lang = i18n.resolvedLanguage || i18n.language
  const src = VIDEO_MAP[lang] ?? VIDEO_MAP.en

  return (
    <div
      data-slot='hero-video'
      className={cn(
        'border-foreground/10 relative overflow-hidden rounded-sm border',
        props.className
      )}
      aria-label={t('How to sign up with Vantyr')}
    >
      {isPlaying ? (
        <video
          src={src}
          controls
          autoPlay
          playsInline
          preload='metadata'
          className='aspect-video w-full bg-black'
        />
      ) : (
        <button
          type='button'
          onClick={() => setIsPlaying(true)}
          className='group absolute inset-0 flex aspect-video w-full items-center justify-center bg-black'
          aria-label={t('Play the sign-up video')}
        >
          {/* Poster frame: brand gradient + mark + play affordance. */}
          <span className='absolute inset-0 bg-gradient-to-br from-[#10141c] via-black to-[#07090e]' />
          <span className='relative z-10 flex flex-col items-center gap-4'>
            <span className='border-primary/50 text-primary group-hover:bg-primary group-hover:text-primary-foreground flex size-16 items-center justify-center rounded-full border-2 transition-colors'>
              {/* Play triangle */}
              <svg viewBox='0 0 24 24' className='size-7' fill='currentColor' aria-hidden='true'>
                <path d='M8 5v14l11-7z' />
              </svg>
            </span>
            <span className='text-muted-foreground font-mono text-sm tracking-wider uppercase'>
              {t('How to sign up · 60 seconds')}
            </span>
          </span>
        </button>
      )}
    </div>
  )
}

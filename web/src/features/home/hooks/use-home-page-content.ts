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
import i18next from 'i18next'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { isHttpUrl } from '@/lib/content-format'
import { handleServerError } from '@/lib/handle-server-error'

import { getHomePageContent } from '../api'
import { selectHomePageContent } from '../lib/language-content'
import type { HomePageContentResult } from '../types'

const STORAGE_KEY = 'home_page_content'

/**
 * Hook to load and manage custom home page content
 * Supports both Markdown/HTML content and iframe URLs, and per-language
 * variants when the option holds a JSON language map
 */
export function useHomePageContent(): HomePageContentResult {
  const { i18n } = useTranslation()
  const [rawContent, setRawContent] = useState<string>('')
  const [isLoaded, setIsLoaded] = useState(false)

  const language = i18n.resolvedLanguage || i18n.language
  const content = selectHomePageContent(rawContent, language)

  useEffect(() => {
    let mounted = true

    const loadContent = async () => {
      // Load from localStorage first for immediate display
      const cached = localStorage.getItem(STORAGE_KEY)
      if (cached && mounted) {
        setRawContent(cached)
      }

      try {
        const response = await getHomePageContent()
        const { success, data } = response

        if (!mounted) return

        if (success && data) {
          setRawContent(data)
          localStorage.setItem(STORAGE_KEY, data)
        } else {
          // Clear content if API returns empty
          setRawContent('')
          localStorage.removeItem(STORAGE_KEY)
        }
      } catch (error) {
        if (!mounted) return
        handleServerError(error, i18next.t('Failed to load home page content'))
      } finally {
        if (mounted) {
          setIsLoaded(true)
        }
      }
    }

    loadContent()

    return () => {
      mounted = false
    }
  }, [])

  const isUrl = isHttpUrl(content)

  return { content, isLoaded, isUrl }
}

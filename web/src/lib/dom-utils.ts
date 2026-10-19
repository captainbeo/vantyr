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
/**
 * Document-head DOM helpers (favicon, title).
 */
const MARKETING_ROUTES = [
  /^\/$/,
  /^\/about\/?$/,
  /^\/pricing(\/|$)/,
  /^\/rankings\/?$/,
  /^\/privacy-policy\/?$/,
  /^\/user-agreement\/?$/,
]

function isMarketingRoute(pathname: string): boolean {
  return MARKETING_ROUTES.some((re) => re.test(pathname))
}

/**
 * Build the runtime document title for a system name and path.
 *
 * Marketing routes keep the static SEO title from `index.html` untouched so
 * crawlers (and users mid-navigation) always see the descriptive page title;
 * the system name replaces it only on authenticated app routes, where the
 * title is admin branding ("Vantyr — Console") rather than a search target.
 */
export function buildDocumentTitle(systemName: string, pathname: string): string | null {
  const name = systemName.trim()
  if (!name) return null
  if (isMarketingRoute(pathname)) return null
  if (/\s[—-]\s/.test(name)) return name
  return `${name} — Console`
}

/** Apply a runtime title, respecting the marketing-route SEO-title policy. */
export function applyDocumentTitleToDom(systemName: string, pathname: string) {
  if (typeof document === 'undefined') return
  const title = buildDocumentTitle(systemName, pathname)
  if (!title) return
  if (document.title === title) return
  document.title = title
  const metaTitle = document.querySelector(
    'meta[name="title"]'
  ) as HTMLMetaElement | null
  if (metaTitle) metaTitle.setAttribute('content', title)
}

export function applyFaviconToDom(url: string) {
  if (typeof document === 'undefined' || !url) return
  try {
    const next = new URL(url, window.location.href).href
    const existing =
      document.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]')
    if (existing.length === 1 && existing[0].href === next) return
    const link = document.createElement('link')
    link.rel = 'icon'
    link.href = url
    existing.forEach((l) => l.remove())
    document.head.appendChild(link)
  } catch {
    // Ignore malformed URLs
  }
}

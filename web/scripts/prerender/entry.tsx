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
 * Build-time prerender entry: server-render the public landing per locale.
 *
 * Bundled with `bun build` (see run.ts) and executed in Node. NOT part of the
 * shipped SPA bundle — this only produces static HTML shells for crawlers.
 *
 * The landing's normal runtime guards (useHomePageContent, useStatus,
 * useSystemConfig) all degrade gracefully without `window`: they render the
 * default English content path, which is exactly the marketing copy we want
 * indexed. The one piece we DO drive is i18next, set per-locale before render.
 */
import { QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { renderToString } from 'react-dom/server'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import { resources } from '@/i18n/config'
import { Home } from '@/features/home'
import { createAppQueryClient } from '@/lib/query-client'

/** Locales we prerender, as BCP-47 path segments → i18next language codes. */
export const PRERENDER_LOCALES = [
  { path: 'fr', lng: 'fr', bcp47: 'fr' },
  { path: 'ru', lng: 'ru', bcp47: 'ru' },
  { path: 'zh', lng: 'zhCN', bcp47: 'zh-CN' },
  { path: 'zh-TW', lng: 'zhTW', bcp47: 'zh-TW' },
  { path: 'vi', lng: 'vi', bcp47: 'vi' },
  { path: 'ja', lng: 'ja', bcp47: 'ja' },
  { path: 'de', lng: 'de', bcp47: 'de' },
  { path: 'nl', lng: 'nl', bcp47: 'nl' },
  { path: 'tr', lng: 'tr', bcp47: 'tr' },
  { path: 'es', lng: 'es', bcp47: 'es' },
  { path: 'ar', lng: 'ar', bcp47: 'ar', dir: 'rtl' },
] as const

export type PrerenderLocale = (typeof PRERENDER_LOCALES)[number]

// This file is a build-time Node entry (bundled by scripts/prerender/run.mjs),
// never part of the shipped SPA — the react-refresh "only-export-components"
// rule targets dev HMR and doesn't apply here.
/* oxlint-disable react/only-export-components */

async function renderLocale(locale: PrerenderLocale): Promise<string> {
  await i18n.use(initReactI18next).init({
    resources,
    lng: locale.lng,
    fallbackLng: 'en',
    supportedLngs: Object.keys(resources),
    load: 'currentOnly',
    nsSeparator: false,
    interpolation: { escapeValue: false },
  })
  // renderToString is synchronous for our tree (no Suspense data fetching).
  // Wrap Home in the same providers the app root supplies so PublicHeader's
  // useSystemConfig (QueryClient) and TanStack Link/useRouterState (router)
  // resolve. A minimal in-memory router with a single route rendering Home is
  // enough — nothing navigates during a prerender.
  const queryClient = createAppQueryClient()
  // Providers live INSIDE the route component: RouterProvider's own children
  // don't reliably re-render with the matched route's context during SSR, but
  // context through the rendered component tree always does.
  const Landing = () => (
    <QueryClientProvider client={queryClient}>
      <Home />
    </QueryClientProvider>
  )
  const rootRoute = createRootRouteWithContext<{ queryClient: typeof queryClient }>()(
    {}
  )
  const homeRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    component: Landing,
  })
  const router = createRouter({
    routeTree: rootRoute.addChildren([homeRoute]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
    context: { queryClient },
  })
  // Load the matched route before rendering: memory-history routers resolve
  // matches asynchronously, and renderToString alone renders 0 chars without it.
  await router.load()
  return renderToString(<RouterProvider router={router} />)
}

export { renderLocale }

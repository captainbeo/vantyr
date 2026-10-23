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
*/
/**
 * Phase B prerender: server-render the public landing per locale and emit
 * static HTML shells into dist/<locale>/index.html. The SPA stays untouched;
 * Caddy serves these shells at /<locale>/ for crawlers while interactive
 * routes keep loading the SPA.
 *
 * Run with Bun: `bun scripts/prerender/run.mjs` (after `bun run build` so
 * dist/ exists — this writes the locale shells next to dist/index.html).
 */
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const web = path.resolve(here, '..', '..')
const DIST = path.join(web, 'dist')

// ---- Stub image/CSS/three imports so the tree bundles under Bun's Node target.
const assetStub = {
  name: 'asset-stub',
  setup(build) {
    build.onResolve({ filter: /\.(png|jpe?g|svg|webp|gif|woff2?)$/ }, (args) => ({
      path: args.path,
      namespace: 'asset-stub',
    }))
    build.onLoad({ filter: /.*/, namespace: 'asset-stub' }, () => ({
      contents: 'export default "/_asset.png"',
      loader: 'js',
    }))
    build.onResolve({ filter: /\.css$/ }, (args) => ({
      path: args.path,
      namespace: 'css-stub',
    }))
    build.onLoad({ filter: /.*/, namespace: 'css-stub' }, () => ({
      contents: '',
      loader: 'js',
    }))
    // three/@react-three are only reachable via lazy() 3D components Suspense
    // skips during renderToString; their CJS/ESM interop breaks under Bun, so
    // resolve to a catch-all Proxy that fabricates any named export.
    build.onResolve({ filter: /^(three|@react-three\/.*)$/ }, (args) => ({
      path: args.path,
      namespace: 'three-stub',
    }))
    build.onLoad({ filter: /.*/, namespace: 'three-stub' }, () => ({
      contents:
        'const p = new Proxy(function(){}, { get: () => p });\n' +
        'export default p;\n' +
        'export const Canvas = p;\nexport const ContactShadows = p;\n' +
        'export const Environment = p;\nexport const Lightformer = p;\n' +
        'export const OrbitControls = p;\nexport const BufferGeometry = p;\n' +
        'export const Float32BufferAttribute = p;\n' +
        'export const MeshPhysicalMaterial = p;\nexport const DoubleSide = p;',
      loader: 'js',
    }))
  },
}

// ---- Bundle the entry once, cache to scripts/prerender/.build/.
const result = await Bun.build({
  entrypoints: [path.join(here, 'entry.tsx')],
  target: 'node',
  format: 'esm',
  jsx: { runtime: 'automatic', importSource: 'react' },
  tsconfig: path.join(web, 'tsconfig.app.json'),
  plugins: [assetStub],
  outdir: path.join(here, '.build'),
})
if (!result.success) {
  for (const log of result.logs) console.error(log)
  process.exit(1)
}
const mod = await import(result.outputs[0].path)

// ---- Per-locale SEO strings. Description reuses the existing translated
// tagline key; title suffix reuses the existing one-liner, both present in all
// 12 locale files. English stays the default (no path prefix) and is the
// x-default hreflang entry.
const escapeHtml = (s) =>
  String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')

const metaFor = (locale) => {
  const t = (key, fallback) => {
    try {
      // Read from the locale JSON directly (bundle-independent, always current).
      const lng = locale.lng
      let file = lng
      if (lng === 'zhCN') file = 'zh'
      else if (lng === 'zhTW') file = 'zh-TW'
      const data = JSON.parse(
        fs.readFileSync(path.join(web, 'src', 'i18n', 'locales', `${file}.json`), 'utf8')
      )
      const tr = data.translation || data
      return tr[key] || fallback
    } catch {
      return fallback
    }
  }
  const desc = t(
    'Vantyr gives you genuine Claude and Codex access at up to 97% below official rates, without fixed monthly subscriptions, arbitrary usage caps or regional lockouts.',
    'Genuine Claude, GPT and Codex models behind one OpenAI/Anthropic-compatible API. Every channel verified to serve the real model — no swaps, no downgrades — at a fraction of official API prices.'
  )
  // Title suffix: the hero headline, translated in every locale. Two keys form
  // the H1 ("The real models." + "98% off the bill."); joining them gives a
  // short, punchy title that's already translated, unlike the long one-liner.
  const head = t('The real models.', 'The real models.')
  const off = t('98% off the bill.', 'A fraction of official prices')
  const titleSuffix = `${head} ${off}`.trim()
  return {
    title: `Vantyr — ${titleSuffix}`,
    description: desc,
  }
}

// ---- Render each locale and write the shell.
if (!fs.existsSync(path.join(DIST, 'index.html'))) {
  console.error('dist/index.html not found — run `bun run build` first.')
  process.exit(1)
}

const hreflangLinks = [
  ...mod.PRERENDER_LOCALES.map(
    (l) =>
      `    <link rel="alternate" hreflang="${l.bcp47}" href="https://vantyr.xyz/${l.path}/" />`
  ),
  '    <link rel="alternate" hreflang="en" href="https://vantyr.xyz/" />',
  '    <link rel="alternate" hreflang="x-default" href="https://vantyr.xyz/" />',
].join('\n')

let rendered = 0
for (const locale of mod.PRERENDER_LOCALES) {
  const html = await mod.renderLocale(locale)
  if (!html || html.length < 2000) {
    console.error(`SKIP ${locale.path}: rendered too small (${html.length} chars)`)
    continue
  }
  const meta = metaFor(locale)
  const dir = locale.dir === 'rtl' ? 'rtl' : 'ltr'
  const title = escapeHtml(meta.title)
  const description = escapeHtml(meta.description)
  const canonical = `https://vantyr.xyz/${locale.path}/`

  const shell = `<!doctype html>
<html lang="${locale.bcp47}" dir="${dir}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${title}</title>
    <meta name="description" content="${description}" />
    <link rel="canonical" href="${canonical}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Vantyr" />
    <meta property="og:title" content="${title}" />
    <meta property="og:description" content="${description}" />
    <meta property="og:url" content="${canonical}" />
    <meta property="og:image" content="https://vantyr.xyz/og-image.png" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:locale" content="${locale.bcp47.replace('-', '_')}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="${title}" />
    <meta name="twitter:description" content="${description}" />
    <meta name="twitter:image" content="https://vantyr.xyz/og-image.png" />
    <link rel="icon" href="/favicon.ico" />
    <meta name="theme-color" content="#020817" />
${hreflangLinks}
  </head>
  <body data-theme-preset="vantyr" data-theme-font="sans" data-theme-content-layout="full">
    <div id="root" translate="no" class="notranslate">${html}</div>
    <script>
      // Honor the prerendered locale so the SPA (if it ever hydrates) starts in
      // the same language as the shell the crawler and user first saw.
      try { localStorage.setItem('i18nextLng', ${JSON.stringify(locale.lng)}) } catch (e) {}
    </script>
  </body>
</html>
`
  const outDir = path.join(DIST, locale.path)
  fs.mkdirSync(outDir, { recursive: true })
  fs.writeFileSync(path.join(outDir, 'index.html'), shell, 'utf8')
  rendered++
  console.log(`OK ${locale.path.padEnd(6)} -> dist/${locale.path}/index.html  (${html.length} chars, dir=${dir})`)
}

console.log(`\nPrerendered ${rendered}/${mod.PRERENDER_LOCALES.length} locales.`)

// Exit explicitly: the bundled module (imported above) leaves a handle on the
// event loop, so without this the process hangs after printing and the Docker
// build step never completes (observed on the VPS build, 2026-10-23).
process.exit(0)

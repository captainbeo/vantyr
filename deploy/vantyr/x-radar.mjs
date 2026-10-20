#!/usr/bin/env node
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
 * Vantyr topic radar — finds early AI/dev topics worth posting about, scores
 * them for Vantyr relevance, and writes DRAFT queue lines to a staging file
 * for human approval. Nothing is posted by this script; a human promotes a
 * draft into x-queue.txt (the poster picks it up from there).
 *
 * Sources (all read-only, no auth):
 *   - Hacker News: front page + new stories matching our keyword set
 *     (Algolia API — verified working from datacenter IPs).
 *   - OpenAI news RSS (verified working).
 * Reddit JSON/RSS is bot-blocked from datacenter IPs (verified 2026-10-20) and
 * Anthropic has no RSS; f5bot covers Reddit keyword alerts separately (free).
 *
 * Relevance scoring: each source item is scored against topic buckets. Items
 * above the threshold become drafts with a suggested angle, ranked by score.
 *
 * Runs from cron before the poster, so a morning draft is waiting to approve.
 * Files: reads nothing from env secrets; writes data/x-radar/drafts.txt and
 * remembers seen items in data/x-radar/seen.txt so drafts never repeat.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const STATE_DIR = process.env.X_STATE_DIR || path.join(here, 'data', 'x-radar')
const SEEN_FILE = path.join(STATE_DIR, 'seen.txt')
const DRAFTS_FILE = process.env.X_DRAFTS_FILE || path.join(STATE_DIR, 'drafts.txt')

// ---- Topic buckets: bucket name -> keywords that raise the score. ----
// Weighted so a model-release or pricing-swap story outranks generic AI news.
const BUCKETS = [
  { name: 'model-release', weight: 3, words: ['new model', 'released', 'launch', 'gpt-5', 'gpt-6', 'sonnet', 'opus', 'haiku', ' o1', ' o3', ' o4', 'gemini', 'llama', 'deepseek', 'qwen', 'mistral', 'kimi', 'fable'] },
  { name: 'api-pricing', weight: 3, words: ['api price', 'pricing', 'cost per token', 'per million', 'cheaper', 'expensive', 'rate limit', 'billing', 'usage-based', 'token cost'] },
  { name: 'reseller-swap', weight: 4, words: ['reseller', 'model swap', 'swapped', 'downgrad', 'distill', 'not the real', 'fake model', 'wrong model'] },
  // vibecoding checked BEFORE model-release in angle selection: 'claude code'
  // and 'codex' are tools, not model releases — they get the builder angle.
  { name: 'vibecoding', weight: 2, words: ['vibecod', 'vibe cod', 'claude code', 'codex cli', 'cursor', 'copilot', 'windsurf', 'ai agent', 'coding agent', 'agentic', 'codex'] },
  { name: 'dev-tools', weight: 1, words: ['sdk', 'openai-compatible', 'openai compatible', 'api key', 'endpoint', 'base url', 'self-host', 'open source llm'] },
]
const RELEVANCE_THRESHOLD = 3

// ---- Source fetchers. Each returns [{title, url, source, snippet}]. ----
async function fetchHN() {
  const out = []
  // Front page (what's big right now)
  const front = await fetch('https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=40').then((r) => r.json())
  for (const h of front.hits || []) out.push({ title: h.title, url: h.url || `https://news.ycombinator.com/item?id=${h.objectID}`, source: 'hn-front', points: h.points })
  // New stories matching our keywords (early signal — low points, fresh)
  const kw = ['claude', 'gpt', 'openai', 'anthropic', 'llm', 'api pricing', 'ai coding', 'vibecod', 'model']
  for (const k of kw) {
    const res = await fetch(`https://hn.algolia.com/api/v1/search_by_date?query=${encodeURIComponent(k)}&tags=story&hitsPerPage=8`).then((r) => r.json()).catch(() => ({ hits: [] }))
    for (const h of res.hits || []) out.push({ title: h.title, url: h.url || `https://news.ycombinator.com/item?id=${h.objectID}`, source: 'hn-new', points: h.points })
  }
  return out
}

async function fetchRSS(url, source) {
  const xml = await fetch(url).then((r) => r.text()).catch(() => '')
  const items = []
  const re = /<item>[\s\S]*?<title>([\s\S]*?)<\/title>[\s\S]*?<link>([\s\S]*?)<\/link>[\s\S]*?<\/item>/g
  let m
  while ((m = re.exec(xml)) && items.length < 10) {
    items.push({ title: m[1].replace(/<!\[CDATA\[|\]\]>/g, '').trim(), url: m[2].trim(), source })
  }
  return items
}

// ---- Scoring: sum bucket weights for keyword hits in the title. ----
function score(item) {
  const text = item.title.toLowerCase()
  let total = 0
  const hits = []
  for (const b of BUCKETS) {
    if (b.words.some((w) => text.includes(w))) {
      total += b.weight
      hits.push(b.name)
    }
  }
  // Front-page HN items with big point counts get a boost (proven interest).
  if (item.source === 'hn-front' && (item.points || 0) > 200) total += 1
  return { score: total, buckets: hits }
}

// ---- Draft angles: map bucket -> a suggested post angle. ----
const ANGLES = {
  'model-release': 'React to the release: what it means for API users, and the price angle (official vs relay).',
  'api-pricing': 'Price comparison post: official rate vs Vantyr rate for the model in the news.',
  'reseller-swap': 'Authenticity post: how buyers get burned by swapped models, and how daily verification prevents it.',
  'vibecoding': 'Builder post: vibecoding workflow that stays cheap because the API bill doesn\'t scale.',
  'dev-tools': 'Integration post: the one-line base_url change, drop-in compatibility.',
}

function loadSeen() {
  if (!fs.existsSync(SEEN_FILE)) return new Set()
  return new Set(fs.readFileSync(SEEN_FILE, 'utf8').split('\n').filter(Boolean))
}

function main(items) {
  const seen = loadSeen()
  const fresh = []
  for (const item of items) {
    const key = item.url
    if (!key || seen.has(key)) continue
    const { score: s, buckets } = score(item)
    if (s >= RELEVANCE_THRESHOLD) fresh.push({ ...item, score: s, buckets })
    seen.add(key)
  }
  fresh.sort((a, b) => b.score - a.score)

  fs.mkdirSync(STATE_DIR, { recursive: true })
  fs.writeFileSync(SEEN_FILE, [...seen].join('\n'))

  if (fresh.length === 0) {
    console.log('[x-radar] no new relevant topics')
    return
  }

  const lines = fresh.slice(0, 8).map((it) => {
    // Pick the angle from the most specific bucket hit: reseller-swap and
    // api-pricing are the strongest Vantyr stories, vibecoding/dev-tools are
    // builder content, model-release is generic news. Order by priority, not
    // by which matched first.
    const priority = ['reseller-swap', 'api-pricing', 'vibecoding', 'dev-tools', 'model-release']
    const best = priority.find((b) => it.buckets.includes(b))
    const angle = best ? ANGLES[best] : 'Comment with a Vantyr angle.'
    return [
      `# [score ${it.score}] ${it.source}${it.points ? ` ${it.points}pts` : ''} — ${it.title}`,
      `#   ${it.url}`,
      `#   angle: ${angle}`,
      `#   draft a post, then promote to x-queue.txt as:`,
      `#   YYYY-MM-DDTHH:MM | <post text> | ${it.url}`,
      '',
    ].join('\n')
  })
  fs.appendFileSync(DRAFTS_FILE, lines.join('\n'))
  console.log(`[x-radar] ${fresh.length} new topics -> ${DRAFTS_FILE} (top: "${fresh[0].title.slice(0, 60)}")`)
}

const items = [
  ...(await fetchHN()),
  ...(await fetchRSS('https://openai.com/news/rss.xml', 'openai-blog')),
]
main(items)

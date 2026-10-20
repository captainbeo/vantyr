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
 * Vantyr auto-content pipeline (fully hands-off):
 *   scout (HN + AI blogs) -> score for AI/vibecoding relevance -> write the
 *   post with an LLM (via our own Vantyr relay) -> append to x-queue.txt,
 *   which x-poster.mjs ships on its schedule. No human step.
 *
 * Scope (per owner): broad AI + vibecoding — model releases, market updates,
 * news, rumors, Chinese models, agentic coding, dev tools. NOT only
 * Vantyr-adjacent stories; the account posts about the whole space. The brand
 * link goes in the self-reply, so a post about someone else's model still
 * points back to us without the main text reading as an ad.
 *
 * Human work (per owner) lives on X itself: replying to posts and answering
 * questions in the community — never writing the feed.
 *
 * Sources (read-only, verified reachable from the VPS): HN Algolia API,
 * OpenAI news RSS. Reddit is bot-blocked from datacenter IPs; f5bot emails
 * cover Reddit keyword alerts.
 *
 * Env: VANTYR_API_KEY (a relay sk- key) + VANTYR_BASE_URL enable the writer;
 * without them the radar logs a warning and writes nothing. X_STATE_DIR /
 * X_QUEUE_FILE override the default paths. --dry-run prints instead of writing.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const STATE_DIR = process.env.X_STATE_DIR || path.join(here, 'data', 'x-radar')
const SEEN_FILE = path.join(STATE_DIR, 'seen.txt')
const QUEUE_FILE = process.env.X_QUEUE_FILE || path.join(here, 'x-queue.txt')
const DRY_RUN = process.argv.includes('--dry-run')

const VANTYR_API_KEY = process.env.VANTYR_API_KEY
const VANTYR_BASE_URL = (process.env.VANTYR_BASE_URL || 'http://127.0.0.1:3000').replace(/\/$/, '')
// Override the drafting model; otherwise auto-discovered from the relay.
const WRITER_MODEL = process.env.X_WRITER_MODEL || null

// Ask the relay which models exist and pick a cheap one for drafting. The
// model list is public on the gateway, so this works without hardcoding a
// slug that may not be live. Cached per process run.
let cachedModel = null
async function pickModel() {
  if (WRITER_MODEL) return WRITER_MODEL
  if (cachedModel) return cachedModel
  const res = await fetch(`${VANTYR_BASE_URL}/v1/models`, {
    headers: { Authorization: `Bearer ${VANTYR_API_KEY}` },
  })
  const data = await res.json().catch(() => ({}))
  const ids = (data.data || []).map((m) => m.id).filter(Boolean)
  // Prefer a small/cheap model for throwaway drafting; fall back to the first.
  const cheap = ids.find((id) => /mini|haiku|nano|astra|flash|lite/i.test(id))
  cachedModel = cheap || ids[0]
  if (!cachedModel) throw new Error('relay returned no models')
  console.log(`[x-radar] drafting with relay model: ${cachedModel}`)
  return cachedModel
}

// ---- Topic buckets: broad AI + vibecoding. weight = how post-worthy. ----
const BUCKETS = [
  { name: 'model-release', weight: 3, words: ['new model', 'released', 'launch', 'gpt-5', 'gpt-6', 'sonnet', 'opus', 'haiku', ' o1', ' o3', ' o4', 'gemini', 'llama', 'deepseek', 'qwen', 'mistral', 'kimi', 'fable', 'glm', 'ernest', 'hunyuan', 'doubao'] },
  { name: 'chinese-models', weight: 3, words: ['deepseek', 'qwen', 'kimi', 'moonshot', 'zhipu', 'glm', 'hunyuan', 'doubao', 'bytedance', 'alibaba', 'baidu', 'minimax', 'yi-'] },
  { name: 'api-pricing', weight: 3, words: ['api price', 'pricing', 'cost per token', 'per million', 'cheaper', 'expensive', 'rate limit', 'billing', 'usage-based', 'token cost', 'price cut', 'price hike'] },
  { name: 'reseller-swap', weight: 4, words: ['reseller', 'model swap', 'swapped', 'downgrad', 'distill', 'not the real', 'fake model', 'wrong model', 'benchmark gaming'] },
  { name: 'vibecoding', weight: 2, words: ['vibecod', 'vibe cod', 'claude code', 'codex cli', 'cursor', 'copilot', 'windsurf', 'ai agent', 'coding agent', 'agentic', 'codex', 'devin', 'aider', 'cline', 'agent mode'] },
  { name: 'ai-news', weight: 2, words: ['openai', 'anthropic', 'google deepmind', 'meta ai', 'xai', 'grok', 'microsoft', 'nvidia', 'funding', 'acquisition', 'rumor', 'leak', 'reportedly', 'agi', 'safety', 'regulation', 'open source', 'open-weight'] },
  { name: 'dev-tools', weight: 1, words: ['sdk', 'openai-compatible', 'openai compatible', 'api key', 'endpoint', 'base url', 'self-host', 'open source llm', 'mcp'] },
]
const RELEVANCE_THRESHOLD = 3

// ---- Source fetchers: [{title, url, source, points}]. ----
async function fetchHN() {
  const out = []
  const front = await fetch('https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=40').then((r) => r.json())
  for (const h of front.hits || []) out.push({ title: h.title, url: h.url || `https://news.ycombinator.com/item?id=${h.objectID}`, source: 'hn-front', points: h.points })
  const kw = ['claude', 'gpt', 'openai', 'anthropic', 'llm', 'ai coding', 'vibecod', 'deepseek', 'qwen', 'gemini', 'ai agent', 'open source llm']
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
  if (item.source === 'hn-front' && (item.points || 0) > 200) total += 1
  return { score: total, buckets: hits }
}

// ---- The writer: call the Vantyr relay to draft the post. ----
async function writePost(item) {
  const model = await pickModel()
  const system = `You write X (Twitter) posts for Vantyr, an AI API gateway selling genuine Claude/GPT/Codex access at a fraction of official prices, with daily model-authenticity verification. Voice: sharp, builder-to-builder, a little wry, zero hype, zero hashtags, no emojis. You comment on the AI/vibecoding space like a peer who's deep in it — you are NOT writing an ad. Keep it under 260 characters. One clear idea. If a price/relay angle fits naturally, take it; if not, just say the smart thing about the topic. Never fabricate numbers.`
  const user = `Topic (${item.source}${item.points ? `, ${item.points} HN points` : ''}): "${item.title}"
URL: ${item.url}
Matched themes: ${item.buckets.join(', ') || 'general AI'}

Write one X post reacting to this. Output ONLY the post text, no quotes, no preamble.`
  const res = await fetch(`${VANTYR_BASE_URL}/v1/chat/completions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${VANTYR_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user },
      ],
      max_completion_tokens: 120,
    }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(`relay ${res.status}: ${JSON.stringify(data).slice(0, 200)}`)
  const text = (data.choices?.[0]?.message?.content || '').trim().replace(/^["']|["']$/g, '')
  if (text.length < 20) throw new Error('writer returned empty post')
  return text.slice(0, 280)
}

// ---- Main ----
function loadSeen() {
  if (!fs.existsSync(SEEN_FILE)) return new Set()
  return new Set(fs.readFileSync(SEEN_FILE, 'utf8').split('\n').filter(Boolean))
}

async function main() {
  const items = [...(await fetchHN()), ...(await fetchRSS('https://openai.com/news/rss.xml', 'openai-blog'))]
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

  if (!VANTYR_API_KEY) {
    console.warn(`[x-radar] ${fresh.length} topics found but VANTYR_API_KEY unset — set a relay sk- key to enable auto-writing. Top: "${fresh[0].title.slice(0, 60)}"`)
    return
  }

  // Write posts for the top few topics, queue them for the next posting slots.
  const toWrite = fresh.slice(0, 4)
  const lines = []
  for (const it of toWrite) {
    try {
      const text = await writePost(it)
      // Next run of the poster picks this up; timestamp = now (due immediately,
      // the poster paces it). Link goes in the self-reply (cheaper + reach).
      lines.push(`${new Date().toISOString().slice(0, 16)} | ${text} | ${it.url}`)
      console.log(`[x-radar] wrote post for "${it.title.slice(0, 50)}..."`)
    } catch (err) {
      console.error(`[x-radar] writer failed for "${it.title.slice(0, 40)}": ${err.message}`)
    }
  }

  if (lines.length === 0) return
  if (DRY_RUN) {
    console.log('[x-radar] DRY RUN — would append:\n' + lines.join('\n'))
    return
  }
  fs.appendFileSync(QUEUE_FILE, lines.join('\n') + '\n')
  console.log(`[x-radar] queued ${lines.length} posts -> ${QUEUE_FILE}`)
}

main().catch((e) => {
  console.error('[x-radar] fatal:', e.message)
  process.exit(1)
})

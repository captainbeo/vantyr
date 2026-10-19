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
 * X posting bot for @vantyr — reads a git-tracked queue file, posts the next
 * due item, records it in a state file. Runs from cron on the server.
 *
 * Design notes:
 * - Pure Node + fetch + crypto. No npm deps (server has Node but no registry
 *   access budget for a one-off tool). OAuth 1.0a is implemented by hand below.
 * - Cost discipline (docs.x.com pricing): a post with a URL costs $0.20, a
 *   plain-text post $0.015. The queue format therefore keeps links in a
 *   separate field that the bot posts as a SELF-REPLY, not in the main post —
 *   same reach, 13× cheaper, and X's algorithm deprioritizes link posts anyway.
 * - Secrets come from env (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN,
 *   X_ACCESS_SECRET) — never from this file or the queue.
 *
 * Queue format (one item per line, in queue.txt):
 *   2026-10-20T09:00 | Main post text here.
 *   2026-10-20T09:00 | Text. | https://link-to-reply-with
 * Lines starting with # and blank lines are ignored. Posted items move to
 * state/posted.log with their tweet id. Failed posts stay queued and are
 * retried next run.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const QUEUE_FILE = process.env.X_QUEUE_FILE || path.join(here, 'x-queue.txt')
const STATE_DIR = process.env.X_STATE_DIR || path.join(here, 'data', 'x-poster')
const POSTED_LOG = path.join(STATE_DIR, 'posted.log')
const DRY_RUN = process.argv.includes('--dry-run')

const { X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET } = process.env

// ---- OAuth 1.0a signing (the user-context auth X requires for posting) ----
function percentEncode(s) {
  return encodeURIComponent(s).replace(/[!'()*]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase())
}

function oauthHeader(method, url) {
  const params = {
    oauth_consumer_key: X_API_KEY,
    oauth_nonce: crypto.randomBytes(16).toString('hex'),
    oauth_signature_method: 'HMAC-SHA1',
    oauth_timestamp: Math.floor(Date.now() / 1000).toString(),
    oauth_token: X_ACCESS_TOKEN,
    oauth_version: '1.0',
  }
  const base =
    method.toUpperCase() +
    '&' +
    percentEncode(url) +
    '&' +
    percentEncode(
      Object.keys(params)
        .sort()
        .map((k) => `${percentEncode(k)}=${percentEncode(params[k])}`)
        .join('&')
    )
  const signingKey = `${percentEncode(X_API_SECRET)}&${percentEncode(X_ACCESS_SECRET)}`
  params.oauth_signature = crypto.createHmac('sha1', signingKey).update(base).digest('base64')
  return (
    'OAuth ' +
    Object.keys(params)
      .sort()
      .map((k) => `${percentEncode(k)}="${percentEncode(params[k])}"`)
      .join(', ')
  )
}

async function postTweet(text, replyToId) {
  const url = 'https://api.x.com/2/tweets'
  const body = { text }
  if (replyToId) body.reply = { in_reply_to_tweet_id: replyToId }
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: oauthHeader('POST', url),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(`X API ${res.status}: ${JSON.stringify(data).slice(0, 300)}`)
  }
  return data?.data?.id
}

// ---- Queue parsing ----
function parseQueue() {
  if (!fs.existsSync(QUEUE_FILE)) return []
  return fs
    .readFileSync(QUEUE_FILE, 'utf8')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'))
    .map((line) => {
      const parts = line.split('|').map((p) => p.trim())
      const [when, text, link] = parts
      return { when, text, link: link || null, raw: line }
    })
    .filter((item) => item.when && item.text)
}

function alreadyPosted(raw) {
  if (!fs.existsSync(POSTED_LOG)) return false
  const log = fs.readFileSync(POSTED_LOG, 'utf8')
  // Match on the exact queue line so a reposted identical line still counts once.
  return log.includes(raw)
}

function recordPosted(item, tweetId) {
  fs.mkdirSync(STATE_DIR, { recursive: true })
  fs.appendFileSync(
    POSTED_LOG,
    `${new Date().toISOString()} | id=${tweetId} | ${item.raw}\n`
  )
}

// ---- Main ----
async function main() {
  if (!X_API_KEY || !X_API_SECRET || !X_ACCESS_TOKEN || !X_ACCESS_SECRET) {
    console.error('Missing X_* credentials in env. Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET.')
    process.exit(2)
  }

  const now = new Date()
  const queue = parseQueue()
  const due = queue.filter((item) => new Date(item.when) <= now && !alreadyPosted(item.raw))

  if (due.length === 0) {
    console.log(`[x-poster] nothing due (${queue.length} queued, none ready)`)
    return
  }

  // Post only the single next-due item per run — the cron cadence is the
  // pacing, so a backlog drains one post at a time instead of bursting.
  const item = due[0]
  console.log(`[x-poster] posting: ${item.text.slice(0, 70)}${item.link ? ' (+link reply)' : ''}`)

  if (DRY_RUN) {
    console.log('[x-poster] DRY RUN — not posting.')
    return
  }

  try {
    const id = await postTweet(item.text)
    let replyId = null
    if (item.link) {
      // Link goes in a self-reply: cheaper ($0.015 vs $0.20 for a URL in the
      // post) and X doesn't deprioritize replies the way it does link posts.
      replyId = await postTweet(item.link, id)
    }
    recordPosted(item, id)
    console.log(`[x-poster] posted id=${id}${replyId ? ` reply=${replyId}` : ''}`)
  } catch (err) {
    console.error(`[x-poster] failed: ${err.message}`)
    process.exit(1)
  }
}

main()

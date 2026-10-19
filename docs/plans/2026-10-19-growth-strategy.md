# Growth strategy — brand exposure plan (2026-10-19)

Status: strategy document only. Nothing in this file is deployed, published,
or purchased. Every externally-visible or money-spending action is marked
**[owner]** per the non-negotiable gates in `AGENTS.md`.

Platform facts verified against developer docs on 2026-10-19 (links inline);
Google Ads specifics are strategy-level and marked as estimates.

---

## 0. Funnel state — the one constraint that shapes everything

- Site live since 2026-10-04, 12-locale landing, referral program live,
  crypto top-up live, Unlimited Usage page live, Discord + Telegram
  communities live, public GitHub repo exists (`captainbeo/vantyr`).
- **No meaningful volume of paid customers yet.** Every paid channel below
  is therefore gated behind a small pilot with a hard stop rule, and the
  zero-cost channels (SEO foundation, X, TikTok production, forums) come
  first. We validate that a visitor becomes a first ≥$20 top-up organically
  before we buy traffic.
- Conversion path today: Telegram OAuth (trial credit gated on
  @vantyrapi group membership) and email/password as fallback (SMTP
  unconfigured). Discord server + ticket bot exist; Discord OAuth sign-in
  is not enabled. **[owner]** enabling Discord OAuth would add a second
  low-friction signup rail; it is already implemented (needs only the
  Discord app + admin config, see the 2026-10-08 referral plan).

## 1. Positioning — what every channel must say

One line: **"Genuine Claude, GPT and Codex models behind one
OpenAI/Anthropic-compatible API, at a fraction of official prices."**

The five proof points, ranked by how much they differentiate us from the
crowd of cheap API resellers:

1. **Authenticity enforcement.** The cctest monitor verifies every channel
   serves the genuine model (model-authenticity sidecar, live). Cheap
   resellers are notorious for silently swapping/downgrading models — we
   are the only relay that publicly polices this. This is the brand story
   no competitor can copy quickly.
2. **Price.** Up to ~98% below official API rates (live public price
   comparison on the Model Overview page; pricing rule: 2× A6 cheap tier,
   margin ≥2×).
3. **Unlimited plan** ($180/mo flat) — the "stop watching your meter"
   angle for heavy users.
4. **12 languages** — genuinely rare in this market; maps directly onto
   low-competition international SEO.
5. **Transparency** — AGPL compliance, public repo, real docs.

Ad/claim discipline: always "up to X%" with the comparison page as
substantiation; never a bare "98% off". Google Ads rejects unverifiable
discount claims, and X/TikTok audiences punish inflated claims.

---

## 2. SEO — the compounding asset

### 2.1 Current state (verified 2026-10-19)

- Pure client-rendered SPA (Rsbuild + React 19). Google sees one English
  shell: `<title>Vantyr</title>`, a meta description, favicon. **No og:
  tags, no twitter: tags, no JSON-LD, no canonical, no hreflang.**
- **No robots.txt, no sitemap.xml** anywhere that ships.
- Language selection is localStorage-based — the 12 translated landings
  are invisible to search engines. Not one localized URL is indexable.
- Analytics placeholders (umami, GA) in `web/index.html` are empty.
- Public routes: `/`, `/about`, `/pricing`, `/pricing/$modelId`,
  `/rankings`, `/setup`, `/privacy-policy`, `/unlimited`. The `/docs` site
  is separate and served via Caddy.
- Runtime branding overwrote `document.title` to the bare system name
  once JS ran (`main.tsx` `initSystemBranding`), clobbering any static
  title for crawlers that render JS.

Net at survey time: organic search ~zero. **Phase A below is now
implemented** (2026-10-19); the locale-URL work (Phase B) remains the
big unlock.

### 2.2 Phase A — config-level SEO (implemented 2026-10-19)

Implemented and verified (unit tests, lint, production build, live
preview evidence; deploy pending as usual):

- `web/index.html`: descriptive title ("Vantyr — Claude, GPT & Codex API
  at a fraction of official prices"), refined description, canonical,
  full Open Graph + Twitter `summary_large_image` set pointing at
  `/og-image.png`, and WebSite JSON-LD (with a `SearchAction` on
  `/pricing`).
- `web/public/og-image.png`: 1200×630 brand card (void + glass panel +
  3D mark + orange CTA pill), rendered as a Remotion still from the
  video repo's brand kit (`vantyr-video` `OgImageCard` still; re-render
  via `npx remotion still OgImageCard <out>` and copy into
  `web/public/`).
- `web/public/robots.txt` (allow all; Disallow /api/ + auth-gated app
  routes; sitemap pointer) and `web/public/sitemap.xml` (6 public URLs;
  `/unlimited` excluded — auth-guarded).
- Title policy fix: new `applyDocumentTitleToDom`/`buildDocumentTitle`
  in `web/src/lib/dom-utils.ts` — marketing routes keep the static SEO
  title; app routes get `"<system_name> — Console"`. 8 unit tests in
  `web/src/lib/__tests__/dom-utils.test.ts` (passing). Verified live:
  `/` keeps the full SEO title after the status fetch; an app route
  shows "Vantyr AI Gateway — Console".
- Static-file serving validated through the SPA fallback behavior:
  real files in `web/public` land in `dist` and serve as themselves
  (verified `/robots.txt` 200 text/plain, `/sitemap.xml` 200 text/xml
  with 6 URLs, `/og-image.png` 200 image/png 340 KB). The live
  production site will pick these up on the next image build + redeploy.
- **[owner]** after deploy: Search Console + Bing Webmaster verification
  (DNS TXT — owner-gated per `AGENTS.md`), submit sitemap.xml, and pick
  umami vs GA4 for the empty placeholder slots in `index.html`.
- **Never set `HomePageContent`** to deploy any of this (standing owner
  rule from the 2026-10-11 guide-map incident).

Namecheap perk note (2026-10-19): Namecheap's domain-purchase perks
have typically included a free month of their "SEO Studio" all-in-one
tool (rank tracking / site audit / keyword suggestions). Their site
blocks automated verification, so treat this as: claim it in the
Namecheap panel if present. It does **not** replace the technical work
here (meta tags, sitemap, prerendering are what make the site
indexable) and Search Console remains the authoritative source either
way; a free month of rank tracking is still nice to have once pages are
indexed.

### 2.3 Phase B — locale URLs + prerendering (DEPLOYED LIVE 2026-10-20, pinned-next44)

Approach shipped: prerendered marketing shells served per-locale, SPA
untouched. Verified end-to-end in the browser (French LTR + Arabic RTL
both render translated hero/title).

- **`web/scripts/prerender/`**: `entry.tsx` server-renders the landing
  (`@/features/home` `Home`) per locale with i18next; `run.mjs` bundles
  it with Bun (stubbing image/CSS/three imports), renders all 11
  non-English locales, and writes `dist/<locale>/index.html` with
  per-locale `<html lang>`/`dir`, title (hero headline, translated),
  description (translated tagline), canonical, og/twitter, and the full
  13-entry hreflang cluster. `dist-server.mjs` is a local static server
  for previewing dist.
- **SSR fix that made it work:** `useHomePageContent` initialized
  `isLoaded: false` and only set it in a `useEffect`, which never runs
  in `renderToString` — so the prerender only produced the "Loading…"
  branch. It now initializes `isLoaded = typeof window === 'undefined'`
  (browser path unchanged; jsdom tests still pass 22/22).
- **Serving:** the shells land inside the embedded `web/dist`, so the
  gateway's existing `static.Serve` (gin + `http.FileServer`) serves
  `/fr/` → `dist/fr/index.html` automatically; no Caddy or Go change.
  Unknown paths still fall through to the SPA. Interactive routes
  (`/sign-up`, `/pricing`, dashboard) remain SPA.
- **Build wiring:** `bun run prerender` after `bun run build` (rsbuild
  wipes `dist/` on each build, so prerender must run after);
  `build:prerender` combines both; the Dockerfile now runs
  `build && prerender` so deployed images include the shells.
- **Sitemap:** homepage entry carries `xhtml:link rel="alternate"` for
  all 12 locales + x-default, with `xmlns:xhtml` declared.
- The en landing stays the default at `/` and is the x-default.
- Verification: 11/11 shells written; titles translated and concise;
  hreflang ×13 per shell; fr/ar serve 200 with translated hero;
  `oxlint` clean on new files; home tests 22/22; production build OK.
- **Deployed live 2026-10-20 (pinned-next44, tag
  deploy/2026-10-19-seo-phase-b).** Deploy note: the gateway's
  `static.Serve` does NOT serve /<locale>/ as a directory index (it
  301-loops); the shells are shipped to `static/locale/<locale>/` and
  served by a Caddy `@locales` handle instead. All 11 locale URLs,
  the bare-locale 308 redirects, the unchanged apex, and the intact SPA
  fallback verified live. Google can now index each locale separately.

### 2.4 Phase C — content surface (weeks, compounding)

- **Programmatic pages**: Model Overview + Rankings already exist and are
  data-driven. Make them indexable (Phase B shells) and add JSON-LD
  (Organization + WebSite on home; Product/Offer per model on
  `/pricing/<modelId>` — the official-price comparison data makes these
  legit rich-result candidates).
- **Comparison pages** (new static routes, ~one page per target):
  "Vantyr vs OpenRouter", "Vantyr vs official Anthropic API", "Vantyr vs
  official OpenAI API". Honest tables — win on price/authenticity,
  lose gracefully on breadth/SLAs. These capture the highest-intent
  query family in this niche.
- **Cost-calculator page**: interactive "your official bill → your Vantyr
  bill" per model. Linkable from every channel; natural backlink magnet.
- **Articles** (also posted to dev.to / Indie Hackers for the forums
  channel, §6): "Claude API pricing explained (2026)", "How to verify
  your API reseller isn't swapping models", "OpenAI-compatible API keys:
  what actually changes when you switch base_url".
- Docs site: per-page titles/descriptions + sitemap. Docs are the
  highest-authority surface we have (real technical content).

### 2.5 Keyword map (seed, en first, then translated)

| Intent | Query family | Page |
| --- | --- | --- |
| Alternative | openrouter alternative · claude api alternative · cheap anthropic api | /, /vs/openrouter |
| Price | claude api pricing · gpt-4 api cost · anthropic api pricing comparison | /pricing, calculator |
| Cheap | cheap claude api · cheapest claude api · api reseller cheap | /, articles |
| Trust | api reseller model swap · is openrouter safe · verify model authenticity | authenticity article |
| How-to | claude api key · openai compatible endpoint · switch base_url | /setup, docs |

The same families in fr/ru/zh/zh-TW/vi/ja/de/nl/tr/es/ar at the Phase B
locale URLs. Expect 2–6 months to meaningful organic volume; forums and
TikTok (§4–6) are the bridge until then.

---

## 3. Google Ads — small, conversion-gated pilot

Hard sequencing rule: **no spend before conversion tracking works.** We
are buying evidence, not traffic.

1. **Setup first**: GA4 events `sign_up`, `topup_success` (with value) via
  gtag; import as conversions into Google Ads. The top-up event must be
  server-emitted or fired from the success page, not the client button.
2. **Campaign shape**: Search only, exact match only, tight negatives
  (free, jobs, course, tutorial, career, download). Seed keywords:
  "cheap claude api", "openrouter alternative", "claude api reseller",
  "anthropic api cheaper", "gpt api for cheap". Bidding: manual/max
  clicks until ≥15 conversions accumulate, then target CPA.
3. **Geo**: start with high-intent English markets + the price-sensitive
  markets that match our locales (TR, VN, ES/LatAm, RU, MENA-ar). CPCs
  there are a fraction of US/UK — this is where the 12-language work pays
  twice.
4. **Budget & stop rule** **[owner]**: $5/day cap, ~$150–200 for the
  pilot. Stop and diagnose if: no signups after ~$100, or no attributable
  first top-up after $200. No scale-up until one organic-quality
  customer has come through paid and their top-up ≥ the pilot CAC.
5. **Ad copy constraints**: bid on trademark keywords is allowed; do not
  put "Claude/Anthropic/OpenAI" in ad *text* (trademark complaint risk).
  "Anthropic-compatible" is factual and fine. "Up to X% less" only, with
  the comparison page as the landing substantiation.

---

## 4. TikTok — automate production now; automate posting after the API audit

TikTok automation truth (verified 2026-10-19,
[developers.tiktok.com](https://developers.tiktok.com/doc/content-posting-api-get-started)):
the Content Posting API needs a developer app with the `video.publish`
scope and **an audit — posts from unaudited apps are locked to
private-only visibility**. Audit timelines are not documented. So:

### Phase 1 — automated production, manual posting (start immediately)

We already own the machine: the Remotion repo
(`D:\worktrees\vantyr-video`) has the brand kit, the 45s explainer, and
the 12-locale per-language render pipeline. Reuse it:

- **Three reusable vertical templates** (1080×1920, 15–30s):
  1. **Price shock** — animated "Official API: $X → Vantyr: $Y" per
     model, data fed from the same pricing JSON the site uses.
  2. **Build demo** — screen recording + burned-in captions ("I built
     this agent for $0.42 with the Claude API").
  3. **Authenticity explainer** — "3 signs your cheap API reseller is
     swapping models" — nobody else can make this content credibly.
- **A weekly auto-generated series**: "API price check this week" —
  rendered from live pricing data by a script in the video repo. Batch
  10–15 videos per render session into a dated folder for manual pickup.
- **[owner]** posts 3–5/week from the @vantyr account: hook in the first
  1.5s, burned captions (most views are muted), keyword-heavy caption
  ("cheap claude api", "openrouter alternative" — TikTok search is now a
  real discovery engine), link in bio (switch to a Business account for
  the website field → `https://vantyr.xyz?utm_source=tiktok`).

### Phase 2 — automated posting (apply in parallel, don't block on it)

- **[owner]** create the TikTok developer app, add Content Posting API +
  Direct Post, request `video.publish`, run one private test post, then
  submit for audit. If/when approved: a VPS cron job renders and posts
  the weekly series end-to-end (media must be pulled from a verified
  domain — we serve the render output from vantyr.xyz, which we control).
- If the audit drags or fails: Phase 1 manual posting is the permanent
  fallback and is honestly fine at 3–5 posts/week.

---

## 5. X — fully automatable today, and nearly free

X API pricing changed to **pay-per-usage with no subscriptions**
(verified 2026-10-19, [docs.x.com](https://docs.x.com/x-api/getting-started/pricing)):

- Post create: **$0.015** per post — **$0.200 if the post contains a
  URL**. Reads: $0.005/post (owned reads $0.001). Self-serve read cap:
  3M reads/month. New accounts get **$20 free credits** after saving a
  payment method and making a first credit purchase.
- Cost math: 2 posts/day + 1 link-in-reply/day ≈ **$13/month** — the
  first month+ is covered by the signup credit. Note the $0.20 with-URL
  charge lines up with what everyone already does for reach reasons:
  put the link in the reply, not the post.

### The build (implemented 2026-10-20, awaiting owner account)

- **Poster**: `deploy/vantyr/x-poster.mjs` — pure-Node (no deps), X API
  v2. Reads the git-tracked `deploy/vantyr/x-queue.txt`, posts the oldest
  due unposted item per cron run, logs to `data/x-poster/posted.log`.
  OAuth 1.0a implemented by hand. Links go in a self-reply (never the
  main post — $0.015 vs $0.20, and better reach). Credentials come from
  `X_*` env vars only (never in files); `--dry-run` for testing. Tested:
  queue parse, due detection, dry-run, missing-creds exit.
- **Queue**: `x-queue.txt` seeds 8 posts (price, authenticity, one-URL
  setup, unlimited tier, transparency, docs).
- **Remaining owner steps** (the account, below) + server-side: drop the
  4 credentials into a root-only `.env` on the VPS, add a twice-daily cron
  entry. Not done until the owner creates the account and hands over the
  keys.
- **Content engine** (later): reactive "new model live" post triggered by
  a daily diff of the public pricing; weekly thread.
- **Engagement stays human**: 15 min/day **[owner]** replying to
  indie-hacker / AI-builder threads; automated reads not worth it at V1.
- X automation rules: official API only, no automated follows/DMs.

---

## 6. Forums — highest intent, human-led, discovery automated

Where our buyers actually are, ranked:

1. **Reddit** — r/LocalLLaMA (huge, price-obsessed, discusses API
   relays constantly), r/ChatGPTCoding, r/SideProject (build posts
   explicitly allowed), r/AI_Agents, r/automation, plus the subreddits
   matching our locales. Rules: read each sub's self-promo policy;
   answer "cheap API?" threads honestly with disclosure; become a known
   account before ever promoting. One intro post per community, then
   pure helpfulness.
2. **Hacker News** — a **Show HN** once SEO Phase A/B is live and the
   landing converts: "Show HN: Vantyr – API relay with automated
   model-authenticity verification". The public repo + AGPL compliance +
   the authenticity monitor is a genuinely HN-shaped story. Do not burn
   this before the landing can absorb a spike.
3. **Linux.do** — the codebase already ships LinuxDO OAuth support; this
   community is precisely the "cheap Claude/GPT access" discourse in
   Chinese. A detailed, honest intro post (they have strong
   anti-hype norms) maps to our zhCN/zhTW locales.
4. **Automation-builder communities** (n8n, Make forums) — heavy
   OpenAI-compatible-API consumers constantly asking for cheaper
   endpoints.
5. **Longer tail**: LowEndTalk (VPS crowd, price-sensitive),
   dev.to / Indie Hackers (republish the SEO articles), V2EX.

### The automation that is allowed and worth building

- A **demand radar**: [f5bot.com](https://f5bot.com) (free) +
  Google Alerts on "openrouter alternative", "cheap claude api",
  "claude api reseller", "anthropic api too expensive" across Reddit +
  HN → daily digest to Discord (#growth channel via the existing
  ticket-bot webhook pattern). Automates discovery; a human hand always
  writes the reply.
- Hard rules: single account per platform, always disclose affiliation,
  no vote manipulation. The brand is an AGPL project with a public repo
  — astroturfing risk isn't worth one banned account.

---

## 7. Cross-channel mechanics

- **UTM discipline everywhere**: `?utm_source=x|tiktok|reddit|google`
  (+ campaign). The bio links, forum links, and ad final URLs all carry
  them; umami/GA4 then shows which channel actually produces signups and
  top-ups, weekly.
- **Referral tie-in**: the live referral program ($7 to the inviter at
  the referred user's first ≥$20 top-up) turns every satisfied early
  user into a channel — mention it in Discord/Telegram, not in ads.
- **Communities as the retort**: Discord/Telegram are where TikTok/X
  visitors get converted and retained; keep the #pricing auto-sync and
  FAQ categories healthy and link them from every profile bio.
- **Every asset multiplies**: one pricing fact = an X post + a TikTok
  price-shock render + a forum answer + (monthly) an SEO page update.
  The queue file, video templates, and article backlog should be
  produced in batches from the same source data.

## 8. Sequencing (2-week sprints) and 90-day targets

- **Sprint 1 (start now, zero spend)**: SEO Phase A (meta/og/sitemap/
  robots + analytics on) · X poster MVP + first 20 queue items + X
  developer account **[owner]** · demand radar live · first 3 TikTok
  videos rendered · Reddit/Linux.do account seeding begins **[owner]**.
- **Sprint 2**: SEO Phase B (prerendered locale shells + hreflang) ·
  first comparison page + calculator · 6 more TikToks · X reactive
  price-post automation · GA4 conversion events in place (no ad spend
  yet) · TikTok developer app submitted for audit **[owner]**.
- **Sprint 3**: Google Ads pilot ($5/day cap, stop rules armed)
  **[owner]** · second comparison page · first article cross-posted ·
  HN launch prep (wait for a converting week before Show HN).
- **Sprint 4**: review against KPIs, double down on the one channel
  producing top-ups, kill the rest.

Honest 90-day targets: organic clicks 1–2k/month, X ≥1k followers,
TikTok median ≥5k views/video, ≥50 signups total, ≥5 first ≥$20
top-ups, and — the number that matters — **at least one channel with a
measurable, repeatable signup→top-up path**.

## 9. Owner decision list (blocking items)

| # | Decision | Cost | Blocks |
| --- | --- | --- | --- |
| 1 | X developer account + first API credit purchase (unlocks $20 credit) | ~$25 | X automation |
| 2 | Google Ads account + $150–200 pilot budget | $150–200 | Paid search |
| 3 | TikTok developer app + audit submission | free | Automated posting (Phase 2 only) |
| 4 | Search Console/Bing DNS verification | free | Sitemap submission |
| 5 | Analytics choice (umami self-hosted vs GA4) | free | SEO iteration + Ads conversions |
| 6 | Discord OAuth enablement (app + admin config) | free | Second signup rail |
| 7 | Owner time: ~15–30 min/day for forums + posting TikToks | time | Forums + TikTok Phase 1 |

## Sources

- X API pay-per-usage pricing: https://docs.x.com/x-api/getting-started/pricing
- X API getting started: https://docs.x.com/x-api/getting-started/about-x-api
- TikTok Content Posting API (scope + audit/private-mode gates):
  https://developers.tiktok.com/doc/content-posting-api-get-started
- Repo state (locales, SEO, referral, communities) verified by code
  survey on 2026-10-19; live config facts per `VANTYR.md` and memory.

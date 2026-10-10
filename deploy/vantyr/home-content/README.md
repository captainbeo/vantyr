# Home page content (translatable guide)

`HomePageContent` is the admin-editable markdown rendered on the homepage
("Get started" guide + landing copy). The frontend now supports two formats
for that option:

1. **Plain string** (Markdown / HTML / iframe URL) — shown to every visitor,
   exactly as before.
2. **JSON language map** — one entry per interface language code; the
   frontend picks the variant matching the visitor's active UI language and
   falls back to English (or the only variant present):

   {"en": "# Vantyr API …", "de": "# Vantyr API …", "ar": "# Vantyr API …"}

## Applying the multilingual guide

`guide-map.json` here is the ready-made language map (en, de, nl, tr, es, ar,
fr, ru, ja, vi, zhCN, zhTW) translated from `guide-en.md`. The per-language
`guide-<lang>.md` files are kept alongside for review/editing.

To set it on an environment, write the JSON to the option (psql file-pipe
avoids shell quoting problems):

    docker cp guide-map.json <postgres>:/tmp/guide-map.json
    docker exec <postgres> psql -U vantyr -d vantyr \
      -c "UPDATE options SET value = pg_read_file('/tmp/guide-map.json') WHERE key='HomePageContent';"

Then restart the gateway container (options are cached in memory at startup;
direct DB writes are only picked up after a restart or an admin-UI save).

Edit via the admin UI (System Settings → System Information → Home Page
Content) as usual — the textarea accepts the JSON map too.

When the guide content changes, edit `guide-en.md`, translate the change into
the other files (keep code fences, URLs, link paths, model names, and env var
names byte-identical — only prose is translated), rebuild the JSON, and
re-apply. The placeholders' host is `vantyr.example.com`; update to the live
domain when applying to production.

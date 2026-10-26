# Vantyr Design Guide — "Control Room"

Give this file to any AI or developer building Vantyr screens. Follow it exactly so new pages match the homepage and console.

## Feel
Dark operations console for a relay station: precise, technical, calm. It should look like real infrastructure software, not an AI template.
Never use: purple/indigo gradients, glows, glassmorphism, rounded "bubbly" cards, emoji, stock illustrations, generic hero blobs, Inter/Poppins.

## Colors (use tokens only — defined in `src/styles.css`)
| Token | Use |
|---|---|
| `bg-background` | page (deep navy-charcoal) |
| `bg-card` | panels, tables, inputs on panels |
| `border` (default border color) | every 1px line |
| `text-foreground` / `text-muted-foreground` | primary / secondary text |
| `text-signal`, `bg-primary` | electric orange — the ONLY accent: CTAs, active nav, model names, key IDs |
| `text-ok` / `bg-ok` | healthy status, 200s, "online" dots |
| `text-destructive` | errors, revoke/delete |
| `bg-gridlines` (utility) | 48px faint grid behind page sections |

Rule: one accent color. Orange for action/selection, green only for health. Never hardcode hex or `text-white`.

## Type
- Headings: `font-display` (Chakra Petch), semibold, tight leading.
- Body: IBM Plex Sans (default).
- Labels, numbers, tables, buttons: `font-mono` (JetBrains Mono).
- Section labels: `label-mono` utility (11px, uppercase, wide tracking, muted) with a code prefix: `<span class="text-signal">CON-01</span> / Title`.

## Shape & layout
- Radius small: `rounded-sm` everywhere. No pills except tiny status dots.
- Flat. No shadows. Separation comes from 1px borders.
- Grids of tiles use the "hairline" trick: `grid gap-px bg-border border rounded-sm overflow-hidden` with `bg-background` children.
- Max width `max-w-7xl` (site) / `max-w-6xl` (console), `px-5`.

## Components (reuse `src/components/console/ui.tsx`)
- `PageTitle` — code label + display H1 + optional description + actions.
- `Panel` — bordered card with a mono header bar (`code / title`, optional right slot).
- `StatGrid` — 2/4-column hairline stat tiles: mono label, big display number, small orange unit.
- `DataTable` — mono 12px table, label-mono headers, row hover `bg-accent/40`.
- `Badge` — tiny bordered uppercase status chip (`ok`, `warn`, `bad`, `muted`, `signal`).
- `Tabs`, `Field`, `Bars` (simple bar chart), `btn.primary | ghost | link | danger`, `inputCls`.
- Buttons: mono, uppercase, wide tracking, `rounded-sm`. Primary = orange fill, dark text.
- Live indicators: `animate-blink` dot + mono caption (e.g. "● LIVE", "ALL RELAYS NOMINAL").

## Console structure (mirrors New API)
Sidebar groups: **Chat** (Playground) · **Console** (Dashboard, API Keys, Usage Logs) · **Personal** (Wallet, Profile) · **Admin** (Channels, Models, Users, Redemption, System).
Active item: `bg-accent`, orange icon, 2px orange bar on the left. Top bar: balance in orange, email, sign out.

## Copy voice
Short, technical, confident. "Relay", "channel", "key", "quota". No hype words ("revolutionary", "unleash", "seamless").

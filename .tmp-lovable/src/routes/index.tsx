import { createFileRoute, Link } from "@tanstack/react-router";
import mark from "@/assets/vantyr-mark.png";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Vantyr — Real Claude & Codex, 98%+ off, no limits" },
      { name: "description", content: "Genuine Claude and Codex models at 98%+ below official API rates with no usage limits, or unlimited usage for $180/month. Never fake models." },
      { property: "og:title", content: "Vantyr — Real Claude & Codex, 98%+ off, no limits" },
      { property: "og:description", content: "Genuine models only. 98%+ off official rates, no limits, or $180/month unlimited." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Home,
});

const stats = [
  { k: "Median added latency", v: "38", u: "ms" },
  { k: "Relay uptime · 90d", v: "99.97", u: "%" },
  { k: "Off official rates", v: "98", u: "%+" },
  { k: "Usage limits", v: "0", u: "caps" },
];

const problems = [
  { n: "01", tag: "Limits", problem: "Daily, weekly and monthly caps", fix: "No usage limits. Ever.", d: "No daily, weekly or monthly ceilings. Code all night without hitting a wall mid-task." },
  { n: "02", tag: "Models", problem: "Locked to one vendor", fix: "Every major model, one key.", d: "Claude and Codex behind one key. Switch models per project, or per request, by changing a single name." },
  { n: "03", tag: "Price", problem: "Official API bills that scale with every token", fix: "At least 98% cheaper.", d: "A minimum of 98% below official Anthropic and OpenAI rates, or one flat $180/month for unlimited use." },
  { n: "04", tag: "Integrity", problem: "Relays that quietly swap in cheaper models", fix: "Real models. Tested daily.", d: "No model swapping, distilling or downgrading. We test every model daily to confirm you get what you asked for." },
  { n: "05", tag: "Support", problem: "Setup docs nobody answers questions about", fix: "Easy setup, real support.", d: "A step-by-step setup guide for Claude Code, Codex and SDKs, and a support team that answers any question." },
  { n: "06", tag: "Drop-in", problem: "Rewriting code to change providers", fix: "Change one URL.", d: "Same request and response format as the official APIs. Your tools keep working, you just pay less." },
];

const compare = [
  ["Usage limits", "Daily / weekly caps", "Often throttled", "None"],
  ["Price vs official", "100%", "Varies", "98%+ less"],
  ["Models", "One vendor", "Mixed", "Claude + Codex, one key"],
  ["Genuine models", "Yes", "Often swapped", "Yes, tested daily"],
  ["Setup", "Per vendor", "Unclear", "One URL change + guide"],
  ["Support", "Ticket queue", "Rare", "Answers any question"],
];

const steps = [
  { n: "01", t: "Issue a key", d: "Subscribe and get a single vt_ key. No provider accounts to juggle." },
  { n: "02", t: "Swap the base URL", d: "Point your SDK at api.vantyr.dev. Request and response shapes stay identical." },
  { n: "03", t: "Ship", d: "Traffic is relayed to the upstream model over pooled capacity at a lower rate." },
];

const log = [
  ["01:51:04.112", "POST", "/v1/messages", "claude-sonnet", "200", "412ms"],
  ["01:51:04.380", "POST", "/v1/responses", "codex", "200", "655ms"],
  ["01:51:04.902", "POST", "/v1/messages", "claude-opus", "200", "1.12s"],
  ["01:51:05.017", "POST", "/v1/chat/completions", "codex-mini", "200", "201ms"],
  ["01:51:05.344", "POST", "/v1/messages", "claude-haiku", "200", "133ms"],
];

function Home() {
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden border-b">
        <div className="mx-auto grid max-w-7xl gap-12 px-5 py-16 md:py-24 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <p className="label-mono">
              <span className="text-signal">SYS-00</span> / Genuine models · relay pricing
            </p>
            <h1 className="mt-5 font-display text-5xl font-semibold leading-[0.98] md:text-7xl">
              The real models.
              <br />
              <span className="text-signal">98% off the bill.</span>
            </h1>
            <p className="mt-6 max-w-lg text-lg text-muted-foreground">
              Every request reaches genuine Claude and Codex. No swapped, distilled or downgraded models, ever. You pay a
              fraction of official API rates, or go unlimited for one flat monthly price.
            </p>
            <div className="mt-8 grid max-w-lg grid-cols-2 gap-px overflow-hidden rounded-sm border bg-border">
              <div className="bg-background p-4">
                <div className="label-mono">vs official API rates</div>
                <div className="mt-1 font-display text-3xl font-semibold">
                  up to <span className="text-signal">98%</span> less
                </div>
              </div>
              <div className="bg-background p-4">
                <div className="label-mono">Unlimited usage</div>
                <div className="mt-1 font-display text-3xl font-semibold">
                  $180<span className="ml-1 font-mono text-sm font-normal text-muted-foreground">/mo</span>
                </div>
              </div>
            </div>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link to="/pricing" className="rounded-sm bg-primary px-5 py-3 font-mono text-sm font-medium uppercase tracking-wider text-primary-foreground hover:brightness-110">
                Go unlimited
              </Link>
              <Link to="/docs" className="rounded-sm border px-5 py-3 font-mono text-sm uppercase tracking-wider hover:bg-accent">
                Read the docs →
              </Link>
              <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full bg-ok" /> Real models only
              </span>
            </div>
            <pre className="mt-10 max-w-lg overflow-x-auto rounded-sm border bg-card p-4 font-mono text-[13px] leading-relaxed">
              <span className="text-muted-foreground"># before</span>
              {"\n"}base_url = <span className="line-through opacity-50">"https://api.anthropic.com"</span>
              {"\n"}
              <span className="text-muted-foreground"># after</span>
              {"\n"}base_url = <span className="text-signal">"https://api.vantyr.dev"</span>
            </pre>
          </div>

          {/* Relay diagram */}
          <div className="relative rounded-sm border bg-card/60">
            <div className="flex items-center justify-between border-b px-4 py-2.5">
              <span className="label-mono">Relay map · live</span>
              <span className="flex items-center gap-2 font-mono text-[11px] text-ok">
                <span className="h-1.5 w-1.5 rounded-full bg-ok animate-blink" /> 3/3 ONLINE
              </span>
            </div>
            <div className="relative aspect-[4/3]">
              <svg viewBox="0 0 400 300" className="absolute inset-0 h-full w-full" aria-hidden>
                {([
                  [60, 70], [60, 150], [60, 230],
                ] as const).map(([x, y], i) => (
                  <g key={i}>
                    <path d={`M${x + 40} ${y} C 160 ${y}, 160 150, 200 150`} fill="none" stroke="var(--border)" strokeWidth="1.5" />
                    <path d={`M${x + 40} ${y} C 160 ${y}, 160 150, 200 150`} fill="none" stroke="var(--signal)" strokeWidth="1.5" className="animate-flow" />
                    <rect x={x - 40} y={y - 14} width="80" height="28" rx="2" fill="var(--secondary)" stroke="var(--border)" />
                    <text x={x} y={y + 4} textAnchor="middle" fontFamily="JetBrains Mono" fontSize="10" fill="var(--muted-foreground)">
                      {["CLIENT-A", "CLIENT-B", "CI RUNNER"][i]}
                    </text>
                  </g>
                ))}
                {[
                  [340, 100, "CODEX"], [340, 200, "CLAUDE"],
                ].map(([x, y, l]) => (
                  <g key={l as string}>
                    <path d={`M240 150 C 290 150, 280 ${y}, ${(x as number) - 40} ${y}`} fill="none" stroke="var(--ok)" strokeWidth="1.5" className="animate-flow" />
                    <rect x={(x as number) - 40} y={(y as number) - 14} width="80" height="28" rx="2" fill="var(--secondary)" stroke="var(--border)" />
                    <text x={x as number} y={(y as number) + 4} textAnchor="middle" fontFamily="JetBrains Mono" fontSize="10" fill="var(--foreground)">{l}</text>
                  </g>
                ))}
                <circle cx="220" cy="150" r="34" fill="var(--background)" stroke="var(--signal)" strokeWidth="1.5" />
                <circle cx="220" cy="150" r="44" fill="none" stroke="var(--signal)" strokeOpacity="0.25" strokeDasharray="2 4" />
              </svg>
              <img src={mark} alt="Vantyr relay" className="absolute left-[55%] top-1/2 h-12 w-12 -translate-x-1/2 -translate-y-1/2" />
            </div>
            <div className="grid grid-cols-3 border-t font-mono text-[11px]">
              {[["EU-W", "31ms"], ["US-E", "42ms"], ["AP-SE", "57ms"]].map(([r, l]) => (
                <div key={r} className="border-r px-4 py-2.5 last:border-r-0">
                  <div className="text-muted-foreground">{r}</div>
                  <div className="mt-0.5 text-foreground">{l}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="border-b">
        <div className="mx-auto grid max-w-7xl grid-cols-2 md:grid-cols-4">
          {stats.map((s) => (
            <div key={s.k} className="border-r px-5 py-8 last:border-r-0 [&:nth-child(2)]:max-md:border-r-0">
              <div className="label-mono">{s.k}</div>
              <div className="mt-2 font-display text-4xl font-semibold">
                {s.v}
                <span className="ml-1 text-lg text-signal">{s.u}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Why Vantyr: problems solved */}
      <section className="border-b">
        <div className="mx-auto max-w-7xl px-5 py-20">
          <p className="label-mono"><span className="text-signal">WHY-00</span> / What Vantyr fixes</p>
          <h2 className="mt-3 max-w-3xl font-display text-3xl font-semibold md:text-5xl">
            Official APIs throttle you, bill you heavily and lock you to one vendor. <span className="text-signal">Vantyr removes all three.</span>
          </h2>
          <div className="mt-12 grid gap-px overflow-hidden rounded-sm border bg-border md:grid-cols-2 lg:grid-cols-3">
            {problems.map((p) => (
              <div key={p.n} className="bg-background p-6">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm text-signal">{p.n}</span>
                  <span className="label-mono">{p.tag}</span>
                </div>
                <p className="mt-6 font-mono text-xs text-muted-foreground line-through decoration-destructive/60">{p.problem}</p>
                <h3 className="mt-2 font-display text-xl font-semibold">{p.fix}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{p.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Comparison */}
      <section className="border-b">
        <div className="mx-auto max-w-7xl px-5 py-20">
          <p className="label-mono"><span className="text-signal">WHY-01</span> / Side by side</p>
          <h2 className="mt-3 font-display text-3xl font-semibold md:text-4xl">Why choose Vantyr.</h2>
          <div className="mt-10 overflow-x-auto rounded-sm border bg-card">
            <table className="w-full min-w-[640px] font-mono text-[13px]">
              <thead>
                <tr className="border-b">
                  <th className="px-4 py-3 text-left font-normal label-mono"> </th>
                  <th className="px-4 py-3 text-left font-normal label-mono">Official APIs</th>
                  <th className="px-4 py-3 text-left font-normal label-mono">Other relays</th>
                  <th className="px-4 py-3 text-left font-normal label-mono text-signal">Vantyr</th>
                </tr>
              </thead>
              <tbody>
                {compare.map((r) => (
                  <tr key={r[0]} className="border-b last:border-b-0">
                    <td className="px-4 py-3 text-muted-foreground">{r[0]}</td>
                    <td className="px-4 py-3">{r[1]}</td>
                    <td className="px-4 py-3">{r[2]}</td>
                    <td className="px-4 py-3 text-signal">{r[3]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Steps */}
      <section className="border-b">
        <div className="mx-auto max-w-7xl px-5 py-20">
          <p className="label-mono"><span className="text-signal">SYS-01</span> / Integration</p>
          <h2 className="mt-3 font-display text-3xl font-semibold md:text-4xl">Three steps. No rewrite.</h2>
          <div className="mt-10 grid gap-px overflow-hidden rounded-sm border bg-border md:grid-cols-3">
            {steps.map((s) => (
              <div key={s.n} className="bg-background p-6">
                <div className="font-mono text-sm text-signal">{s.n}</div>
                <h3 className="mt-6 font-display text-xl font-semibold">{s.t}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Traffic log */}
      <section className="border-b">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-20 lg:grid-cols-[1fr_1.6fr]">
          <div>
            <p className="label-mono"><span className="text-signal">SYS-02</span> / Transparency</p>
            <h2 className="mt-3 font-display text-3xl font-semibold md:text-4xl">Every request, accounted for.</h2>
            <p className="mt-4 text-muted-foreground">
              Per-request logs with model, status, latency and token cost. Nothing is stored beyond what billing needs.
            </p>
          </div>
          <div className="overflow-x-auto rounded-sm border bg-card">
            <div className="flex items-center justify-between border-b px-4 py-2.5">
              <span className="label-mono">stream · vt_live_••••3f9a</span>
              <span className="font-mono text-[11px] text-signal animate-blink">● REC</span>
            </div>
            <table className="w-full font-mono text-[12px]">
              <tbody>
                {log.map((r) => (
                  <tr key={r[0]} className="border-b last:border-b-0">
                    <td className="px-4 py-2 text-muted-foreground">{r[0]}</td>
                    <td className="px-2 py-2">{r[1]}</td>
                    <td className="px-2 py-2">{r[2]}</td>
                    <td className="px-2 py-2 text-signal">{r[3]}</td>
                    <td className="px-2 py-2 text-ok">{r[4]}</td>
                    <td className="px-4 py-2 text-right text-muted-foreground">{r[5]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section>
        <div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-6 px-5 py-16 md:flex-row md:items-center">
          <h2 className="font-display text-3xl font-semibold md:text-4xl">
            Open a channel. <span className="text-signal">Keep coding.</span>
          </h2>
          <Link to="/pricing" className="rounded-sm bg-primary px-5 py-3 font-mono text-sm font-medium uppercase tracking-wider text-primary-foreground hover:brightness-110">
            See plans
          </Link>
        </div>
      </section>
    </>
  );
}

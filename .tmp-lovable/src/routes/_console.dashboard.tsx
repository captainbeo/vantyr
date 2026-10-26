import { createFileRoute, Link } from "@tanstack/react-router";
import { Check, CreditCard, KeyRound, TerminalSquare } from "lucide-react";
import { Bars, DataTable, Panel, PageTitle, StatGrid, Badge } from "@/components/console/ui";

export const Route = createFileRoute("/_console/dashboard")({
  head: () => ({
    meta: [
      { title: "Dashboard — Vantyr Console" },
      { name: "description", content: "Balance, usage, request volume and model distribution for your Vantyr account." },
      { property: "og:title", content: "Dashboard — Vantyr Console" },
      { property: "og:description", content: "Your Vantyr usage at a glance." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Dashboard,
});

// Sample data — replace with New API /api/user/self and /api/data/self responses.
const usage = [42, 55, 38, 61, 70, 66, 81, 74, 90, 85, 96, 72, 88, 102];
const models = [
  ["claude-sonnet", 46],
  ["codex", 28],
  ["claude-opus", 14],
  ["codex-mini", 8],
  ["claude-haiku", 4],
] as const;
const steps = [
  { t: "Create API key", d: "A key for your app or service", to: "/keys", icon: KeyRound, done: true },
  { t: "Add credits", d: "Keep balance before production traffic", to: "/wallet", icon: CreditCard, done: true },
  { t: "Send a request", d: "Verify routing in Playground or your client", to: "/playground", icon: TerminalSquare, done: false },
] as const;

function Dashboard() {
  return (
    <>
      <PageTitle code="CON-00" title="Dashboard" desc="Account overview for the current billing cycle." />
      <StatGrid
        items={[
          { k: "Balance", v: "$42.18", s: "remaining" },
          { k: "Used quota", v: "$17.82", s: "this cycle" },
          { k: "Requests", v: "4,812", s: "24h" },
          { k: "RPM / TPM", v: "12 / 48k", s: "avg" },
        ]}
      />

      <div className="mt-6 grid gap-px overflow-hidden rounded-sm border bg-border md:grid-cols-3">
        {steps.map(({ t, d, to, icon: Icon, done }, i) => (
          <Link key={t} to={to} className="group flex items-start gap-4 bg-background p-5 transition hover:bg-card">
            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-sm border ${done ? "border-ok/40 text-ok" : "border-signal/50 text-signal"}`}>
              {done ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
            </span>
            <span className="min-w-0">
              <span className="font-mono text-[11px] text-muted-foreground">STEP {String(i + 1).padStart(2, "0")}</span>
              <span className="mt-0.5 block font-display font-semibold group-hover:text-signal">{t}</span>
              <span className="block text-xs text-muted-foreground">{d}</span>
            </span>
          </Link>
        ))}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <Panel code="CON-01" title="Quota consumption · 14 days" right={<span className="font-mono text-[11px] text-muted-foreground">USD / day</span>}>
          <Bars data={usage} />
        </Panel>
        <Panel code="CON-02" title="Model distribution">
          <ul className="space-y-3 p-4">
            {models.map(([m, p]) => (
              <li key={m}>
                <div className="flex justify-between font-mono text-xs"><span className="text-signal">{m}</span><span>{p}%</span></div>
                <div className="mt-1.5 h-1.5 rounded-full bg-secondary"><div className="h-full rounded-full bg-signal" style={{ width: `${p}%` }} /></div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel className="mt-6" code="CON-03" title="Recent calls" right={<Link to="/usage-logs" className="font-mono text-[11px] uppercase tracking-wider text-signal hover:underline">All logs →</Link>}>
        <DataTable
          cols={["Time", "Key", "Model", "Status", "Latency", "Cost"]}
          rows={[
            ["01:51:04", "laptop", <span className="text-signal">claude-sonnet</span>, <Badge t="ok">200</Badge>, "412ms", "$0.0182"],
            ["01:50:58", "ci-runner", <span className="text-signal">codex</span>, <Badge t="ok">200</Badge>, "655ms", "$0.0097"],
            ["01:50:41", "laptop", <span className="text-signal">claude-opus</span>, <Badge t="ok">200</Badge>, "1.12s", "$0.0930"],
            ["01:50:12", "ci-runner", <span className="text-signal">codex-mini</span>, <Badge t="bad">429</Badge>, "—", "$0"],
          ]}
        />
      </Panel>
    </>
  );
}

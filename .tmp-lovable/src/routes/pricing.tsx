import { createFileRoute, Link } from "@tanstack/react-router";
import { PageHeading } from "@/components/site/SiteChrome";

export const Route = createFileRoute("/pricing")({
  head: () => ({
    meta: [
      { title: "Pricing — Vantyr" },
      { name: "description", content: "Monthly Vantyr plans for relaying Codex and Claude traffic. Flat subscription, no provider accounts." },
      { property: "og:title", content: "Pricing — Vantyr" },
      { property: "og:description", content: "Flat monthly plans for Codex and Claude relay traffic." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [{ rel: "canonical", href: "/pricing" }],
  }),
  component: Pricing,
});

const plans = [
  { id: "P-01", name: "Relay", price: "19", tag: "Solo developers", feats: ["5M tokens / month", "Codex + Claude", "1 API key", "Community support"] },
  { id: "P-02", name: "Relay Pro", price: "49", tag: "Daily heavy use", feats: ["20M tokens / month", "All models incl. Opus", "5 API keys", "Request logs · 30 days", "Priority routing"], hot: true },
  { id: "P-03", name: "Station", price: "149", tag: "Teams & CI", feats: ["80M tokens / month", "All models", "Unlimited keys", "Request logs · 90 days", "Dedicated capacity pool"] },
];

function Pricing() {
  return (
    <>
      <PageHeading code="SYS-10" title="Pricing">
        One subscription. Same endpoints you already use. Cancel any time.
      </PageHeading>
      <section className="mx-auto max-w-7xl px-5 py-16">
        <div className="grid gap-px overflow-hidden rounded-sm border bg-border lg:grid-cols-3">
          {plans.map((p) => (
            <div key={p.id} className={`relative flex flex-col bg-background p-7 ${p.hot ? "bg-card" : ""}`}>
              {p.hot && <div className="absolute inset-x-0 top-0 h-0.5 bg-signal" />}
              <div className="flex items-center justify-between">
                <span className="label-mono">{p.id}</span>
                {p.hot && <span className="font-mono text-[11px] uppercase tracking-widest text-signal">Most used</span>}
              </div>
              <h2 className="mt-6 font-display text-2xl font-semibold">{p.name}</h2>
              <p className="text-sm text-muted-foreground">{p.tag}</p>
              <div className="mt-6 font-display text-5xl font-semibold">
                €{p.price}
                <span className="ml-1 font-mono text-sm font-normal text-muted-foreground">/mo</span>
              </div>
              <ul className="mt-6 flex-1 space-y-2.5 font-mono text-[13px]">
                {p.feats.map((f) => (
                  <li key={f} className="flex gap-2.5">
                    <span className="text-signal">▸</span>
                    {f}
                  </li>
                ))}
              </ul>
              <Link
                to="/docs"
                className={`mt-8 rounded-sm px-4 py-2.5 text-center font-mono text-xs font-medium uppercase tracking-wider ${p.hot ? "bg-primary text-primary-foreground hover:brightness-110" : "border hover:bg-accent"}`}
              >
                Start {p.name}
              </Link>
            </div>
          ))}
        </div>
        <p className="mt-6 label-mono">Prices excl. VAT · overage billed per 1M tokens at plan rate</p>
      </section>
    </>
  );
}

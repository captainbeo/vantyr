import { createFileRoute } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { Badge, DataTable, Panel, PageTitle, StatGrid, btn } from "@/components/console/ui";

export const Route = createFileRoute("/_console/channels")({
  head: () => ({
    meta: [
      { title: "Channels — Vantyr Admin" },
      { name: "description", content: "Configure upstream provider channels, priorities, weights and health." },
      { property: "og:title", content: "Channels — Vantyr Admin" },
      { property: "og:description", content: "Upstream channel routing for Vantyr." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Channels,
});

// Sample data — replace with New API /api/channel/ responses.
const ch = [
  ["#01", "anthropic-pool-a", "Anthropic", "claude-*", "10", "50", "312ms", "$1,204", "ok"],
  ["#02", "anthropic-pool-b", "Anthropic", "claude-*", "5", "30", "355ms", "$860", "ok"],
  ["#03", "openai-codex", "OpenAI", "codex, codex-mini", "10", "100", "498ms", "$1,530", "ok"],
  ["#04", "openai-backup", "OpenAI", "codex", "0", "10", "—", "$0", "off"],
] as const;

function Channels() {
  return (
    <>
      <PageTitle code="ADM-00" title="Channels" desc="Upstream providers with multi-key polling, priority and auto-disable." actions={<button className={btn.primary}><Plus className="h-3.5 w-3.5" /> Add channel</button>} />
      <StatGrid items={[{ k: "Channels", v: "4" }, { k: "Enabled", v: "3" }, { k: "Avg response", v: "388", s: "ms" }, { k: "Spend · 30d", v: "$3,594" }]} />
      <Panel className="mt-6" code="ADM-01" title="All channels">
        <DataTable
          cols={["ID", "Name", "Type", "Models", "Priority", "Weight", "Response", "Used", "Status", ""]}
          rows={ch.map((c) => [
            <span className="text-muted-foreground">{c[0]}</span>, <span className="font-sans text-sm font-medium">{c[1]}</span>, c[2],
            <span className="text-signal">{c[3]}</span>, c[4], c[5], c[6], c[7],
            c[8] === "ok" ? <Badge t="ok">Enabled</Badge> : <Badge>Disabled</Badge>,
            <span className="flex gap-3"><button className={btn.link}>Test</button><button className={btn.danger}>Edit</button></span>,
          ])}
        />
      </Panel>
    </>
  );
}

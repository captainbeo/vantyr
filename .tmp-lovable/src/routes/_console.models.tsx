import { createFileRoute } from "@tanstack/react-router";
import { Badge, DataTable, Panel, PageTitle, btn } from "@/components/console/ui";

export const Route = createFileRoute("/_console/models")({
  head: () => ({
    meta: [
      { title: "Models — Vantyr Admin" },
      { name: "description", content: "Model pricing ratios, availability and groups on the Vantyr relay." },
      { property: "og:title", content: "Models — Vantyr Admin" },
      { property: "og:description", content: "Model pricing and availability." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Models,
});

const m = [
  ["claude-opus", "Anthropic", "$15.00", "$75.00", "default, pro", true],
  ["claude-sonnet", "Anthropic", "$3.00", "$15.00", "default", true],
  ["claude-haiku", "Anthropic", "$0.80", "$4.00", "default", true],
  ["codex", "OpenAI", "$1.25", "$10.00", "default", true],
  ["codex-mini", "OpenAI", "$0.25", "$2.00", "default", false],
] as const;

function Models() {
  return (
    <>
      <PageTitle code="ADM-10" title="Models" desc="Per-model pricing (per 1M tokens) and group availability." actions={<button className={btn.ghost}>Sync upstream</button>} />
      <Panel code="ADM-11" title={`${m.length} models`}>
        <DataTable
          cols={["Model", "Vendor", "Input", "Output", "Groups", "Status", ""]}
          rows={m.map((r) => [
            <span className="text-signal">{r[0]}</span>, r[1], r[2], r[3], <span className="text-muted-foreground">{r[4]}</span>,
            r[5] ? <Badge t="ok">Live</Badge> : <Badge t="warn">Hidden</Badge>, <button className={btn.link}>Edit</button>,
          ])}
        />
      </Panel>
    </>
  );
}

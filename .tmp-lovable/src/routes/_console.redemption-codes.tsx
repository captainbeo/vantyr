import { createFileRoute } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { Badge, DataTable, Panel, PageTitle, btn } from "@/components/console/ui";

export const Route = createFileRoute("/_console/redemption-codes")({
  head: () => ({
    meta: [
      { title: "Redemption Codes — Vantyr Admin" },
      { name: "description", content: "Generate and track Vantyr credit redemption codes." },
      { property: "og:title", content: "Redemption Codes — Vantyr Admin" },
      { property: "og:description", content: "Credit codes for Vantyr." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Codes,
});

const c = [
  ["launch-batch", "VT-8KQ2-••••", "$10.00", "2026-10-01", "unused"],
  ["launch-batch", "VT-1ZP7-••••", "$10.00", "2026-10-01", "used"],
  ["partner-acme", "VT-AC3E-••••", "$50.00", "2026-09-20", "unused"],
] as const;

function Codes() {
  return (
    <>
      <PageTitle code="ADM-30" title="Redemption Codes" actions={<button className={btn.primary}><Plus className="h-3.5 w-3.5" /> Generate</button>} />
      <Panel code="ADM-31" title="Codes">
        <DataTable
          cols={["Batch", "Code", "Value", "Created", "Status", ""]}
          rows={c.map((r) => [
            r[0], <span className="text-signal">{r[1]}</span>, r[2], r[3],
            r[4] === "used" ? <Badge>Used</Badge> : <Badge t="ok">Unused</Badge>, <button className={btn.danger}>Delete</button>,
          ])}
        />
      </Panel>
    </>
  );
}

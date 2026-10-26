import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Badge, DataTable, Panel, PageTitle, StatGrid, Tabs, btn, inputCls } from "@/components/console/ui";

export const Route = createFileRoute("/_console/usage-logs")({
  head: () => ({
    meta: [
      { title: "Usage Logs — Vantyr Console" },
      { name: "description", content: "Every relayed call with model, tokens, quota cost and latency." },
      { property: "og:title", content: "Usage Logs — Vantyr Console" },
      { property: "og:description", content: "Per-request usage logs for your Vantyr keys." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Logs,
});

// Sample data — replace with New API /api/log/self responses.
const rows = [
  ["2026-10-05 01:51:04", "laptop", "claude-sonnet", "Consume", "12,480", "5,720", "$0.0182", "412ms", true],
  ["2026-10-05 01:50:58", "ci-runner", "codex", "Consume", "6,210", "3,490", "$0.0097", "655ms", false],
  ["2026-10-05 01:50:41", "laptop", "claude-opus", "Consume", "22,900", "8,100", "$0.0930", "1.12s", true],
  ["2026-10-05 01:50:12", "ci-runner", "codex-mini", "Error", "0", "0", "$0", "—", false],
  ["2026-10-05 00:12:00", "—", "—", "Top up", "—", "—", "+$20.00", "—", false],
] as const;

const type = { Consume: "signal", Error: "bad", "Top up": "ok" } as const;

function Logs() {
  const [tab, setTab] = useState<"common" | "drawing" | "task">("common");
  return (
    <>
      <PageTitle code="CON-20" title="Usage Logs" desc="Call records with token consumption and quota deduction." />
      <StatGrid items={[{ k: "Quota used", v: "$17.82" }, { k: "Requests", v: "4,812" }, { k: "RPM", v: "12" }, { k: "TPM", v: "48k" }]} />

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Tabs value={tab} onChange={setTab} tabs={[{ id: "common", label: "Common" }, { id: "drawing", label: "Drawing" }, { id: "task", label: "Task" }]} />
        <div className="ml-auto grid w-full grid-cols-2 gap-2 sm:w-auto sm:grid-cols-[160px_160px_auto]">
          <input className={inputCls} placeholder="Key name" />
          <input className={inputCls} placeholder="Model" />
          <button className={btn.ghost + " col-span-2 sm:col-span-1"}>Filter</button>
        </div>
      </div>

      <Panel className="mt-4" code="CON-21" title={tab === "common" ? "Call log" : `${tab} log`}>
        {tab === "common" ? (
          <DataTable
            cols={["Time", "Key", "Model", "Type", "Prompt", "Completion", "Cost", "Latency", "Stream"]}
            rows={rows.map((r) => [
              <span className="text-muted-foreground">{r[0]}</span>, r[1], <span className="text-signal">{r[2]}</span>,
              <Badge t={type[r[3]]}>{r[3]}</Badge>, r[4], r[5], r[6], r[7], r[8] ? <Badge t="ok">SSE</Badge> : <span className="text-muted-foreground">—</span>,
            ])}
          />
        ) : (
          <p className="p-8 text-center font-mono text-xs text-muted-foreground">No {tab} tasks in this period.</p>
        )}
      </Panel>
    </>
  );
}

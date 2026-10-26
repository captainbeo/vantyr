import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Copy, Plus } from "lucide-react";
import { toast } from "sonner";
import { Badge, DataTable, Field, Panel, PageTitle, btn, inputCls } from "@/components/console/ui";

export const Route = createFileRoute("/_console/keys")({
  head: () => ({
    meta: [
      { title: "API Keys — Vantyr Console" },
      { name: "description", content: "Create and manage Vantyr API keys with quota limits, model restrictions and expiry." },
      { property: "og:title", content: "API Keys — Vantyr Console" },
      { property: "og:description", content: "Manage your Vantyr API keys." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Keys,
});

type Key = { name: string; key: string; status: "enabled" | "disabled" | "expired"; used: string; left: string; expires: string; models: string };

// Sample data — replace with New API /api/token/ responses.
const initial: Key[] = [
  { name: "laptop", key: "sk-••••3f9a", status: "enabled", used: "$12.40", left: "Unlimited", expires: "Never", models: "All" },
  { name: "ci-runner", key: "sk-••••81c2", status: "enabled", used: "$5.42", left: "$20.00", expires: "2026-12-31", models: "codex, codex-mini" },
  { name: "old-demo", key: "sk-••••07de", status: "expired", used: "$0.90", left: "$0", expires: "2026-09-01", models: "All" },
];

const tone = { enabled: "ok", disabled: "muted", expired: "bad" } as const;

function Keys() {
  const [keys, setKeys] = useState(initial);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");

  return (
    <>
      <PageTitle
        code="CON-10"
        title="API Keys"
        desc="Keys authenticate requests to the relay. Set quota, model limits and expiry per key."
        actions={<button onClick={() => setOpen((o) => !o)} className={btn.primary}><Plus className="h-3.5 w-3.5" /> New key</button>}
      />

      {open && (
        <Panel className="mb-6" code="NEW" title="Create key">
          <form
            className="grid gap-4 p-4 md:grid-cols-4"
            onSubmit={(e) => {
              e.preventDefault();
              setKeys((k) => [{ name: name || "untitled", key: "sk-••••new0", status: "enabled", used: "$0", left: "Unlimited", expires: "Never", models: "All" }, ...k]);
              setName(""); setOpen(false); toast.success("Key created (sample)");
            }}
          >
            <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="my-app" /></Field>
            <Field label="Quota (USD)"><input className={inputCls} placeholder="Unlimited" /></Field>
            <Field label="Expires"><input type="date" className={inputCls} /></Field>
            <div className="flex items-end"><button className={btn.primary + " w-full"}>Create</button></div>
          </form>
        </Panel>
      )}

      <Panel code="CON-11" title={`${keys.length} keys`}>
        <DataTable
          cols={["Name", "Key", "Status", "Used", "Remaining", "Models", "Expires", ""]}
          rows={keys.map((k, i) => [
            <span className="font-sans text-sm font-medium">{k.name}</span>,
            <span className="text-signal">{k.key}</span>,
            <Badge t={tone[k.status]}>{k.status}</Badge>,
            k.used, k.left,
            <span className="text-muted-foreground">{k.models}</span>,
            k.expires,
            <span className="flex justify-end gap-4">
              <button onClick={() => toast("Key copied (sample)")} className={btn.link}><Copy className="inline h-3 w-3" /></button>
              <button onClick={() => setKeys((ks) => ks.map((x, j) => (j === i ? { ...x, status: x.status === "enabled" ? "disabled" : "enabled" } : x)))} className={btn.danger}>
                {k.status === "enabled" ? "Disable" : "Enable"}
              </button>
              <button onClick={() => setKeys((ks) => ks.filter((_, j) => j !== i))} className={btn.danger}>Delete</button>
            </span>,
          ])}
        />
      </Panel>
    </>
  );
}

import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { DataTable, Field, Panel, PageTitle, StatGrid, Badge, btn, inputCls } from "@/components/console/ui";

export const Route = createFileRoute("/_console/wallet")({
  head: () => ({
    meta: [
      { title: "Wallet — Vantyr Console" },
      { name: "description", content: "Top up your Vantyr balance, redeem codes and view payment history." },
      { property: "og:title", content: "Wallet — Vantyr Console" },
      { property: "og:description", content: "Balance, top-ups and redemption codes." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Wallet,
});

const presets = [10, 20, 50, 100, 200, 500];

function Wallet() {
  const [amount, setAmount] = useState(20);
  const [code, setCode] = useState("");
  return (
    <>
      <PageTitle code="PER-00" title="Wallet" desc="Credits are deducted per request at the model's rate." />
      <StatGrid items={[{ k: "Balance", v: "$42.18" }, { k: "Used", v: "$17.82" }, { k: "Requests", v: "12,904" }, { k: "Referral reward", v: "$3.00" }]} />

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Panel code="PER-01" title="Top up">
          <div className="space-y-5 p-4">
            <div className="grid grid-cols-3 gap-px overflow-hidden rounded-sm border bg-border">
              {presets.map((p) => (
                <button key={p} onClick={() => setAmount(p)} className={`bg-background py-4 font-display text-xl font-semibold transition hover:bg-card ${amount === p ? "text-signal" : ""}`}>
                  ${p}
                </button>
              ))}
            </div>
            <Field label="Custom amount (USD)"><input type="number" min={1} value={amount} onChange={(e) => setAmount(Number(e.target.value))} className={inputCls} /></Field>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => toast("Checkout via Stripe (connect backend)")} className={btn.primary}>Pay ${amount} · Card</button>
              <button onClick={() => toast("Checkout via EPay (connect backend)")} className={btn.ghost}>Other methods</button>
            </div>
          </div>
        </Panel>
        <Panel code="PER-02" title="Redemption code">
          <form className="space-y-4 p-4" onSubmit={(e) => { e.preventDefault(); toast.success("Code submitted (sample)"); setCode(""); }}>
            <Field label="Code" hint="Codes are issued by an admin or partner."><input value={code} onChange={(e) => setCode(e.target.value)} className={inputCls} placeholder="VT-XXXX-XXXX" /></Field>
            <button className={btn.primary + " w-full"}>Redeem</button>
          </form>
          <div className="border-t p-4">
            <p className="label-mono">Referral link</p>
            <p className="mt-1.5 truncate font-mono text-xs text-signal">https://vantyr.dev/register?aff=k3f9</p>
          </div>
        </Panel>
      </div>

      <Panel className="mt-6" code="PER-03" title="History">
        <DataTable
          cols={["Date", "Method", "Amount", "Status"]}
          rows={[
            ["2026-10-05", "Card", "$20.00", <Badge t="ok">Paid</Badge>],
            ["2026-09-28", "Redemption", "$10.00", <Badge t="ok">Paid</Badge>],
            ["2026-09-12", "Card", "$30.00", <Badge t="ok">Paid</Badge>],
          ]}
        />
      </Panel>
    </>
  );
}

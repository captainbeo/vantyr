import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { Field, Panel, PageTitle, btn, inputCls } from "@/components/console/ui";

export const Route = createFileRoute("/_console/system-settings")({
  head: () => ({
    meta: [
      { title: "System Settings — Vantyr Admin" },
      { name: "description", content: "Site info, billing rules, payments, email and sign-in configuration." },
      { property: "og:title", content: "System Settings — Vantyr Admin" },
      { property: "og:description", content: "Root configuration for Vantyr." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: SystemSettings,
});

const sections = [
  { code: "SYS-A", title: "Site", fields: [["Site name", "Vantyr"], ["Server address", "https://api.vantyr.dev"], ["Footer note", ""]] },
  { code: "SYS-B", title: "Billing", fields: [["Quota per USD", "500000"], ["New user credit", "0.50"], ["Referral reward", "1.00"]] },
  { code: "SYS-C", title: "Payments", fields: [["Stripe publishable key", ""], ["EPay merchant ID", ""], ["Min top-up (USD)", "5"]] },
  { code: "SYS-D", title: "Sign-in", fields: [["Allow registration", "Yes"], ["Email verification", "Required"], ["OAuth providers", "GitHub"]] },
];

function SystemSettings() {
  return (
    <>
      <PageTitle code="ADM-40" title="System Settings" desc="Root only. Changes apply site-wide." actions={<button onClick={() => toast.success("Saved (sample)")} className={btn.primary}>Save all</button>} />
      <div className="grid gap-6 lg:grid-cols-2">
        {sections.map((s) => (
          <Panel key={s.code} code={s.code} title={s.title}>
            <div className="space-y-4 p-4">
              {s.fields.map(([l, v]) => <Field key={l} label={l ?? ""}><input defaultValue={v} className={inputCls} /></Field>)}
            </div>
          </Panel>
        ))}
      </div>
    </>
  );
}

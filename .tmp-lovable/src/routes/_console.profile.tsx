import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { Badge, Field, Panel, PageTitle, btn, inputCls } from "@/components/console/ui";
import { getSession } from "@/lib/session";

export const Route = createFileRoute("/_console/profile")({
  head: () => ({
    meta: [
      { title: "Profile — Vantyr Console" },
      { name: "description", content: "Account details, password, two-factor authentication and passkeys for Vantyr." },
      { property: "og:title", content: "Profile — Vantyr Console" },
      { property: "og:description", content: "Manage your Vantyr account security." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Profile,
});

function Profile() {
  const email = getSession()?.email ?? "";
  return (
    <>
      <PageTitle code="PER-10" title="Profile" desc="Account information and sign-in security." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel code="PER-11" title="Account">
          <form className="space-y-4 p-4" onSubmit={(e) => { e.preventDefault(); toast.success("Saved (sample)"); }}>
            <Field label="Email"><input defaultValue={email} className={inputCls} /></Field>
            <Field label="Display name"><input className={inputCls} placeholder="Your name" /></Field>
            <Field label="Group"><div className="flex gap-2"><Badge t="signal">default</Badge><Badge>Relay Pro</Badge></div></Field>
            <button className={btn.primary}>Save</button>
          </form>
        </Panel>
        <Panel code="PER-12" title="Security">
          <ul className="divide-y">
            {[
              ["Password", "Last changed 21 days ago", "Change"],
              ["Two-factor (TOTP)", "Not enabled", "Enable"],
              ["Passkey", "Passwordless sign-in", "Add passkey"],
              ["System access token", "For management API calls", "Generate"],
            ].map(([t, d, a]) => (
              <li key={t} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-4 py-4">
                <div className="min-w-0">
                  <p className="font-display font-semibold">{t}</p>
                  <p className="text-xs text-muted-foreground">{d}</p>
                </div>
                <button onClick={() => toast(`${a} (connect backend)`)} className={btn.ghost}>{a}</button>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </>
  );
}

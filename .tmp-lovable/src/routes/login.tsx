import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import mark from "@/assets/vantyr-mark.png";
import { signIn } from "@/lib/session";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Sign in — Vantyr" },
      { name: "description", content: "Sign in to your Vantyr console to manage API keys, usage and billing." },
      { property: "og:title", content: "Sign in — Vantyr" },
      { property: "og:description", content: "Access your Vantyr relay console." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Login,
});

function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    await signIn(email, password);
    navigate({ to: "/dashboard" });
  }

  const input = "mt-1.5 w-full rounded-sm border bg-background px-3 py-2.5 font-mono text-sm outline-none focus:border-signal";

  return (
    <section>
      <div className="mx-auto flex min-h-[70vh] max-w-7xl items-center justify-center px-5 py-16">
        <form onSubmit={submit} className="w-full max-w-sm rounded-sm border bg-card">
          <div className="flex items-center justify-between border-b px-5 py-3">
            <span className="label-mono"><span className="text-signal">AUTH</span> / Console access</span>
            <img src={mark} alt="" className="h-5 w-5" />
          </div>
          <div className="space-y-4 p-5">
            <h1 className="font-display text-2xl font-semibold">Sign in</h1>
            <label className="block">
              <span className="label-mono">Email</span>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
            </label>
            <label className="block">
              <span className="label-mono">Password</span>
              <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className={input} />
            </label>
            <button disabled={busy} className="w-full rounded-sm bg-primary py-2.5 font-mono text-xs font-medium uppercase tracking-wider text-primary-foreground hover:brightness-110 disabled:opacity-60">
              {busy ? "Connecting…" : "Open console"}
            </button>
            <p className="text-center text-xs text-muted-foreground">
              No account? <Link to="/pricing" className="text-signal hover:underline">Pick a plan</Link>
            </p>
          </div>
        </form>
      </div>
    </section>
  );
}

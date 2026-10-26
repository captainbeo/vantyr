import { createFileRoute, Link, Outlet, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  Activity, BarChart3, Boxes, CreditCard, Gift, KeyRound, LogOut, Play, RadioTower, Settings, User, Users,
} from "lucide-react";
import mark from "@/assets/vantyr-mark.png";
import { getSession, signOut, type Session } from "@/lib/session";
import { AmbientBackground } from "@/components/site/AmbientBackground";

export const Route = createFileRoute("/_console")({
  component: ConsoleLayout,
});

// Sidebar mirrors New API's sections: Chat / Console / Personal / Admin.
const groups = [
  { label: "Chat", items: [{ to: "/playground", label: "Playground", icon: Play }] },
  {
    label: "Console",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: BarChart3 },
      { to: "/keys", label: "API Keys", icon: KeyRound },
      { to: "/usage-logs", label: "Usage Logs", icon: Activity },
    ],
  },
  {
    label: "Personal",
    items: [
      { to: "/wallet", label: "Wallet", icon: CreditCard },
      { to: "/profile", label: "Profile", icon: User },
    ],
  },
  {
    label: "Admin",
    items: [
      { to: "/channels", label: "Channels", icon: RadioTower },
      { to: "/models", label: "Models", icon: Boxes },
      { to: "/users", label: "Users", icon: Users },
      { to: "/redemption-codes", label: "Redemption", icon: Gift },
      { to: "/system-settings", label: "System", icon: Settings },
    ],
  },
] as const;

function ConsoleLayout() {
  const navigate = useNavigate();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const s = getSession();
    if (!s) navigate({ to: "/login" });
    else setSession(s);
  }, [navigate]);

  if (!session) return <div className="p-10 label-mono">Authorising…</div>;

  return (
    <>
    <AmbientBackground />
    <div className="relative z-10 flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-card/40 md:flex">
        <Link to="/" className="flex h-14 items-center gap-2.5 border-b px-5">
          <img src={mark} alt="" className="h-6 w-6" />
          <span className="font-display font-semibold tracking-[0.18em]">VANTYR</span>
        </Link>
        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5">
          {groups.map((g) => (
            <div key={g.label}>
              <p className="label-mono px-2 pb-2">{g.label}</p>
              {g.items.map(({ to, label, icon: Icon }) => (
                <Link
                  key={to}
                  to={to}
                  className="group relative flex items-center gap-3 rounded-sm px-2 py-2 text-sm text-muted-foreground transition hover:bg-accent hover:text-foreground data-[status=active]:bg-accent data-[status=active]:text-foreground"
                >
                  <Icon className="h-4 w-4 shrink-0 group-data-[status=active]:text-signal" strokeWidth={1.75} />
                  {label}
                  <span className="absolute inset-y-1.5 left-0 w-0.5 bg-signal opacity-0 group-data-[status=active]:opacity-100" />
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t px-5 py-3 font-mono text-[11px] text-muted-foreground">
          <span className="mr-2 inline-block h-1.5 w-1.5 rounded-full bg-ok animate-blink" />
          Relays nominal
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b bg-background/85 px-5 backdrop-blur">
          <div className="flex gap-3 overflow-x-auto md:hidden">
            {groups.map((g) =>
              g.items.map((i) => (
                <Link key={i.to} to={i.to} className="whitespace-nowrap font-mono text-[11px] uppercase text-muted-foreground data-[status=active]:text-signal">
                  {i.label}
                </Link>
              )),
            )}
          </div>
          <div className="ml-auto flex items-center gap-4">
            <span className="hidden font-mono text-xs sm:inline">
              <span className="text-muted-foreground">Balance </span><span className="text-signal">$42.18</span>
            </span>
            <span className="hidden font-mono text-xs text-muted-foreground lg:inline">{session.email}</span>
            <button
              onClick={() => { signOut(); navigate({ to: "/login" }); }}
              className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
            >
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </button>
          </div>
        </header>
        <main className="flex-1 px-5 py-8">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
    </>
  );
}

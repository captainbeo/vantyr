import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import mark from "@/assets/vantyr-mark.png";

const nav = [
  { to: "/", label: "Relay" },
  { to: "/pricing", label: "Pricing" },
  { to: "/docs", label: "Models & Docs" },
] as const;

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-8 px-5">
        <Link to="/" className="flex items-center gap-2.5">
          <img src={mark} alt="" width={28} height={28} className="h-7 w-7" />
          <span className="font-display text-lg font-semibold tracking-[0.18em]">VANTYR</span>
        </Link>
        <nav className="hidden gap-6 md:flex">
          {nav.map((n) => (
            <Link
              key={n.to}
              to={n.to}
              activeOptions={{ exact: true }}
              className="font-mono text-xs uppercase tracking-widest text-muted-foreground transition-colors hover:text-foreground data-[status=active]:text-signal"
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <span className="hidden items-center gap-2 font-mono text-[11px] text-muted-foreground lg:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-ok animate-blink" /> ALL RELAYS NOMINAL
          </span>
          <Link to="/login" className="font-mono text-xs uppercase tracking-widest text-muted-foreground hover:text-foreground">
            Sign in
          </Link>
          <Link
            to="/pricing"
            className="rounded-sm bg-primary px-3.5 py-1.5 font-mono text-xs font-medium uppercase tracking-wider text-primary-foreground transition hover:brightness-110"
          >
            Get API key
          </Link>
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t">
      <div className="mx-auto grid max-w-7xl gap-8 px-5 py-10 md:grid-cols-[1fr_auto]">
        <div>
          <div className="flex items-center gap-2.5">
            <img src={mark} alt="" width={22} height={22} className="h-5.5 w-5.5" />
            <span className="font-display font-semibold tracking-[0.18em]">VANTYR</span>
          </div>
          <p className="mt-3 max-w-sm text-sm text-muted-foreground">
            Transfer relay for Codex and Claude traffic. One key, lower cost, no rewrites.
          </p>
        </div>
        <div className="flex gap-6 font-mono text-xs uppercase tracking-widest text-muted-foreground">
          {nav.map((n) => (
            <Link key={n.to} to={n.to} className="hover:text-foreground">
              {n.label}
            </Link>
          ))}
          <Link to="/brand" className="hover:text-foreground">
            Brand
          </Link>
        </div>
      </div>
      <div className="border-t">
        <div className="mx-auto flex max-w-7xl justify-between px-5 py-3 label-mono">
          <span>© {new Date().getFullYear()} Vantyr</span>
          <span>Build 26.10 · EU-W / US-E / AP-SE</span>
        </div>
      </div>
    </footer>
  );
}

export function PageHeading({ code, title, children }: { code: string; title: string; children?: ReactNode }) {
  return (
    <section className="border-b">
      <div className="mx-auto max-w-7xl px-5 py-16 md:py-20">
        <p className="label-mono">
          <span className="text-signal">{code}</span> / {title}
        </p>
        <h1 className="mt-4 max-w-3xl font-display text-4xl font-semibold leading-[1.05] md:text-6xl">{title}</h1>
        {children && <div className="mt-5 max-w-2xl text-muted-foreground">{children}</div>}
      </div>
    </section>
  );
}

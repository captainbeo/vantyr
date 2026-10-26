import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Shared Vantyr console primitives — reuse these on every console page. */

export const btn = {
  primary:
    "inline-flex items-center justify-center gap-2 rounded-sm bg-primary px-3.5 py-2 font-mono text-xs font-medium uppercase tracking-wider text-primary-foreground transition hover:brightness-110 disabled:opacity-60",
  ghost:
    "inline-flex items-center justify-center gap-2 rounded-sm border px-3.5 py-2 font-mono text-xs uppercase tracking-wider transition hover:bg-accent",
  link: "font-mono text-[11px] uppercase tracking-wider text-signal hover:underline",
  danger: "font-mono text-[11px] text-muted-foreground hover:text-destructive",
};

export const inputCls =
  "w-full rounded-sm border bg-background px-3 py-2 font-mono text-sm outline-none transition focus:border-signal";

export function PageTitle({ code, title, desc, actions }: { code: string; title: string; desc?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 grid grid-cols-[minmax(0,1fr)_auto] items-end gap-4">
      <div className="min-w-0">
        <p className="label-mono"><span className="text-signal">{code}</span> / {title}</p>
        <h1 className="mt-2 truncate font-display text-2xl font-semibold md:text-3xl">{title}</h1>
        {desc && <p className="mt-1 text-sm text-muted-foreground">{desc}</p>}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({ code, title, right, children, className }: { code?: string; title: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-sm border bg-card", className)}>
      <header className="flex items-center justify-between gap-3 border-b px-4 py-2.5">
        <span className="label-mono truncate">{code && <span className="text-signal">{code} / </span>}{title}</span>
        {right}
      </header>
      {children}
    </section>
  );
}

export function StatGrid({ items }: { items: { k: string; v: string; s?: string }[] }) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-sm border bg-border lg:grid-cols-4">
      {items.map((i) => (
        <div key={i.k} className="bg-background p-5">
          <div className="label-mono">{i.k}</div>
          <div className="mt-2 font-display text-2xl font-semibold md:text-3xl">
            {i.v}
            {i.s && <span className="ml-1.5 font-mono text-xs text-signal">{i.s}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

const tone = {
  ok: "border-ok/40 text-ok",
  warn: "border-chart-4/40 text-chart-4",
  bad: "border-destructive/40 text-destructive",
  muted: "border-border text-muted-foreground",
  signal: "border-signal/40 text-signal",
};
export function Badge({ t = "muted", children }: { t?: keyof typeof tone; children: ReactNode }) {
  return <span className={cn("inline-flex rounded-sm border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider", tone[t])}>{children}</span>;
}

export function DataTable({ cols, rows }: { cols: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full font-mono text-[12px]">
        <thead>
          <tr className="border-b text-left">
            {cols.map((c) => <th key={c} className="whitespace-nowrap px-4 py-2.5 label-mono font-normal">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b transition last:border-b-0 hover:bg-accent/40">
              {r.map((c, j) => <td key={j} className="whitespace-nowrap px-4 py-2.5">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="label-mono">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && <span className="mt-1 block text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { id: T; label: string }[] }) {
  return (
    <div className="flex gap-px overflow-hidden rounded-sm border bg-border">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={cn("bg-background px-3.5 py-2 font-mono text-xs uppercase tracking-wider transition", value === t.id ? "text-signal" : "text-muted-foreground hover:text-foreground")}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Bars({ data, height = 180 }: { data: number[]; height?: number }) {
  const max = Math.max(...data);
  return (
    <div className="flex items-end gap-1.5 px-4 pb-4 pt-6" style={{ height: height + 40 }}>
      {data.map((u, i) => (
        <div key={i} className="flex-1 rounded-t-[1px] bg-signal/75 transition hover:bg-signal" style={{ height: `${(u / max) * height}px` }} />
      ))}
    </div>
  );
}

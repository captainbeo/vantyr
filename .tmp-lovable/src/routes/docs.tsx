import { createFileRoute } from "@tanstack/react-router";
import { PageHeading } from "@/components/site/SiteChrome";

export const Route = createFileRoute("/docs")({
  head: () => ({
    meta: [
      { title: "Models & Docs — Vantyr" },
      { name: "description", content: "Supported Codex and Claude models on Vantyr and how to connect with your API key in under a minute." },
      { property: "og:title", content: "Models & Docs — Vantyr" },
      { property: "og:description", content: "Supported models and a one-line setup for the Vantyr relay." },
      { property: "og:type", content: "article" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [{ rel: "canonical", href: "/docs" }],
  }),
  component: Docs,
});

const models = [
  ["claude-opus", "Anthropic", "/v1/messages", "200K", "Pro+"],
  ["claude-sonnet", "Anthropic", "/v1/messages", "200K", "All"],
  ["claude-haiku", "Anthropic", "/v1/messages", "200K", "All"],
  ["codex", "OpenAI", "/v1/responses", "400K", "All"],
  ["codex-mini", "OpenAI", "/v1/responses", "200K", "All"],
];

const toc = [
  ["quickstart", "Quickstart"],
  ["models", "Supported models"],
  ["claude-code", "Claude Code"],
  ["codex-cli", "Codex CLI"],
  ["errors", "Errors"],
];

function Code({ children }: { children: string }) {
  return (
    <pre className="mt-4 overflow-x-auto rounded-sm border bg-card p-4 font-mono text-[13px] leading-relaxed">{children}</pre>
  );
}

function Docs() {
  return (
    <>
      <PageHeading code="SYS-20" title="Models & Docs">
        Vantyr speaks the native Anthropic and OpenAI APIs. Change the base URL, use your vt_ key, done.
      </PageHeading>
      <div className="mx-auto grid max-w-7xl gap-12 px-5 py-14 lg:grid-cols-[200px_1fr]">
        <aside className="hidden lg:block">
          <nav className="sticky top-24 space-y-2">
            <p className="label-mono mb-3">Index</p>
            {toc.map(([id, l], i) => (
              <a key={id} href={`#${id}`} className="block font-mono text-xs text-muted-foreground hover:text-signal">
                {String(i + 1).padStart(2, "0")} {l}
              </a>
            ))}
          </nav>
        </aside>
        <article className="max-w-3xl space-y-16">
          <section id="quickstart">
            <h2 className="font-display text-2xl font-semibold">Quickstart</h2>
            <p className="mt-3 text-muted-foreground">Set two environment variables. Any official SDK picks them up.</p>
            <Code>{`export ANTHROPIC_BASE_URL="https://api.vantyr.dev"
export ANTHROPIC_API_KEY="vt_live_xxxxxxxxxxxx"

export OPENAI_BASE_URL="https://api.vantyr.dev/v1"
export OPENAI_API_KEY="vt_live_xxxxxxxxxxxx"`}</Code>
          </section>

          <section id="models">
            <h2 className="font-display text-2xl font-semibold">Supported models</h2>
            <div className="mt-5 overflow-x-auto rounded-sm border">
              <table className="w-full font-mono text-[13px]">
                <thead className="bg-card">
                  <tr className="border-b text-left">
                    {["Model", "Upstream", "Endpoint", "Context", "Plans"].map((h) => (
                      <th key={h} className="px-4 py-2.5 label-mono font-normal">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m[0]} className="border-b last:border-b-0">
                      <td className="px-4 py-2.5 text-signal">{m[0]}</td>
                      <td className="px-4 py-2.5">{m[1]}</td>
                      <td className="px-4 py-2.5 text-muted-foreground">{m[2]}</td>
                      <td className="px-4 py-2.5">{m[3]}</td>
                      <td className="px-4 py-2.5">{m[4]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section id="claude-code">
            <h2 className="font-display text-2xl font-semibold">Claude Code</h2>
            <p className="mt-3 text-muted-foreground">Export the Anthropic variables above, then run as usual.</p>
            <Code>{`claude`}</Code>
          </section>

          <section id="codex-cli">
            <h2 className="font-display text-2xl font-semibold">Codex CLI</h2>
            <p className="mt-3 text-muted-foreground">Add a provider to ~/.codex/config.toml.</p>
            <Code>{`[model_providers.vantyr]
name = "Vantyr"
base_url = "https://api.vantyr.dev/v1"
env_key = "OPENAI_API_KEY"`}</Code>
          </section>

          <section id="errors">
            <h2 className="font-display text-2xl font-semibold">Errors</h2>
            <ul className="mt-4 divide-y rounded-sm border font-mono text-[13px]">
              {[
                ["401", "Key missing or revoked"],
                ["402", "Monthly token quota reached"],
                ["429", "Rate limit — retry after header"],
                ["503", "Upstream unavailable, auto-retried once"],
              ].map(([c, d]) => (
                <li key={c} className="flex gap-6 px-4 py-2.5">
                  <span className="w-10 text-signal">{c}</span>
                  <span className="text-muted-foreground">{d}</span>
                </li>
              ))}
            </ul>
          </section>
        </article>
      </div>
    </>
  );
}

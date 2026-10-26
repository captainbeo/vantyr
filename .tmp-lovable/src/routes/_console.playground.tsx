import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Field, Panel, PageTitle, btn, inputCls } from "@/components/console/ui";

export const Route = createFileRoute("/_console/playground")({
  head: () => ({
    meta: [
      { title: "Playground — Vantyr Console" },
      { name: "description", content: "Test Codex and Claude models through the Vantyr relay from your browser." },
      { property: "og:title", content: "Playground — Vantyr Console" },
      { property: "og:description", content: "Try models through the Vantyr relay." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Playground,
});

function Playground() {
  const [msgs, setMsgs] = useState<{ role: "user" | "relay"; text: string }[]>([]);
  const [text, setText] = useState("");
  return (
    <>
      <PageTitle code="CHT-00" title="Playground" desc="Send a test prompt to verify routing." />
      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <Panel code="CFG" title="Parameters">
          <div className="space-y-4 p-4">
            <Field label="Model">
              <select className={inputCls}>
                {["claude-sonnet", "claude-opus", "claude-haiku", "codex", "codex-mini"].map((m) => <option key={m}>{m}</option>)}
              </select>
            </Field>
            <Field label="Key"><select className={inputCls}><option>laptop</option><option>ci-runner</option></select></Field>
            <Field label="Max tokens"><input type="number" defaultValue={1024} className={inputCls} /></Field>
          </div>
        </Panel>
        <Panel code="CHT-01" title="Session">
          <div className="flex h-[440px] flex-col">
            <div className="flex-1 space-y-4 overflow-y-auto p-4">
              {msgs.length === 0 && <p className="pt-24 text-center font-mono text-xs text-muted-foreground">No messages. Prompts are sent through your selected key.</p>}
              {msgs.map((m, i) => (
                <div key={i} className={m.role === "user" ? "ml-auto max-w-[80%] rounded-sm bg-secondary px-3 py-2 text-sm" : "max-w-[80%] text-sm"}>
                  {m.role === "relay" && <span className="label-mono block pb-1 text-signal">relay</span>}
                  {m.text}
                </div>
              ))}
            </div>
            <form
              className="flex gap-2 border-t p-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (!text.trim()) return;
                setMsgs((m) => [...m, { role: "user", text }, { role: "relay", text: "Connect the console to your backend to get live responses." }]);
                setText("");
              }}
            >
              <input value={text} onChange={(e) => setText(e.target.value)} className={inputCls} placeholder="Type a prompt…" />
              <button className={btn.primary}>Send</button>
            </form>
          </div>
        </Panel>
      </div>
    </>
  );
}

import { createFileRoute } from "@tanstack/react-router";
import { Badge, DataTable, Panel, PageTitle, btn, inputCls } from "@/components/console/ui";

export const Route = createFileRoute("/_console/users")({
  head: () => ({
    meta: [
      { title: "Users — Vantyr Admin" },
      { name: "description", content: "Manage Vantyr users, roles, groups and balances." },
      { property: "og:title", content: "Users — Vantyr Admin" },
      { property: "og:description", content: "User administration for Vantyr." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: UsersPage,
});

const u = [
  ["#1", "root@vantyr.dev", "Root", "default", "$∞", "—", true],
  ["#14", "dev@acme.io", "User", "pro", "$42.18", "4,812", true],
  ["#22", "ci@builds.dev", "User", "default", "$3.40", "912", true],
  ["#31", "spam@x.co", "User", "default", "$0", "0", false],
] as const;

function UsersPage() {
  return (
    <>
      <PageTitle code="ADM-20" title="Users" desc="Roles, groups and balances." actions={<input className={inputCls + " w-56"} placeholder="Search email…" />} />
      <Panel code="ADM-21" title="All users">
        <DataTable
          cols={["ID", "Email", "Role", "Group", "Balance", "Requests", "Status", ""]}
          rows={u.map((r) => [
            <span className="text-muted-foreground">{r[0]}</span>, r[1], r[2] === "Root" ? <Badge t="signal">Root</Badge> : <Badge>User</Badge>,
            r[3], r[4], r[5], r[6] ? <Badge t="ok">Active</Badge> : <Badge t="bad">Banned</Badge>,
            <span className="flex gap-3"><button className={btn.link}>Edit</button><button className={btn.danger}>{r[6] ? "Ban" : "Unban"}</button></span>,
          ])}
        />
      </Panel>
    </>
  );
}

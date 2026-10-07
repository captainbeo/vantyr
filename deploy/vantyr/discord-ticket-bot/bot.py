# Vantyr Discord bot: private support tickets + live pricing channel.
# Ticket channels live under the Support category, created via a button panel
# in #support; staff get Claim/Close controls and the admin is pinged per
# ticket. The pricing task polls the public /api/pricing + /api/status
# endpoints (same data the admin UI edits) and a read-only DB view for plan
# rows, then edits one pinned message in #pricing — so admin-side price
# changes propagate automatically. Dedup state lives in channel topics.
import asyncio
import datetime as dt
import os
import re

import aiohttp
import discord
import pg8000.native

TOKEN_FILE = os.environ.get("DISCORD_TOKEN_FILE", "/run/secrets/token")
DB_DSN_FILE = os.environ.get("DISCORD_DB_DSN_FILE", "/run/secrets/db")

GUILD_ID = 1557219502712688792
TICKET_CATEGORY_ID = 1557522362071777331
PANEL_CHANNEL_ID = 1557326340359987221
PRICING_CHANNEL_ID = 1557532324113948762
ADMIN_ID = 552967704017895438
MODERATOR_ROLE_ID = 1557326343392333875

BASE_URL = "https://vantyr.xyz"
PRICING_POLL_SECONDS = 120
# Engine math (verified against live billing): $/1M input = 2 x model_ratio,
# output = input x completion_ratio, cache = input x cache_ratio.
QUOTA_PER_UNIT = 500_000

OPEN_ID = "vantyr:ticket:open"
CLAIM_ID = "vantyr:ticket:claim"
CLOSE_ID = "vantyr:ticket:close"
CLOSE_CONFIRM_ID = "vantyr:ticket:close:confirm"
PANEL_MARKER = "vantyr-ticket-panel"
PRICING_MARKER = "vantyr-pricing-live"
TICKET_TOPIC_PREFIX = "vantyr-ticket user:"
BRAND_COLOR = discord.Color(14309376)  # same orange as the Subscriber role

intents = discord.Intents.default()


def is_staff(member) -> bool:
    if member.id == ADMIN_ID or member.guild_permissions.manage_channels:
        return True
    return member.get_role(MODERATOR_ROLE_ID) is not None


def sanitize(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return cleaned[:24] or "user"


class TicketControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.secondary, custom_id=CLAIM_ID, emoji="🙋")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("Only staff can claim tickets.", ephemeral=True)
            return
        for child in self.children:
            if getattr(child, "custom_id", None) == CLAIM_ID:
                child.disabled = True
        await interaction.response.edit_message(
            content=interaction.message.content + f"\n**Claimed by {interaction.user.mention}**",
            view=self,
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id=CLOSE_ID, emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        topic = interaction.channel.topic or ""
        owner_id = None
        if topic.startswith(TICKET_TOPIC_PREFIX):
            try:
                owner_id = int(topic[len(TICKET_TOPIC_PREFIX):].split()[0])
            except (ValueError, IndexError):
                pass
        if owner_id != interaction.user.id and not is_staff(interaction.user):
            await interaction.response.send_message("Only the ticket owner or staff can close this ticket.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Close this ticket and delete the channel?",
            view=ConfirmCloseView(),
            ephemeral=True,
        )


class ConfirmCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Confirm close", style=discord.ButtonStyle.danger, custom_id=CLOSE_CONFIRM_ID, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        await interaction.response.defer()
        try:
            await channel.send(embed=discord.Embed(
                title="Ticket closed",
                description=f"Closed by {interaction.user.mention}. This channel will be deleted in 5 seconds.",
                color=discord.Color.red(),
            ))
            await asyncio.sleep(5)
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.NotFound:
            pass


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open a Ticket", style=discord.ButtonStyle.success, custom_id=OPEN_ID, emoji="🎫")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        await interaction.response.defer(ephemeral=True, thinking=True)
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if category is None:
            await interaction.followup.send("Support category not found. Please tell a staff member.", ephemeral=True)
            return
        for channel in category.text_channels:
            topic = channel.topic or ""
            if not topic.startswith(TICKET_TOPIC_PREFIX):
                continue
            try:
                existing_user = int(topic[len(TICKET_TOPIC_PREFIX):].split()[0])
            except (ValueError, IndexError):
                continue
            if existing_user == user.id:
                await interaction.followup.send(f"You already have an open ticket: {channel.mention}", ephemeral=True)
                return
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_channels=True, manage_messages=True,
            ),
        }
        mod_role = guild.get_role(MODERATOR_ROLE_ID)
        if mod_role is not None:
            overwrites[mod_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_messages=True, attach_files=True, embed_links=True,
            )
        channel = await guild.create_text_channel(
            name=f"ticket-{sanitize(user.display_name)}",
            category=category,
            overwrites=overwrites,
            topic=f"{TICKET_TOPIC_PREFIX}{user.id}",
        )
        embed = discord.Embed(
            title="New support ticket",
            description="Describe your issue with as much detail as you can: the client you use, what you expected, and any error message.",
            color=BRAND_COLOR,
        )
        embed.add_field(name="Opened by", value=user.mention)
        await channel.send(
            content=f"<@{ADMIN_ID}> — new ticket opened by {user.mention}",
            embed=embed,
            view=TicketControls(),
        )
        await interaction.followup.send(
            f"Your private ticket is open: {channel.mention} — only you and staff can see it.",
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Pricing sync
# ---------------------------------------------------------------------------

def fmt_price(value: float) -> str:
    if value == 0:
        return "$0"
    if value < 0.01:
        return f"${value:.3f}".rstrip("0").rstrip(".") if f"{value:.3f}".endswith("0") else f"${value:.3f}"
    return f"${value:.2f}"


def fetch_models(session_payload: dict) -> list[dict]:
    """Compute USD/1M input/output/cache per model from live ratios."""
    rows = []
    for m in session_payload.get("data", []):
        if m.get("quota_type") != 0 or (m.get("model_price", 0) > 0 and m.get("model_ratio", 0) == 0):
            continue  # per-call priced models: site page stays authoritative
        input_usd = m["model_ratio"] * (1_000_000 / QUOTA_PER_UNIT)
        output_usd = input_usd * m.get("completion_ratio", 1)
        cache_usd = input_usd * m.get("cache_ratio", 0)
        rows.append({
            "name": m["model_name"],
            "input": input_usd,
            "output": output_usd,
            "cache": cache_usd,
        })
    rows.sort(key=lambda r: (-r["input"], r["name"]))
    return rows


def render_models_block(rows: list[dict]) -> str:
    name_w = max([len(r["name"]) for r in rows] + [len("model")]) + 2
    header = f"{'model':<{name_w}}{'input':>7} {'output':>7} {'cache':>7}"
    lines = [header]
    for r in rows:
        lines.append(
            f"{r['name']:<{name_w}}{fmt_price(r['input']):>7} {fmt_price(r['output']):>7} {fmt_price(r['cache']):>7}"
        )
    return "\n".join(lines)


def fetch_plans(dsn: str) -> list[dict]:
    """Read plan rows through the read-only DB role (reflects every admin edit)."""
    # pg8000 DSN: postgresql://user:pass@host:5432/db
    m = re.match(r"postgresql://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(\w+)", dsn)
    if not m:
        raise ValueError("unparsable DSN")
    user, password, host, port, dbname = m.group(1), m.group(2), m.group(3), m.group(4) or 5432, m.group(5)
    con = pg8000.native.Connection(user, password=password, host=host, port=int(port), database=dbname)
    try:
        rows = con.run(
            "SELECT id, title, subtitle, price_amount, currency, duration_unit, "
            "duration_value, custom_seconds, enabled FROM subscription_plans "
            "ORDER BY sort_order DESC, id DESC"
        )
    finally:
        con.close()
    plans = []
    for r in rows:
        if r[7] and r[7] > 0:  # custom_seconds
            period = f"{r[7] // 86400} days" if r[7] % 86400 == 0 else f"{r[7]} seconds"
        else:
            unit = r[5] or "month"
            value = r[6] or 1
            period = f"{value} {unit}" + ("s" if value != 1 and not unit.endswith("s") else "")
        plans.append({
            "id": r[0], "title": r[1], "subtitle": r[2] or "",
            "price": float(r[3]), "currency": r[4] or "USD",
            "period": period, "enabled": bool(r[8]),
        })
    return plans


def render_plans_block(plans: list[dict]) -> str:
    if not plans:
        return "**Plans**\n_No plan rows available — see https://vantyr.xyz/pricing_"
    lines = ["**Plans**"]
    for p in plans:
        price = f"${p['price']:,.2f}"
        status = "available from the console" if p["enabled"] else "self-purchase paused — granted by staff"
        lines.append(
            f"• **{p['title']}** — **{price} {p['currency']} / {p['period']}** — {p['subtitle']} _({status})_"
        )
    return "\n".join(lines)


class VantyrBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self._http: aiohttp.ClientSession | None = None
        self._last_plans: list[dict] | None = None

    async def setup_hook(self):
        self.add_view(PanelView())
        self.add_view(TicketControls())
        self.add_view(ConfirmCloseView())
        asyncio.create_task(self.pricing_loop())

    async def pricing_loop(self):
        await self.wait_until_ready()
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        print("pricing loop started", flush=True)
        while not self.is_closed():
            try:
                await self.sync_pricing_message()
            except Exception as exc:  # keep the loop alive on any failure
                print(f"pricing sync failed: {exc!r}", flush=True)
            await asyncio.sleep(PRICING_POLL_SECONDS)

    async def fetch_live(self) -> dict:
        async with self._http.get(f"{BASE_URL}/api/pricing") as resp:
            resp.raise_for_status()
            payload = await resp.json(content_type=None)
        async with self._http.get(f"{BASE_URL}/api/status") as resp:
            resp.raise_for_status()
            status = await resp.json(content_type=None)
        qpu = status.get("data", {}).get("quota_per_unit") or status.get("quota_per_unit") or QUOTA_PER_UNIT
        return {"payload": payload, "quota_per_unit": qpu}

    async def refresh_plans(self) -> list[dict] | None:
        try:
            with open(DB_DSN_FILE) as fh:
                dsn = fh.read().strip()
            return await asyncio.to_thread(fetch_plans, dsn)
        except Exception as exc:
            print(f"plan poll failed (keeping last render): {exc!r}", flush=True)
            return None

    async def sync_pricing_message(self):
        guild = self.get_guild(GUILD_ID)
        channel = guild.get_channel(PRICING_CHANNEL_ID) if guild else None
        if channel is None:
            return
        live = await self.fetch_live()
        quota_per_unit = live["quota_per_unit"]
        global QUOTA_PER_UNIT
        QUOTA_PER_UNIT = quota_per_unit
        rows = fetch_models(live["payload"])
        if not rows:
            return
        plans = await self.refresh_plans()
        if plans is not None:
            self._last_plans = plans
        plans = self._last_plans or []

        embed = discord.Embed(
            title="Vantyr pricing — live",
            description=(
                "**Pay as you go** — USD per 1M tokens, billed per request:\n"
                f"```{render_models_block(rows)}```\n"
                f"{render_plans_block(plans)}\n\n"
                f"Auto-synced from live site configuration. Full details: {BASE_URL}/pricing"
            ),
            color=BRAND_COLOR,
            timestamp=dt.datetime.now(dt.timezone.utc),
        )
        embed.set_footer(text=PRICING_MARKER)

        target = None
        async for message in channel.history(limit=50):
            if message.author.id != self.user.id or not message.embeds:
                continue
            footer = message.embeds[0].footer
            if footer and footer.text == PRICING_MARKER:
                target = message
                break
        if target is None:
            target = await channel.send(embed=embed)
            try:
                await channel.pins()
                await target.pin()
            except discord.HTTPException:
                pass
        else:
            await target.edit(embed=embed)
        print(f"pricing synced ({len(rows)} models, {len(plans)} plans)", flush=True)

    async def on_ready(self):
        guild = self.get_guild(GUILD_ID)
        channel = guild.get_channel(PANEL_CHANNEL_ID) if guild else None
        if channel is not None:
            need_panel = True
            async for message in channel.history(limit=25):
                if message.author.id != self.user.id or not message.embeds:
                    continue
                footer = message.embeds[0].footer
                if footer and footer.text == PANEL_MARKER:
                    need_panel = False
                    break
            if need_panel:
                embed = discord.Embed(
                    title="Vantyr support tickets",
                    description=(
                        "Need help with keys, top-ups or billing? Click below to open a **private ticket** "
                        "— only you and Vantyr staff can read it.\n\nFor setup and common questions, check "
                        "the [docs](https://vantyr.xyz/docs) first."
                    ),
                    color=BRAND_COLOR,
                )
                embed.set_footer(text=PANEL_MARKER)
                await channel.send(embed=embed, view=PanelView())
        print(f"logged in as {self.user} in {guild.name if guild else 'unknown guild'}", flush=True)


def main():
    with open(TOKEN_FILE) as fh:
        token = fh.read().strip()
    bot = VantyrBot()
    bot.run(token)


if __name__ == "__main__":
    main()

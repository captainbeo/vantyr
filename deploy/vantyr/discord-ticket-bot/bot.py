# Vantyr Discord ticket bot.
# Private per-user ticket channels under the Support category, created via
# a button panel in #support. Staff get Claim/Close controls; the admin is
# pinged on every new ticket. Stateless: dedup state lives in channel topics.
import asyncio
import os
import re

import discord

TOKEN_FILE = os.environ.get("DISCORD_TOKEN_FILE", "/run/secrets/token")

GUILD_ID = 1557219502712688792
TICKET_CATEGORY_ID = 1557522362071777331
PANEL_CHANNEL_ID = 1557326340359987221
ADMIN_ID = 552967704017895438
MODERATOR_ROLE_ID = 1557326343392333875

OPEN_ID = "vantyr:ticket:open"
CLAIM_ID = "vantyr:ticket:claim"
CLOSE_ID = "vantyr:ticket:close"
CLOSE_CONFIRM_ID = "vantyr:ticket:close:confirm"
PANEL_MARKER = "vantyr-ticket-panel"
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


class VantyrBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)

    async def setup_hook(self):
        self.add_view(PanelView())
        self.add_view(TicketControls())
        self.add_view(ConfirmCloseView())

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

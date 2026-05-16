"""NewsBot — Discord bot for personal AI-powered news briefings.

Commands:
  /brief       — Generate a briefing now
  /add <url>   — Add an RSS news source
  /remove <id> — Remove a source by ID
  /sources     — List your sources
  /recommend   — Browse recommended sources
  /schedule    — Set daily briefing time
  /track       — Track a topic over time
  /untrack     — Stop tracking a topic
  /read <url>  — AI summarizes an article
  /help        — Show all commands
"""

import os
import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from db import init_db, get_user, create_user, update_user, get_all_users
from db import add_source, remove_source, get_sources
from db import add_track, remove_track, get_tracked_topics
from fetcher import NewsFetcher
from briefing import BriefingGenerator
from llm import LLMClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("newsbot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN not set in .env")


class NewsBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.fetcher = NewsFetcher()
        self.briefer = BriefingGenerator()
        self.llm = LLMClient()

    async def setup_hook(self):
        await init_db()
        await self.tree.sync()
        self.daily_briefing.start()
        logger.info("NewsBot ready — commands synced")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")

    @tasks.loop(minutes=60)
    async def daily_briefing(self):
        """Check every hour if any user should receive a briefing."""
        now = datetime.now(timezone.utc)
        current_time = now.strftime("%H:%M")

        users = await get_all_users()
        for user in users:
            if user.get("briefing_time") == current_time:
                discord_id = user["discord_id"]
                try:
                    member = await self.fetch_user(int(discord_id))
                    if member:
                        briefing = await self.briefer.generate(discord_id)
                        for chunk in self._chunk_text(briefing, 1900):
                            await member.send(chunk)
                        logger.info(f"Briefing sent to {discord_id}")
                except Exception as e:
                    logger.error(f"Briefing failed for {discord_id}: {e}")

    def _chunk_text(self, text: str, max_len: int) -> list:
        """Split long text into Discord-safe chunks."""
        chunks = []
        while len(text) > max_len:
            split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                split_at = max_len
            chunks.append(text[:split_at])
            text = text[split_at:].strip()
        if text:
            chunks.append(text)
        return chunks


client = NewsBot()
tree = client.tree


# ===== COMMANDS =====

@tree.command(name="brief", description="🌅 Generate a news briefing now")
async def cmd_brief(interaction: discord.Interaction):
    await interaction.response.defer()
    await create_user(str(interaction.user.id))
    briefing = await client.briefer.generate(str(interaction.user.id))

    for chunk in client._chunk_text(briefing, 1900):
        await interaction.followup.send(chunk)


@tree.command(name="add", description="📡 Add an RSS news source")
@app_commands.describe(url="RSS feed URL")
async def cmd_add(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    await create_user(str(interaction.user.id))

    # Validate feed
    items = await client.fetcher.fetch_feed(url, max_items=1)
    if not items:
        await interaction.followup.send(
            "❌ Not a valid RSS feed. Check the URL.\n"
            "Use `/recommend` to browse curated sources."
        )
        return

    name = items[0].get("source", url.split("/")[2])
    await add_source(str(interaction.user.id), name, url)
    await interaction.followup.send(
        f"✅ **{name}** added!\n"
        f"Run `/brief` to get your briefing now."
    )


@tree.command(name="remove", description="🗑️ Remove a news source")
@app_commands.describe(source_id="Source ID (check /sources)")
async def cmd_remove(interaction: discord.Interaction, source_id: int):
    success = await remove_source(source_id, str(interaction.user.id))
    if success:
        await interaction.response.send_message("✅ Source removed.")
    else:
        await interaction.response.send_message("❌ Source not found.")


@tree.command(name="sources", description="📋 List your news sources")
async def cmd_sources(interaction: discord.Interaction):
    sources = await get_sources(str(interaction.user.id))
    if not sources:
        await interaction.response.send_message(
            "📭 **No news sources yet.**\n"
            "Use `/recommend` to browse curated sources or\n"
            "`/add <rss_url>` to add your own."
        )
        return

    lines = ["📡 **My News Sources**\n"]
    for s in sources:
        lines.append(f"`{s['id']:2d}` ─ **{s['name']}** ({s['category']})")
        lines.append(f"       <{s['url']}>")

    lines.append(f"\nTotal: {len(sources)} sources")
    await interaction.response.send_message("\n".join(lines))


@tree.command(name="recommend", description="🌟 Browse and subscribe to curated news sources")
@app_commands.describe(
    category="Category (global / geopolitics / asia / tech_policy)",
    name="Source name (optional — leave empty to list)"
)
async def cmd_recommend(interaction: discord.Interaction,
                         category: str = None,
                         name: str = None):
    await create_user(str(interaction.user.id))

    if name and category:
        sources = client.fetcher.RECOMMENDED_SOURCES.get(category, [])
        found = [s for s in sources if s[0].lower() == name.lower()]
        if found:
            await add_source(str(interaction.user.id), found[0][0], found[0][1], category)
            await interaction.response.send_message(
                f"✅ **{found[0][0]}** added!"
            )
        else:
            await interaction.response.send_message(
                f"❌ Could not find '{name}' in '{category}'.\n"
                f"Run `/recommend {category}` to see the list."
            )
        return

    if category:
        sources = client.fetcher.RECOMMENDED_SOURCES.get(category, [])
        lines = [f"🌟 **{category}** sources\n"]
        for s_name, s_url in sources:
            lines.append(f"• **{s_name}**")
            lines.append(f"  Run `/recommend {category}:{s_name}` to add")
        await interaction.response.send_message("\n".join(lines))
        return

    categories = [
        ("global", "🌍 Global News"),
        ("geopolitics", "🌐 Geopolitics"),
        ("asia", "🌏 Asia"),
        ("tech_policy", "💻 Tech / Policy"),
        ("ai_ml", "🤖 AI / ML"),
    ]
    lines = ["🌟 **Curated News Sources**\n"]
    for cat_id, cat_name in categories:
        count = len(client.fetcher.RECOMMENDED_SOURCES.get(cat_id, []))
        lines.append(f"`/recommend {cat_id}` ─ {cat_name} ({count} sources)")
    lines.append("\nPick a category, then choose a source by name.")
    await interaction.response.send_message("\n".join(lines))


@cmd_recommend.autocomplete("category")
async def recommend_category_autocomplete(interaction: discord.Interaction, current: str):
    cats = ["global", "geopolitics", "asia", "tech_policy", "ai_ml"]
    return [
        app_commands.Choice(name=c, value=c)
        for c in cats if current.lower() in c
    ]


@cmd_recommend.autocomplete("name")
async def recommend_name_autocomplete(interaction: discord.Interaction, current: str):
    options = interaction.data.get("options", [])
    cat = next((o["value"] for o in options if o.get("name") == "category"), "")
    sources = client.fetcher.RECOMMENDED_SOURCES.get(cat, [])
    return [
        app_commands.Choice(name=n, value=n)
        for n, _ in sources if current.lower() in n.lower()
    ][:25]


@tree.command(name="schedule", description="⏰ Set daily briefing time (24h UTC)")
@app_commands.describe(
    time="Briefing time (e.g. 07:00 or 18:30)",
    timezone="Timezone (e.g. Asia/Seoul, US/Eastern, UTC)"
)
async def cmd_schedule(interaction: discord.Interaction, time: str, timezone: str = "UTC"):
    await create_user(str(interaction.user.id))

    try:
        datetime.strptime(time, "%H:%M")
    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid time format. Use `07:00` or `18:30`."
        )
        return

    await update_user(str(interaction.user.id), briefing_time=time, timezone=timezone)
    local_name = timezone if timezone != "UTC" else "UTC"

    await interaction.response.send_message(
        f"✅ **Briefing time set!**\n"
        f"   Daily at {time} UTC ({local_name}) — I'll DM you the briefing.\n\n"
        f"💡 Use `/brief` to get one right now."
    )


@tree.command(name="track", description="📌 Track a topic over time")
@app_commands.describe(topic="Topic to track (e.g. Ukraine, Taiwan, AI regulation)")
async def cmd_track(interaction: discord.Interaction, topic: str):
    await create_user(str(interaction.user.id))
    await add_track(str(interaction.user.id), topic)
    await interaction.response.send_message(
        f"✅ Now tracking **'{topic}'**.\n"
        f"I'll flag new articles and show how the story evolves."
    )


@tree.command(name="untrack", description="⛔ Stop tracking a topic")
@app_commands.describe(topic="Topic to stop tracking")
async def cmd_untrack(interaction: discord.Interaction, topic: str):
    success = await remove_track(str(interaction.user.id), topic)
    if success:
        await interaction.response.send_message(f"✅ Stopped tracking **'{topic}'**.")
    else:
        await interaction.response.send_message(
            f"❌ Not currently tracking **'{topic}'**.\n"
            f"Use `/track <topic>` to start."
        )


@tree.command(name="read", description="📖 AI summarizes an article for you")
@app_commands.describe(url="Article URL")
async def cmd_read(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    if not client.llm.enabled:
        await interaction.followup.send(
            "⚠️ LLM API key not configured. Add `LLM_API_KEY` to `.env`."
        )
        return

    text = await client.fetcher.fetch_article_text(url)
    if not text:
        await interaction.followup.send("❌ Could not load the article.")
        return

    summary = await client.llm.summarize("Article", text[:3000], url)
    context = await client.llm.why_it_matters("Article", text[:2000])

    lines = [
        f"📖 **Article Summary**\n",
        f"📝 {summary}" if summary else "📝 Could not generate a summary.",
        "",
    ]
    if context:
        lines.append(f"💡 **Context:** {context}")
        lines.append("")

    lines.append(f"🔗 <{url}>")
    await interaction.followup.send("\n".join(lines))


@tree.command(name="help", description="📚 Show all commands")
async def cmd_help(interaction: discord.Interaction):
    lines = [
        "🌅 **NewsBot — AI News Briefing**",
        "",
        "**Commands**",
        "`/brief` — Generate briefing now",
        "`/add <rss_url>` — Add RSS source",
        "`/remove <id>` — Remove source",
        "`/sources` — List your sources",
        "`/recommend [category]` — Browse curated sources",
        "`/schedule <time>` — Set daily briefing time",
        "`/track <topic>` — Track a story topic",
        "`/untrack <topic>` — Stop tracking",
        "`/read <url>` — AI-summarize an article",
        "",
        "**💡 Quick Start**",
        "1. `/recommend global` → add Reuters, BBC, AP",
        "2. `/schedule 07:00` → daily at 7 AM",
        "3. `/track Ukraine` → track story evolution",
        "4. `/brief` → get a briefing right now",
    ]
    await interaction.response.send_message("\n".join(lines))


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)

"""NewsBot — Discord bot for personal AI-powered news briefings.

Commands:
  /brief        — Generate a briefing now
  /add <url>    — Add an RSS news source
  /remove <id>  — Remove a source by ID
  /sources      — List your sources
  /recommend    — Browse recommended sources
  /schedule     — Set daily briefing time
  /track        — Track a topic over time
  /untrack      — Stop tracking a topic
  /read <url>   — AI summarizes an article
  /help         — Show all commands
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
                        # Discord has 2000 char limit
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

@tree.command(name="brief", description="🌅 지금 뉴스 브리핑을 받습니다")
async def cmd_brief(interaction: discord.Interaction):
    await interaction.response.defer()
    await create_user(str(interaction.user.id))
    briefing = await client.briefer.generate(str(interaction.user.id))

    for chunk in client._chunk_text(briefing, 1900):
        await interaction.followup.send(chunk)


@tree.command(name="add", description="📡 RSS 뉴스 소스를 추가합니다")
@app_commands.describe(url="RSS feed URL")
async def cmd_add(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    await create_user(str(interaction.user.id))

    # Validate feed
    items = await client.fetcher.fetch_feed(url, max_items=1)
    if not items:
        await interaction.followup.send(
            "❌ 유효한 RSS 피드가 아닙니다. URL을 확인해주세요.\n"
            "`/recommend`로 추천 소스를 확인하세요."
        )
        return

    name = items[0].get("source", url.split("/")[2])
    await add_source(str(interaction.user.id), name, url)
    await interaction.followup.send(
        f"✅ **{name}** 추가 완료!\n"
        f"`/brief`로 지금 브리핑을 받아보세요."
    )


@tree.command(name="remove", description="🗑️ 뉴스 소스를 제거합니다")
@app_commands.describe(source_id="source 번호 (/sources로 확인)")
async def cmd_remove(interaction: discord.Interaction, source_id: int):
    success = await remove_source(source_id, str(interaction.user.id))
    if success:
        await interaction.response.send_message("✅ 소스가 제거되었습니다.")
    else:
        await interaction.response.send_message("❌ 해당 소스를 찾을 수 없습니다.")


@tree.command(name="sources", description="📋 내 뉴스 소스 목록을 확인합니다")
async def cmd_sources(interaction: discord.Interaction):
    sources = await get_sources(str(interaction.user.id))
    if not sources:
        await interaction.response.send_message(
            "📭 **등록된 뉴스 소스가 없습니다.**\n"
            "`/recommend`로 추천 소스를 추가하거나\n"
            "`/add <rss_url>`로 직접 추가하세요."
        )
        return

    lines = ["📡 **내 뉴스 소스**\n"]
    for s in sources:
        lines.append(f"`{s['id']:2d}` ─ **{s['name']}** ({s['category']})")
        lines.append(f"       <{s['url']}>")

    lines.append(f"\n총 {len(sources)}개의 소스")
    await interaction.response.send_message("\n".join(lines))


@tree.command(name="recommend", description="🌟 추천 뉴스 소스를 구독합니다")
@app_commands.describe(
    category="카테고리 (global / geopolitics / asia / tech_policy)",
    name="소스 이름 (선택 — 비우면 목록 표시)"
)
async def cmd_recommend(interaction: discord.Interaction,
                         category: str = None,
                         name: str = None):
    await create_user(str(interaction.user.id))

    if name and category:
        # Subscribe to specific source
        sources = client.fetcher.RECOMMENDED_SOURCES.get(category, [])
        found = [s for s in sources if s[0].lower() == name.lower()]
        if found:
            await add_source(str(interaction.user.id), found[0][0], found[0][1], category)
            await interaction.response.send_message(
                f"✅ **{found[0][0]}** 추가 완료!"
            )
        else:
            await interaction.response.send_message(
                f"❌ '{name}'을(를) '{category}'에서 찾을 수 없습니다.\n"
                f"`/recommend {category}`로 목록을 확인하세요."
            )
        return

    if category:
        sources = client.fetcher.RECOMMENDED_SOURCES.get(category, [])
        lines = [f"🌟 **{category}** 소스 목록\n"]
        for s_name, s_url in sources:
            lines.append(f"• **{s_name}**")
            lines.append(f"  `/recommend {category}:{s_name}` 으로 추가")
        await interaction.response.send_message("\n".join(lines))
        return

    # Show categories
    categories = [
        ("global", "🌍 국제 뉴스"),
        ("geopolitics", "🌐 지정학"),
        ("asia", "🌏 아시아"),
        ("tech_policy", "💻 기술/정책"),
    ]
    lines = ["🌟 **추천 뉴스 소스 카테고리**\n"]
    for cat_id, cat_name in categories:
        count = len(client.fetcher.RECOMMENDED_SOURCES.get(cat_id, []))
        lines.append(f"`/recommend {cat_id}` ─ {cat_name} ({count}개 소스)")
    lines.append("\n각 카테고리를 선택한 후 소스 이름을 입력하세요.")
    await interaction.response.send_message("\n".join(lines))


@cmd_recommend.autocomplete("category")
async def recommend_category_autocomplete(interaction: discord.Interaction, current: str):
    cats = ["global", "geopolitics", "asia", "tech_policy"]
    return [
        app_commands.Choice(name=c, value=c)
        for c in cats if current.lower() in c
    ]


@cmd_recommend.autocomplete("name")
async def recommend_name_autocomplete(interaction: discord.Interaction, current: str):
    # Get the category from the current options
    options = interaction.data.get("options", [])
    cat = next((o["value"] for o in options if o.get("name") == "category"), "")
    sources = client.fetcher.RECOMMENDED_SOURCES.get(cat, [])
    return [
        app_commands.Choice(name=n, value=n)
        for n, _ in sources if current.lower() in n.lower()
    ][:25]


@tree.command(name="schedule", description="⏰ 브리핑 시간을 설정합니다 (24h, UTC)")
@app_commands.describe(
    time="브리핑 시간 (예: 07:00 또는 18:30)",
    timezone="시간대 (예: Asia/Seoul, US/Eastern, UTC)"
)
async def cmd_schedule(interaction: discord.Interaction, time: str, timezone: str = "UTC"):
    await create_user(str(interaction.user.id))

    # Validate time format
    try:
        datetime.strptime(time, "%H:%M")
    except ValueError:
        await interaction.response.send_message(
            "❌ 시간 형식이 잘못되었습니다. `07:00` 또는 `18:30` 형식으로 입력하세요."
        )
        return

    await update_user(str(interaction.user.id), briefing_time=time, timezone=timezone)
    utc_time = time
    local_name = timezone if timezone != "UTC" else "UTC"

    await interaction.response.send_message(
        f"✅ **브리핑 시간 설정 완료!**\n"
        f"   매일 {utc_time} UTC ({local_name})에 DM으로 브리핑을 보내드립니다.\n\n"
        f"💡 `/brief`로 지금 바로 받아볼 수도 있습니다."
    )


@tree.command(name="track", description="📌 관심 주제를 추적합니다")
@app_commands.describe(topic="추적할 주제 (예: Ukraine, Taiwan, AI regulation)")
async def cmd_track(interaction: discord.Interaction, topic: str):
    await create_user(str(interaction.user.id))
    await add_track(str(interaction.user.id), topic)
    await interaction.response.send_message(
        f"✅ **'{topic}'** 주제 추적을 시작합니다.\n"
        f"이 주제의 새 기사가 발견되면 알려드립니다."
    )


@tree.command(name="untrack", description="⛔ 주제 추적을 중단합니다")
@app_commands.describe(topic="중단할 주제")
async def cmd_untrack(interaction: discord.Interaction, topic: str):
    success = await remove_track(str(interaction.user.id), topic)
    if success:
        await interaction.response.send_message(f"✅ **'{topic}'** 추적이 중단되었습니다.")
    else:
        await interaction.response.send_message(
            f"❌ **'{topic}'** 추적 기록이 없습니다.\n"
            f"`/track <주제>`로 새 주제를 추적하세요."
        )


@tree.command(name="read", description="📖 AI가 기사를 요약해줍니다")
@app_commands.describe(url="기사 URL")
async def cmd_read(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    if not client.llm.enabled:
        await interaction.followup.send(
            "⚠️ LLM API 키가 설정되지 않았습니다. `.env` 파일에 `LLM_API_KEY`를 추가하세요."
        )
        return

    text = await client.fetcher.fetch_article_text(url)
    if not text:
        await interaction.followup.send("❌ 기사를 불러올 수 없습니다.")
        return

    summary = await client.llm.summarize("Article", text[:3000], url)
    context = await client.llm.why_it_matters("Article", text[:2000])

    lines = [
        f"📖 **기사 요약**\n",
        f"📝 {summary}" if summary else "📝 요약을 생성할 수 없습니다.",
        "",
    ]
    if context:
        lines.append(f"💡 **맥락:** {context}")
        lines.append("")

    lines.append(f"🔗 <{url}>")
    await interaction.followup.send("\n".join(lines))


@tree.command(name="help", description="📚 모든 명령어를 확인합니다")
async def cmd_help(interaction: discord.Interaction):
    lines = [
        "🌅 **NewsBot — AI 뉴스 브리핑 봇**",
        "",
        "**명령어**",
        "`/brief` — 지금 브리핑 생성",
        "`/add <rss_url>` — RSS 소스 추가",
        "`/remove <id>` — 소스 제거",
        "`/sources` — 내 소스 목록",
        "`/recommend [category]` — 추천 소스 구독",
        "`/schedule <time>` — 매일 브리핑 시간 설정",
        "`/track <topic>` — 주제 추적",
        "`/untrack <topic>` — 추적 중단",
        "`/read <url>` — 기사 요약",
        "",
        "**💡 사용법**",
        "1. `/recommend global` → Reuters, BBC, AP 추가",
        "2. `/schedule 07:00` → 매일 아침 7시 브리핑",
        "3. `/track Ukraine` → 우크라이나 관련 기사 추적",
        "4. `/brief` → 지금 바로 받아보기",
    ]
    await interaction.response.send_message("\n".join(lines))


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)

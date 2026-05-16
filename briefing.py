"""Briefing generator — assembles news into a morning briefing."""

from datetime import datetime, timezone
from typing import Optional
from fetcher import NewsFetcher
from llm import LLMClient
from db import get_sources, save_story, get_recent_stories, upsert_cluster

NARRATORS = ["📰", "🌍", "📡", "🔍", "🗞️", "⚡", "🇺🇳", "🌏"]


class BriefingGenerator:
    """Generates rich news briefings."""

    def __init__(self):
        self.fetcher = NewsFetcher()
        self.llm = LLMClient()

    async def generate(self, discord_id: str) -> str:
        """Generate a full briefing for a user."""
        sources = await get_sources(discord_id)
        if not sources:
            return (
                "📭 **아직 뉴스 소스가 없어요!**\n"
                "`/sources`로 추천 소스를 구독하거나\n"
                "`/add <rss_url>`로 직접 추가하세요."
            )

        # Fetch all sources
        urls = [s["url"] for s in sources]
        articles = await self.fetcher.fetch_multiple(urls, max_per_feed=10)

        if not articles:
            return "📭 오늘은 새로운 소식이 없습니다."

        # Limit to top 15 for briefing
        articles = articles[:15]

        # Build briefing
        lines = [self._header(articles)]
        lines.append("")

        for i, article in enumerate(articles):
            blocks = await self._build_article_block(article, i)
            for block in blocks:
                lines.append(block)
            lines.append("")

        lines.append(self._footer())
        return "\n".join(lines)

    async def generate_topic_brief(self, articles: list) -> str:
        """Generate a thematic briefing for a tracked topic."""
        lines = ["📌 **주제별 브리핑**\n"]

        for i, article in enumerate(articles[:8], 1):
            summary = None
            if article.get("content"):
                summary = await self.llm.summarize(
                    article["title"], article["content"][:2000], article["source"]
                )

            lines.append(
                f"**{i}. {article['title']}**\n"
                f"   출처: {article['source']}\n"
                f"   {summary or article.get('summary', '')[:200]}\n"
            )

        # Check for tension between sources
        if len(articles) >= 2:
            tension = await self.llm.detect_tension(articles)
            if tension:
                lines.append(f"⚡ **관점 차이 / 모순:**\n{tension}\n")

        return "\n".join(lines)

    async def _build_article_block(self, article: dict, index: int) -> list:
        """Build a formatted article block."""
        blocks = []
        emoji = NARRATORS[index % len(NARRATORS)]

        # Summarize
        summary = None
        context = None
        if article.get("content"):
            summary = await self.llm.summarize(
                article["title"], article["content"][:2000], article["source"]
            )
            if index < 5:  # Top stories get context
                context = await self.llm.why_it_matters(
                    article["title"], article["content"][:2000]
                )

        time_str = ""
        if article.get("published"):
            try:
                dt = datetime.fromisoformat(article["published"])
                time_str = f" · {dt.strftime('%H:%M')}"
            except:
                pass

        blocks.append(
            f"{emoji} **{article['title']}**\n"
            f"└ {article['source']}{time_str}"
        )

        if summary:
            blocks.append(f"  📝 {summary}")

        if context:
            blocks.append(f"  💡 {context}")

        blocks.append(f"  🔗 <{article['url']}>")

        # Save to DB
        await save_story(
            url=article["url"],
            title=article["title"],
            source=article["source"],
            summary=summary,
            context=context,
            published=article.get("published"),
        )

        return blocks

    def _header(self, articles: list) -> str:
        """Generate briefing header."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y년 %m월 %d일 (%A)")
        article_count = len(articles)

        lines = [
            f"🌅 **굿모닝! 오늘의 뉴스 브리핑**",
            f"   {date_str} · {article_count}개의 기사",
            "",
            f"   {'─' * 30}",
        ]
        return "\n".join(lines)

    def _footer(self) -> str:
        """Generate briefing footer."""
        return (
            "───\n"
            "💡 **명령어:** `/brief` 지금 브리핑 · `/track <주제>` 주제 추적\n"
            "🔧 `/source` 소스 관리 · `/schedule` 브리핑 시간 설정"
        )


def cluster_articles_by_topic(articles: list) -> dict:
    """Simple topic clustering based on keyword overlap."""
    from collections import defaultdict
    fetcher = NewsFetcher()
    clusters = defaultdict(list)

    for article in articles:
        keywords = set(fetcher.extract_keywords(article["title"], article.get("content", "")))
        assigned = False
        for topic in list(clusters.keys()):
            topic_keywords = set(topic.split())
            overlap = keywords & topic_keywords
            if len(overlap) >= 3:
                clusters[topic].append(article)
                assigned = True
                break
        if not assigned:
            top_kw = ", ".join(list(keywords)[:5])
            clusters[top_kw].append(article)

    return dict(clusters)

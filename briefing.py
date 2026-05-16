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
                "📭 **No news sources yet!**\n"
                "Use `/recommend` to subscribe to curated sources, or\n"
                "`/add <rss_url>` to add your own."
            )

        urls = [s["url"] for s in sources]
        articles = await self.fetcher.fetch_multiple(urls, max_per_feed=10)

        if not articles:
            return "📭 No fresh news today."

        articles = articles[:15]

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
        lines = ["📌 **Topic Briefing**\n"]

        for i, article in enumerate(articles[:8], 1):
            summary = None
            if article.get("content"):
                summary = await self.llm.summarize(
                    article["title"], article["content"][:2000], article["source"]
                )

            lines.append(
                f"**{i}. {article['title']}**\n"
                f"   Source: {article['source']}\n"
                f"   {summary or article.get('summary', '')[:200]}\n"
            )

        if len(articles) >= 2:
            tension = await self.llm.detect_tension(articles)
            if tension:
                lines.append(f"⚡ **Framing differences / contradictions:**\n{tension}\n")

        return "\n".join(lines)

    async def _build_article_block(self, article: dict, index: int) -> list:
        """Build a formatted article block."""
        blocks = []
        emoji = NARRATORS[index % len(NARRATORS)]

        summary = None
        context = None
        if article.get("content"):
            summary = await self.llm.summarize(
                article["title"], article["content"][:2000], article["source"]
            )
            if index < 5:
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
        date_str = now.strftime("%A, %B %d, %Y")
        article_count = len(articles)

        lines = [
            f"🌅 **Good morning! Your Daily Briefing**",
            f"   {date_str} · {article_count} articles",
            "",
            f"   {'─' * 30}",
        ]
        return "\n".join(lines)

    def _footer(self) -> str:
        """Generate briefing footer."""
        return (
            "───\n"
            "💡 **Commands:** `/brief` now · `/track <topic>` follow a story\n"
            "🔧 `/source` manage sources · `/schedule` set briefing time"
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

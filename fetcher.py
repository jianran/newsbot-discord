"""RSS feed fetcher and article parser."""

import re
import feedparser
import httpx
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from typing import Optional


class NewsFetcher:
    """Fetches and parses news from RSS feeds."""

    # Pre-curated recommended sources
    RECOMMENDED_SOURCES = {
        "global": [
            ("Reuters", "https://www.rss-bridge.org/bridge01/?action=display&bridge=FilterBridge&url=https%3A%2F%2Fwww.reuters.com%2F&content_filter=%5Cw&content_filter_type=text&title_filter=&title_filter_type=text&inverse=on&case_insensitive=on&fix_encoding=on&format=Atom"),
            ("AP News", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
            ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
            ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
            ("The Guardian", "https://www.theguardian.com/world/rss"),
            ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
        ],
        "geopolitics": [
            ("Foreign Policy", "https://foreignpolicy.com/feed/"),
            ("War on the Rocks", "https://warontherocks.com/feed/"),
            ("The Diplomat", "https://thediplomat.com/feed/"),
            ("Stratfor Worldview", "https://worldview.stratfor.com/rss.xml"),
        ],
        "asia": [
            ("NK News", "https://www.nknews.org/feed/"),
            ("Stimson Center", "https://www.stimson.org/feed/"),
            ("East Asia Forum", "https://eastasiaforum.org/feed/"),
            ("South China Morning Post", "https://www.scmp.com/rss/4/feed"),
        ],
        "tech_policy": [
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
            ("TechCrunch", "https://techcrunch.com/feed/"),
            ("The Verge", "https://www.theverge.com/rss/index.xml"),
            ("Wired", "https://www.wired.com/feed/rss"),
        ],
    }

    async def fetch_feed(self, url: str, max_items: int = 20) -> list:
        """Fetch and parse an RSS feed."""
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={
                    "User-Agent": "NewsBot/1.0 (news aggregator)",
                })
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)

                items = []
                for entry in feed.entries[:max_items]:
                    article_url = entry.get("link", "")

                    # Skip boilerplate
                    title = (entry.get("title") or "").strip()
                    if not title or len(title) < 10:
                        continue

                    published = entry.get("published_parsed")
                    pub_iso = (
                        datetime(*published[:6], tzinfo=timezone.utc).isoformat()
                        if published else None
                    )

                    items.append({
                        "title": title,
                        "url": article_url,
                        "source": feed.feed.get("title", url),
                        "published": pub_iso,
                        "summary": entry.get("summary", ""),
                        "content": self._clean_html(
                            entry.get("content", [{}])[0].get("value", "")
                            or entry.get("summary", "")
                        ),
                    })

                return items
        except Exception as e:
            print(f"Feed fetch error ({url}): {e}")
            return []

    async def fetch_multiple(self, urls: list, max_per_feed: int = 10) -> list:
        """Fetch multiple feeds and return deduplicated articles sorted by time."""
        all_items = []
        seen_urls = set()

        for url in urls:
            items = await self.fetch_feed(url, max_per_feed)
            for item in items:
                if item["url"] and item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    all_items.append(item)

        # Sort by published time (desc)
        all_items.sort(key=lambda x: x.get("published") or "", reverse=True)
        return all_items

    async def fetch_article_text(self, url: str) -> Optional[str]:
        """Fetch full article text from a URL."""
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)",
                })
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                # Remove scripts, styles, nav
                for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                    tag.decompose()
                text = soup.get_text(separator="\n")
                return self._clean_html(text)[:5000]
        except Exception as e:
            print(f"Article fetch error ({url}): {e}")
            return None

    def _clean_html(self, html: str) -> str:
        """Remove HTML tags and normalize whitespace."""
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def extract_keywords(self, title: str, text: str) -> list:
        """Simple keyword extraction for clustering."""
        words = re.findall(r"\b[a-zA-Z]{4,}\b", (title + " " + text[:1000]).lower())
        stopwords = {
            "this", "that", "with", "from", "have", "been", "will", "their",
            "what", "when", "where", "which", "about", "into", "would", "could",
            "after", "before", "between", "other", "there", "said", "also",
            "than", "very", "just", "more", "some", "these", "those",
        }
        return [w for w in words if w not in stopwords][:15]

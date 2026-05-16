"""
CLI to manage news sources from the terminal.
Use before running send.py for the first time.

Usage:
    python manage.py add <rss_url> [name]
    python manage.py list
    python manage.py remove <id>
    python manage.py recommend     # add all curated sources
    python manage.py recommend-global
    python manage.py recommend-geopolitics

Examples:
    python manage.py recommend-global
    python manage.py add https://feeds.bbci.co.uk/news/world/rss.xml BBC
    python manage.py list
"""

import os
import sys
import asyncio
from db import init_db, add_source, remove_source, get_sources
from fetcher import NewsFetcher

USER_ID = os.getenv("DISCORD_DM_USER_ID")
if not USER_ID:
    # Read from .env if available
    try:
        from dotenv import load_dotenv
        load_dotenv()
        USER_ID = os.getenv("DISCORD_DM_USER_ID")
    except:
        pass

if not USER_ID:
    print("❌ Set DISCORD_DM_USER_ID in .env or as environment variable.")
    sys.exit(1)

fetcher = NewsFetcher()


async def cmd_list():
    sources = await get_sources(USER_ID)
    if not sources:
        print("📭 No sources.")
        return
    print("\n📡 Sources:")
    for s in sources:
        print(f"  {s['id']:2d}. {s['name']} ({s['category']})")
        print(f"       {s['url']}")
    print(f"\nTotal: {len(sources)}")


async def cmd_add(url, name=None):
    items = await fetcher.fetch_feed(url, max_items=1)
    if not items:
        print("❌ Invalid RSS feed.")
        return
    feed_name = name or items[0].get("source", url.split("/")[2])
    await add_source(USER_ID, feed_name, url)
    print(f"✅ Added: {feed_name}")


async def cmd_remove(source_id):
    success = await remove_source(source_id, USER_ID)
    print("✅ Removed." if success else "❌ Not found.")


async def cmd_recommend(category=None):
    cats = fetcher.RECOMMENDED_SOURCES
    if category:
        sources = cats.get(category, [])
        for name, url in sources:
            await add_source(USER_ID, name, url)
        print(f"✅ Added {len(sources)} {category} sources.")
    else:
        for cat, sources in cats.items():
            for name, url in sources:
                await add_source(USER_ID, name, url)
        total = sum(len(s) for s in cats.values())
        print(f"✅ Added all {total} curated sources.")


async def main():
    await init_db()

    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "list":
        await cmd_list()
    elif cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: python manage.py add <url> [name]")
            return
        url = sys.argv[2]
        name = sys.argv[3] if len(sys.argv) > 3 else None
        await cmd_add(url, name)
    elif cmd == "remove":
        if len(sys.argv) < 3:
            print("Usage: python manage.py remove <id>")
            return
        await cmd_remove(int(sys.argv[2]))
    elif cmd == "recommend":
        await cmd_recommend()
    elif cmd == "recommend-global":
        await cmd_recommend("global")
    elif cmd == "recommend-geopolitics":
        await cmd_recommend("geopolitics")
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())

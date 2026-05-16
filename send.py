"""
One-shot news briefing sender.
Reads DISCORD_BOT_TOKEN + DISCORD_DM_USER_ID from .env, generates a briefing,
sends it as a DM, and exits.

Usage:
    python send.py
    # or set env vars manually:
    DISCORD_BOT_TOKEN=xxx DISCORD_DM_USER_ID=123 python send.py
"""

import os
import asyncio
import logging
from datetime import datetime, timezone

import discord
from dotenv import load_dotenv

from db import init_db, create_user, get_sources
from fetcher import NewsFetcher
from briefing import BriefingGenerator

load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("send_briefing")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USER_ID = os.getenv("DISCORD_DM_USER_ID")

if not TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN not set")
if not USER_ID:
    raise ValueError("DISCORD_DM_USER_ID not set")


class SendClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.fetcher = NewsFetcher()
        self.briefer = BriefingGenerator()

    async def on_ready(self):
        logger.info(f"Connected as {self.user}")

        try:
            user = await self.fetch_user(int(USER_ID))
            if not user:
                print(f"❌ Could not find user {USER_ID}")
                await self.close()
                return

            await init_db()
            await create_user(USER_ID)
            sources = await get_sources(USER_ID)

            if not sources:
                print(
                    "📭 No news sources configured. Add some first:\n"
                    "   python manage.py add <rss_url>\n"
                    "   or insert into the sources table directly."
                )
                await self.close()
                return

            print(f"📡 Fetching {len(sources)} sources...")
            briefing = await self.briefer.generate(USER_ID)

            print("📨 Sending DM...")
            # Discord 2000 char limit — chunk
            chunks = []
            text = briefing
            while len(text) > 1900:
                split_at = text.rfind("\n", 0, 1900)
                if split_at == -1:
                    split_at = 1900
                chunks.append(text[:split_at])
                text = text[split_at:].strip()
            if text:
                chunks.append(text)

            for chunk in chunks:
                await user.send(chunk)

            print(f"✅ Delivered {len(chunks)} message(s) to {user.name}")

        except Exception as e:
            print(f"❌ Error: {e}")
            logger.exception("Send failed")

        finally:
            await self.close()


if __name__ == "__main__":
    client = SendClient()
    asyncio.run(client.start(TOKEN))

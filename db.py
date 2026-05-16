"""SQLite database for user preferences, sources, and story tracking."""

import os
import json
import aiosqlite
from datetime import datetime, timezone
from typing import Optional


DB_PATH = os.path.join(os.path.dirname(__file__), "data", "newsbot.db")


async def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db():
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            timezone TEXT DEFAULT 'UTC',
            briefing_time TEXT DEFAULT '07:00',
            briefings_enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT NOT NULL,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            added_at TEXT NOT NULL,
            FOREIGN KEY (discord_id) REFERENCES users(discord_id)
        );

        CREATE TABLE IF NOT EXISTS stories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT,
            source_name TEXT,
            summary TEXT,
            context TEXT,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(url)
        );

        CREATE TABLE IF NOT EXISTS story_clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            story_urls TEXT NOT NULL,
            last_updated TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(discord_id, topic)
        );
    """)
    await db.commit()
    await db.close()


# --- Users ---
async def get_user(discord_id: str) -> Optional[dict]:
    db = await get_db()
    row = await db.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
    user = await row.fetchone()
    await db.close()
    return dict(user) if user else None


async def create_user(discord_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO users (discord_id, created_at) VALUES (?, ?)",
        (discord_id, now),
    )
    await db.commit()
    await db.close()
    return await get_user(discord_id)


async def update_user(discord_id: str, **kwargs):
    db = await get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [discord_id]
    await db.execute(f"UPDATE users SET {sets} WHERE discord_id = ?", vals)
    await db.commit()
    await db.close()


async def get_all_users():
    db = await get_db()
    rows = await db.execute("SELECT * FROM users WHERE briefings_enabled = 1")
    users = await rows.fetchall()
    await db.close()
    return [dict(u) for u in users]


# --- Sources ---
async def add_source(discord_id: str, name: str, url: str, category: str = "general"):
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    await db.execute(
        "INSERT INTO sources (discord_id, name, url, category, added_at) VALUES (?, ?, ?, ?, ?)",
        (discord_id, name, url, category, now),
    )
    await db.commit()
    await db.close()


async def remove_source(source_id: int, discord_id: str) -> bool:
    db = await get_db()
    cur = await db.execute(
        "DELETE FROM sources WHERE id = ? AND discord_id = ?", (source_id, discord_id)
    )
    await db.commit()
    deleted = cur.rowcount > 0
    await db.close()
    return deleted


async def get_sources(discord_id: str) -> list:
    db = await get_db()
    rows = await db.execute(
        "SELECT * FROM sources WHERE discord_id = ? ORDER BY added_at", (discord_id,)
    )
    sources = await rows.fetchall()
    await db.close()
    return [dict(s) for s in sources]


async def get_all_sources() -> list:
    db = await get_db()
    rows = await db.execute("SELECT * FROM sources ORDER BY discord_id")
    sources = await rows.fetchall()
    await db.close()
    return [dict(s) for s in sources]


# --- Stories ---
async def save_story(url: str, title: str, source: str, summary: str = None,
                     context: str = None, published: str = None) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO stories
               (url, title, source_name, summary, context, published_at, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (url, title, source, summary, context, published, now),
        )
        await db.commit()
        return True
    except Exception as e:
        print(f"Save story error: {e}")
        return False
    finally:
        await db.close()


async def get_recent_stories(limit: int = 50) -> list:
    db = await get_db()
    rows = await db.execute(
        "SELECT * FROM stories ORDER BY fetched_at DESC LIMIT ?", (limit,)
    )
    stories = await rows.fetchall()
    await db.close()
    return [dict(s) for s in stories]


# --- Story Clusters ---
async def get_cluster(topic: str) -> Optional[dict]:
    db = await get_db()
    row = await db.execute(
        "SELECT * FROM story_clusters WHERE topic = ?", (topic,)
    )
    cluster = await row.fetchone()
    await db.close()
    if cluster:
        c = dict(cluster)
        c["story_urls"] = json.loads(c["story_urls"])
        return c
    return None


async def upsert_cluster(topic: str, url: str):
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    existing = await db.execute(
        "SELECT * FROM story_clusters WHERE topic = ?", (topic,)
    )
    row = await existing.fetchone()
    if row:
        urls = json.loads(row["story_urls"])
        if url not in urls:
            urls.append(url)
        await db.execute(
            "UPDATE story_clusters SET story_urls = ?, last_updated = ? WHERE id = ?",
            (json.dumps(urls), now, row["id"]),
        )
    else:
        await db.execute(
            "INSERT INTO story_clusters (topic, story_urls, last_updated) VALUES (?, ?, ?)",
            (topic, json.dumps([url]), now),
        )
    await db.commit()
    await db.close()


# --- Tracked Topics ---
async def get_tracked_topics(discord_id: str) -> list:
    db = await get_db()
    rows = await db.execute(
        "SELECT * FROM user_tracks WHERE discord_id = ?", (discord_id,)
    )
    topics = await rows.fetchall()
    await db.close()
    return [dict(t) for t in topics]


async def add_track(discord_id: str, topic: str):
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO user_tracks (discord_id, topic, created_at) VALUES (?, ?, ?)",
        (discord_id, topic, now),
    )
    await db.commit()
    await db.close()


async def remove_track(discord_id: str, topic: str) -> bool:
    db = await get_db()
    cur = await db.execute(
        "DELETE FROM user_tracks WHERE discord_id = ? AND topic = ?",
        (discord_id, topic),
    )
    await db.commit()
    deleted = cur.rowcount > 0
    await db.close()
    return deleted

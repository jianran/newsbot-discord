# NewsBot — AI News Briefing for Discord

Your personal geopolitics news briefing bot. No algorithm, no infinite scroll — you control the sources, AI handles the noise.

## Features

- **📡 Your sources** — subscribe to any RSS feed, or pick from curated recommendations
- **🌅 Daily briefing** — delivered to your DM at your chosen time
- **📝 AI summaries** — 2-3 sentence summaries per article
- **💡 Context** — "why this matters" analysis for top stories
- **📌 Topic tracking** — follow stories over time (e.g., Ukraine, Taiwan)
- **📖 Read later** — paste any URL and get an AI summary

## Quick Start

```bash
# 1. Install
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: add your Discord bot token + LLM API key

# 3. Run
python bot.py
```

## Discord Bot Setup

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create an application → Bot → Copy token
3. Enable **Message Content Intent** under Bot settings
4. OAuth2 → URL Generator → `bot` + `applications.commands` → Invite to server

## Commands

| Command | Description |
|---|---|
| `/brief` | Generate briefing now |
| `/add <rss_url>` | Add RSS source |
| `/remove <id>` | Remove source |
| `/sources` | List your sources |
| `/recommend [category]` | Browse/subscribe curated sources |
| `/schedule <time>` | Set daily briefing time |
| `/track <topic>` | Track a story topic |
| `/read <url>` | AI-summarize an article |
| `/help` | All commands |

## Recommended Workflow

```
/recommend global    → Reuters, BBC, AP, Al Jazeera
/recommend geopolitics → Foreign Policy, CFR
/schedule 07:00      → Morning briefing at 7 AM
/track Ukraine       → Follow the story
```

## License

MIT

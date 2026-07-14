# WaterChugger Telegram Bot

WaterChugger is a privacy-first Telegram bot that reminds people to drink water once per hour while they are awake. It runs entirely in memory: there is no database, allowlist, password system, user history, analytics, or persistent tracking.

The bot retains a name, timezone, active reminder schedule, and handled reminder IDs only while the process is running. A restart or Railway redeployment clears everything.

This is a general wellness reminder, not medical advice. Hydration needs vary; anyone with a prescribed fluid restriction should follow their clinician's advice.

## Features

- Available to anyone through a private Telegram chat
- Asks for a preferred name and timezone
- Determines timezone from a shared location without retaining the coordinates
- Sends an immediate reminder after `/awake`, then one every 60 minutes
- **Drank it**, **Snooze 15 min**, and **Going to sleep** buttons
- Stops reminders with `/sleep` or automatically after 18 hours
- Stores no hydration totals or history
- Clears all temporary user state on restart
- Ready for single-replica Railway deployment

## Local setup

Python 3.12 is recommended.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Create a bot through [@BotFather](https://t.me/BotFather), then put its token in `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=replace_with_your_bot_token
REMINDER_INTERVAL_MINUTES=60
SNOOZE_MINUTES=15
MAX_AWAKE_HOURS=18
SCHEDULER_INTERVAL_SECONDS=15
LOG_LEVEL=INFO
```

Start the bot:

```bash
python main.py
```

## Commands

- `/start` — enter a temporary name and timezone
- `/awake` — start hourly reminders
- `/sleep` — stop reminders
- `/status` — show whether reminders are active and the next reminder time
- `/settings` — show temporary settings
- `/name New Name` — change the temporary preferred name
- `/timezone Asia/Singapore` — change the temporary IANA timezone
- `/forget_me` — immediately clear the user's temporary state
- `/cancel` — cancel the current input step
- `/help` — show command help

Tapping **Drank it** only dismisses that reminder. The acknowledgement is not counted or added to any history. **Snooze 15 min** moves the next reminder to 15 minutes later; the following hourly interval starts from that snoozed delivery.

## Deploy to Railway

1. Push the project to GitHub and create a Railway project from the repository.
2. Do not add PostgreSQL or any other database service.
3. Add the variables from `.env.example` to the service's **Variables** tab.
4. Set the real `TELEGRAM_BOT_TOKEN` value.
5. Deploy. `railway.toml` runs `python main.py`.
6. Keep exactly one replica because Telegram long polling cannot use multiple instances with the same bot token.

When Railway restarts or redeploys the service, every user must run `/start` and `/awake` again. This is intentional for the first iteration and ensures that no user profiles or drinking habits are retained.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Suggested deployment smoke test:

1. Complete `/start` and confirm `/settings` says storage is memory-only.
2. Send `/awake` and check that an immediate reminder arrives.
3. Test **Drank it** and confirm no count is shown.
4. Test **Snooze 15 min**, then `/sleep`.
5. Restart the Railway service and confirm `/status` requires onboarding again.

## Data handling

There are no database or filesystem writes for user data. Temporary state is held in the Python process so the bot can address the user, calculate the next reminder, prevent duplicate button handling, and stop the current session. Shared coordinates are used only to calculate an IANA timezone and are discarded immediately. Telegram itself still processes and retains messages according to Telegram's own policies.

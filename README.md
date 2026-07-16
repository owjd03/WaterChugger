# WaterChugger Telegram Bot

WaterChugger is a fun Python Telegram bot that sends hourly water reminders while a user is awake and switches to 15-minute, workout-themed reminders in Pump Mode. It stores a minimal PostgreSQL profile keyed by the user's numeric Telegram ID so onboarding and active schedules survive restarts.

Only the latest confirmed drink time is retained. The bot does not store message contents, phone numbers, Telegram usernames, raw location coordinates, or historical drink events. A complete user row is automatically deleted after 24 hours without user interaction.

This is a general wellness reminder, not medical advice. Anyone with a prescribed fluid restriction should follow their clinician's advice.

## What is stored

Each user row contains an increasing internal database ID, Telegram numeric user ID, private chat ID, entered name, timezone, onboarding state, last activity time, latest drink time, awake/workout state, and active reminder schedule. Timestamps are stored as timezone-aware instants and displayed in Singapore time. Workout history is not retained.

Any command, message, location share, or button press updates `last_activity_at`. Bot-generated reminders do not count as user activity. After 24 hours without input, the row and schedule are deleted and `/start` onboarding is required again.

## Requirements

- Docker Desktop or another Docker Engine with Docker Compose
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

Python and PostgreSQL do not need to be installed on the host.

## Start locally with Docker

Create the local environment file:

```bash
cp .env.example .env
```

Edit `.env` and replace the Telegram token placeholder:

```dotenv
TELEGRAM_BOT_TOKEN=your_real_botfather_token

POSTGRES_USER=waterchugger
POSTGRES_PASSWORD=localpassword
POSTGRES_DB=waterchugger

REMINDER_INTERVAL_MINUTES=60
WORKOUT_REMINDER_INTERVAL_MINUTES=15
SNOOZE_MINUTES=15
MAX_AWAKE_HOURS=18
IDLE_EXPIRY_HOURS=24
CLEANUP_INTERVAL_SECONDS=300
SCHEDULER_INTERVAL_SECONDS=15
LOG_LEVEL=INFO
```

Build and start Python and PostgreSQL together:

```bash
docker compose up --build
```

The Compose service automatically supplies this internal connection URL to the bot:

```text
postgresql+asyncpg://waterchugger:localpassword@db:5432/waterchugger
```

The `db` hostname works inside Docker. If connecting from a host application instead, use `localhost`, but the supported development workflow runs Python inside Docker.

Useful commands:

```bash
docker compose logs -f bot
docker compose down
docker compose up --build
```

`docker compose down` retains the named PostgreSQL volume. The following command is destructive and permanently deletes the local database:

```bash
docker compose down -v
```

## Run tests in Docker

The test service starts a separate temporary PostgreSQL 16 database, applies migrations, and runs the suite:

```bash
docker compose run --rm test
```

The test database does not use the development database volume.

## Commands

- `/start` — create or resume onboarding
- `/awake` — start hourly reminders
- `/workout` — enter Pump Mode with 15-minute reminders
- `/end_workout` — leave Pump Mode and return to hourly reminders
- `/sleep` — stop reminders after ending any active workout
- `/status` — show the schedule and latest drink time in Singapore time
- `/settings` — show the database ID and saved settings
- `/name New Name` — change the saved name
- `/timezone Asia/Singapore` — change the saved IANA timezone
- `/forget_me` — immediately delete the profile and schedule
- `/cancel` — cancel the current input step
- `/help` — show command help

The bottom keyboard adapts to the current mode: **I'm awake** while sleeping, **Pump Mode / I'm going to sleep** while awake, and **End Workout** during a workout. Workout reminders keep **Drank it** and **Snooze 15 min**, with **End Workout** replacing the sleep action.

**Drank it** records only the latest confirmation timestamp. **Snooze 15 min** persists the delayed reminder. Active schedules and workout mode resume after restarts and deployments.

## Customize the fun messages

Edit `waterbot/messages.py` to change the hardcoded normal encouragements, workout reminder prompts, and workout drink confirmations. Keep each message quoted and comma-separated inside its tuple. Message edits require rebuilding or redeploying the bot; reminder timings remain in `.env` locally and Railway Variables in production.

## Inspect the local database

Open a PostgreSQL shell inside the database container:

```bash
docker compose exec db psql -U waterchugger -d waterchugger
```

Useful read-only queries:

```sql
SELECT id, telegram_user_id, name, is_awake, is_working_out,
       last_activity_at AT TIME ZONE 'Asia/Singapore' AS last_activity_sgt,
       last_drank_at AT TIME ZONE 'Asia/Singapore' AS last_drank_sgt
FROM users
ORDER BY id;
```

Exit with `\q`.

## Database migrations

Alembic migrations run automatically before the bot starts in Docker Compose and before Railway deploys the new version.

To run them manually inside the bot image:

```bash
docker compose run --rm bot alembic upgrade head
```

Running `alembic upgrade head` repeatedly is safe; already-applied migrations are not rerun.

## Upgrade the existing Railway deployment

Use the existing Railway project and existing bot service. Do not create a
second bot service with the same Telegram token.

1. Commit these changes and push them to the GitHub branch already connected
   to the Railway bot service.
2. Open the existing Railway project. From its project canvas, select **+ New**
   and add a **PostgreSQL** database service.
3. Open the existing bot service's **Variables** tab. Keep its current
   `TELEGRAM_BOT_TOKEN`, add the PostgreSQL reference, and add or update the
   timing variables:

```dotenv
TELEGRAM_BOT_TOKEN=your_real_botfather_token
DATABASE_URL=${{Postgres.DATABASE_URL}}
REMINDER_INTERVAL_MINUTES=60
WORKOUT_REMINDER_INTERVAL_MINUTES=15
SNOOZE_MINUTES=15
MAX_AWAKE_HOURS=18
IDLE_EXPIRY_HOURS=24
CLEANUP_INTERVAL_SECONDS=300
SCHEDULER_INTERVAL_SECONDS=15
LOG_LEVEL=INFO
```

If the database service is not named `Postgres`, replace `Postgres` in
`${{Postgres.DATABASE_URL}}` with the exact Railway service name. The bot does
not need a public database URL or database port.

4. Deploy the existing bot service. A push to its connected GitHub branch will
   normally trigger this automatically; otherwise choose **Redeploy** from the
   bot service.
5. Confirm the bot service has exactly one replica and stop any local copy using
   the same Telegram token.

Railway uses the repository `Dockerfile`. The pre-deploy command in `railway.toml` runs `alembic upgrade head`, and the image starts with `python main.py`.

The workout migration only adds `is_working_out` with a default of `false` and a state-safety constraint. It does not delete or recreate the `users` table, so existing IDs, profiles, latest drink times, awake states, and reminder schedules remain intact. Existing users begin in normal hourly mode after the migration and do not need to repeat `/start`.

Keep exactly one bot replica. Telegram long polling must not run from multiple instances with the same token.

### One-time effect on current users

The previous release stored users and schedules only in the Python process's
memory. That memory cannot be copied into PostgreSQL during deployment. When
this upgrade restarts the bot, existing users keep the same Telegram bot chat
but must send `/start` and complete their name and timezone once more. Existing
hourly schedules will not resume until they do so and send `/awake`.

After that one-time onboarding, profiles and active schedules survive normal
Railway deployments because they are stored in PostgreSQL. A user must onboard
again only after `/forget_me`, database loss, or 24 hours without interacting
with the bot.

## Railway verification

1. Check the existing bot service's deployment logs for a successful Alembic
   migration and bot startup.
2. Complete `/start`, send `/awake`, and confirm a reminder.
3. Enter Pump Mode and verify an immediate workout reminder followed by a 15-minute schedule.
4. End the workout and verify an immediate normal reminder followed by an hourly schedule.
5. Check `/status` for the mode and latest drink timestamp.
6. Redeploy during Pump Mode and verify that the mode and schedule recover.
7. Use `/forget_me` and confirm `/status` requires `/start` again.

For a quick expiry test in a non-production environment, temporarily reduce `IDLE_EXPIRY_HOURS`, wait for the cleanup job, and confirm that the row is removed. Restore it to `24` afterward.

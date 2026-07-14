from __future__ import annotations

import html
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from timezonefinder import TimezoneFinder

from waterbot.config import Config, ConfigError
from waterbot.models import User
from waterbot.repository import UserRepository

LOGGER = logging.getLogger(__name__)
TIMEZONE_FINDER = TimezoneFinder(in_memory=True)
SINGAPORE = ZoneInfo("Asia/Singapore")

AWAKE_TEXT = "☀️ I'm awake"
SLEEP_TEXT = "😴 I'm going to sleep"


def utcnow() -> datetime:
    return datetime.now(UTC)


def format_singapore(value: datetime | None) -> str:
    if value is None:
        return "Never"
    return value.astimezone(SINGAPORE).strftime("%d %b %Y, %H:%M SGT")


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(AWAKE_TEXT), KeyboardButton(SLEEP_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Share my location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def reminder_keyboard(token: str, snooze_minutes: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💧 Drank it", callback_data=f"drink:{token}"),
                InlineKeyboardButton(
                    f"⏰ Snooze {snooze_minutes} min",
                    callback_data=f"snooze:{token}",
                ),
            ],
            [InlineKeyboardButton("😴 Going to sleep", callback_data="sleep")],
        ]
    )


def validate_name(raw: str) -> str | None:
    name = " ".join(raw.strip().split())
    if not 1 <= len(name) <= 50 or not name.isprintable():
        return None
    return name


def validate_timezone(raw: str) -> str | None:
    timezone_name = raw.strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return None
    return timezone_name


class ReminderService:
    def __init__(
        self, application: Application, config: Config, repository: UserRepository
    ) -> None:
        self.application = application
        self.config = config
        self.repository = repository

    @property
    def idle_threshold(self) -> datetime:
        return utcnow() - timedelta(hours=self.config.idle_expiry_hours)

    async def tick(self, _context: ContextTypes.DEFAULT_TYPE | None = None) -> None:
        now = utcnow()
        await self.repository.expire_sessions(now)
        reminders = await self.repository.claim_due(
            now,
            self.config.reminder_interval_minutes,
            now - timedelta(hours=self.config.idle_expiry_hours),
        )
        for reminder in reminders:
            try:
                await self.application.bot.send_message(
                    chat_id=reminder.chat_id,
                    text=(
                        f"💧 <b>{html.escape(reminder.name)}</b>, "
                        "it’s time to drink some water."
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reminder_keyboard(
                        reminder.token, self.config.snooze_minutes
                    ),
                )
            except Exception:
                LOGGER.exception(
                    "Could not deliver reminder to Telegram user %s",
                    reminder.telegram_user_id,
                )
                await self.repository.retry_delivery(
                    reminder.user_id,
                    reminder.token,
                    utcnow() + timedelta(minutes=1),
                )

    async def cleanup(self, _context: ContextTypes.DEFAULT_TYPE | None = None) -> None:
        deleted = await self.repository.delete_expired(self.idle_threshold)
        if deleted:
            LOGGER.info("Deleted %s user row(s) after inactivity", deleted)


def components(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[Config, UserRepository, ReminderService]:
    return (
        context.application.bot_data["config"],
        context.application.bot_data["repository"],
        context.application.bot_data["reminders"],
    )


def idle_threshold(config: Config, now: datetime) -> datetime:
    return now - timedelta(hours=config.idle_expiry_hours)


async def private_only(update: Update) -> bool:
    chat = update.effective_chat
    if chat and chat.type == ChatType.PRIVATE:
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Please use this bot in a private chat.")
    return False


async def touch_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> User | None:
    if not update.effective_user or not update.effective_chat:
        return None
    config, repository, _ = components(context)
    now = utcnow()
    return await repository.touch(
        update.effective_user.id,
        update.effective_chat.id,
        now,
        idle_threshold(config, now),
    )


async def require_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> User | None:
    user = await touch_user(update, context)
    if user is None and update.effective_message:
        await update.effective_message.reply_text(
            "Your session is missing or expired. Send /start to set up again.",
            reply_markup=ReplyKeyboardRemove(),
        )
    return user


async def ask_for_timezone(update: Update, name: str) -> None:
    await update.effective_message.reply_text(
        f"Nice to meet you, {name}. Share your location so I can determine your timezone. "
        "The coordinates are not saved. If location sharing does not work, send:\n\n"
        "/timezone Asia/Singapore",
        reply_markup=location_keyboard(),
    )


async def finish_onboarding(update: Update, user: User) -> None:
    await update.effective_message.reply_text(
        f"All set, {user.name}! Use /awake when you wake up. Your profile and active "
        "reminders will survive restarts, but your profile is deleted after 24 hours "
        "without interaction.\n\nThis is a general wellness reminder, not medical advice.",
        reply_markup=main_keyboard(),
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user or not update.effective_chat:
        return
    config, repository, _ = components(context)
    now = utcnow()
    user, created = await repository.create_or_touch(
        update.effective_user.id,
        update.effective_chat.id,
        now,
        idle_threshold(config, now),
    )
    if not created and user.name and user.onboarding_step == "none":
        await update.effective_message.reply_text(
            f"Welcome back, {user.name}! Use /awake when your day starts.",
            reply_markup=main_keyboard(),
        )
        return
    if user.name and user.onboarding_step == "timezone":
        await ask_for_timezone(update, user.name)
        return
    await repository.set_onboarding_step(user.telegram_user_id, "name", now)
    await update.effective_message.reply_text(
        "Hi! What name should I use when reminding you?",
        reply_markup=ReplyKeyboardRemove(),
    )


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    text = update.effective_message.text or ""
    if text == AWAKE_TEXT:
        await awake_command(update, context)
        return
    if text == SLEEP_TEXT:
        await sleep_command(update, context)
        return

    user = await require_user(update, context)
    if user is None:
        return
    _, repository, _ = components(context)
    if user.onboarding_step in ("name", "name_update"):
        name = validate_name(text)
        if not name:
            await update.effective_message.reply_text(
                "Please enter a printable name from 1–50 characters."
            )
            return
        updated = await repository.set_name(user.telegram_user_id, name, utcnow())
        if updated and updated.onboarding_step == "none":
            await update.effective_message.reply_text(
                f"I’ll call you {name}.", reply_markup=main_keyboard()
            )
        else:
            await ask_for_timezone(update, name)
        return
    await update.effective_message.reply_text(
        "I didn’t understand that. Use /help to see the available commands.",
        reply_markup=main_keyboard(),
    )


async def location_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    user = await require_user(update, context)
    if user is None:
        return
    location = update.effective_message.location
    timezone_name = TIMEZONE_FINDER.timezone_at(
        lat=location.latitude, lng=location.longitude
    )
    if not timezone_name:
        await update.effective_message.reply_text(
            "I couldn’t determine that timezone. Send:\n\n/timezone Asia/Singapore"
        )
        return
    was_update = user.onboarding_step == "timezone_update"
    _, repository, _ = components(context)
    updated = await repository.set_timezone(user.telegram_user_id, timezone_name, utcnow())
    if updated and updated.name and was_update:
        await update.effective_message.reply_text(
            f"Timezone updated to {timezone_name}.", reply_markup=main_keyboard()
        )
    elif updated and updated.name:
        await finish_onboarding(update, updated)
    else:
        await repository.set_onboarding_step(user.telegram_user_id, "name", utcnow())
        await update.effective_message.reply_text("What name should I use when reminding you?")


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    user = await require_user(update, context)
    if user is None:
        return
    _, repository, _ = components(context)
    if not context.args:
        step = (
            "timezone_update"
            if user.name and user.onboarding_step == "none"
            else "timezone"
        )
        await repository.set_onboarding_step(user.telegram_user_id, step, utcnow())
        await update.effective_message.reply_text(
            "Send your timezone like this:\n\n/timezone Asia/Singapore\n\n"
            "Or use the button to share your location.",
            reply_markup=location_keyboard(),
        )
        return
    timezone_name = validate_timezone(" ".join(context.args))
    if not timezone_name:
        await update.effective_message.reply_text(
            "That timezone is invalid. Try an IANA name such as Asia/Singapore."
        )
        return
    was_update = user.onboarding_step in ("none", "timezone_update")
    updated = await repository.set_timezone(user.telegram_user_id, timezone_name, utcnow())
    if updated and updated.name and was_update:
        await update.effective_message.reply_text(
            f"Timezone updated to {timezone_name}.", reply_markup=main_keyboard()
        )
    elif updated and updated.name:
        await finish_onboarding(update, updated)


async def awake_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    user = await require_user(update, context)
    if user is None:
        return
    if not user.name or user.onboarding_step != "none":
        await update.effective_message.reply_text("Please complete /start first.")
        return
    config, repository, reminders = components(context)
    _, started = await repository.start_day(
        user.telegram_user_id, utcnow(), config.max_awake_hours
    )
    if started:
        await reminders.tick()
        text = "Your day has started. I’ll remind you to drink water every hour."
    else:
        text = "Your reminders are already running."
    await update.effective_message.reply_text(text, reply_markup=main_keyboard())


async def sleep_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    user = await require_user(update, context)
    if user is None:
        return
    _, repository, _ = components(context)
    stopped = await repository.stop_day(user.telegram_user_id, utcnow())
    await update.effective_message.reply_text(
        "Sleep well! Water reminders are stopped."
        if stopped
        else "No active reminder session was found.",
        reply_markup=main_keyboard(),
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update):
        return
    user = await require_user(update, context)
    if user is None:
        return
    status = "running" if user.is_awake else "stopped"
    lines = [
        f"Reminders: {status}",
        f"Last drink: {format_singapore(user.last_drank_at)}",
        f"Last activity: {format_singapore(user.last_activity_at)}",
    ]
    if user.is_awake and user.next_reminder_at:
        lines.insert(1, f"Next reminder: {format_singapore(user.next_reminder_at)}")
    await update.effective_message.reply_text("\n".join(lines))


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update):
        return
    user = await require_user(update, context)
    if user is None:
        return
    config, _, _ = components(context)
    await update.effective_message.reply_text(
        f"Database ID: {user.id}\nName: {user.name}\nTimezone: {user.timezone}\n"
        f"Interval: {config.reminder_interval_minutes} minutes\n"
        f"Snooze: {config.snooze_minutes} minutes\n"
        f"Inactive profiles are deleted after {config.idle_expiry_hours} hours.\n\n"
        "Change your details with /name New Name or /timezone Area/City."
    )


async def name_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    user = await require_user(update, context)
    if user is None:
        return
    _, repository, _ = components(context)
    if context.args:
        name = validate_name(" ".join(context.args))
        if not name:
            await update.effective_message.reply_text(
                "Please use a printable name from 1–50 characters."
            )
            return
        await repository.set_onboarding_step(user.telegram_user_id, "name_update", utcnow())
        await repository.set_name(user.telegram_user_id, name, utcnow())
        await update.effective_message.reply_text(f"I’ll call you {name}.")
    else:
        await repository.set_onboarding_step(user.telegram_user_id, "name_update", utcnow())
        await update.effective_message.reply_text("What name should I use?")


async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    _, repository, _ = components(context)
    deleted = await repository.delete_user(update.effective_user.id)
    await update.effective_message.reply_text(
        "Your saved profile and reminder schedule were deleted. Use /start to begin again."
        if deleted
        else "No saved profile was found.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    user = await require_user(update, context)
    if user is None:
        return
    _, repository, _ = components(context)
    if user.onboarding_step in ("name_update", "timezone_update"):
        next_step = "none"
    else:
        next_step = "timezone" if user.name else "name"
    await repository.set_onboarding_step(user.telegram_user_id, next_step, utcnow())
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update):
        return
    await touch_user(update, context)
    await update.effective_message.reply_text(
        "/start – set up the bot\n/awake – start hourly reminders\n"
        "/sleep – stop reminders\n/status – show reminder and drink status\n"
        "/settings – view saved settings\n/name – change your name\n"
        "/timezone – change timezone\n/forget_me – delete your saved profile\n"
        "/cancel – cancel input\n/help – show this help\n\n"
        "Only your latest drink time is retained. Hydration needs vary; follow medical "
        "advice if you have a fluid restriction."
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if (
        not query
        or not update.effective_user
        or not update.effective_chat
        or update.effective_chat.type != ChatType.PRIVATE
    ):
        return
    user = await touch_user(update, context)
    if user is None:
        await query.answer("Your session expired. Send /start again.", show_alert=True)
        return
    config, repository, _ = components(context)
    data = query.data or ""
    if data == "sleep":
        stopped = await repository.stop_day(user.telegram_user_id, utcnow())
        await query.answer()
        await query.edit_message_text(
            "Sleep well! Reminders are stopped."
            if stopped
            else "No active session was found."
        )
        return
    if data.startswith("drink:"):
        changed = await repository.confirm_drink(
            user.telegram_user_id, data.removeprefix("drink:"), utcnow()
        )
        if changed:
            await query.answer()
            await query.edit_message_text(
                f"Nice work! Last drink: {format_singapore(utcnow())}."
            )
        else:
            await query.answer(
                "This reminder was already handled or is no longer yours.",
                show_alert=True,
            )
        return
    if data.startswith("snooze:"):
        changed = await repository.snooze(
            user.telegram_user_id,
            data.removeprefix("snooze:"),
            utcnow(),
            config.snooze_minutes,
        )
        if changed:
            await query.answer()
            await query.edit_message_text(
                f"Snoozed. I’ll remind you again in {config.snooze_minutes} minutes."
            )
        else:
            await query.answer(
                "This reminder can no longer be snoozed.", show_alert=True
            )
        return
    await query.answer("Unknown action.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.error("Unhandled bot error", exc_info=context.error)


async def post_init(application: Application) -> None:
    config: Config = application.bot_data["config"]
    repository: UserRepository = application.bot_data["repository"]
    reminders: ReminderService = application.bot_data["reminders"]
    await repository.ping()
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Set up the bot"),
            BotCommand("awake", "Start hourly reminders"),
            BotCommand("sleep", "Stop reminders"),
            BotCommand("status", "Show reminder and drink status"),
            BotCommand("settings", "View saved settings"),
            BotCommand("forget_me", "Delete saved profile"),
            BotCommand("help", "Show help"),
        ]
    )
    application.job_queue.run_repeating(
        reminders.tick,
        interval=config.scheduler_interval_seconds,
        first=1,
        name="reminder-scheduler",
    )
    application.job_queue.run_repeating(
        reminders.cleanup,
        interval=config.cleanup_interval_seconds,
        first=5,
        name="expired-user-cleanup",
    )


async def post_shutdown(application: Application) -> None:
    repository: UserRepository = application.bot_data["repository"]
    await repository.close()


def build_application(config: Config) -> Application:
    application = (
        ApplicationBuilder()
        .token(config.telegram_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    repository = UserRepository(config.database_url)
    application.bot_data["config"] = config
    application.bot_data["repository"] = repository
    application.bot_data["reminders"] = ReminderService(
        application, config, repository
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("awake", awake_command))
    application.add_handler(CommandHandler("sleep", sleep_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("name", name_command))
    application.add_handler(CommandHandler("timezone", timezone_command))
    application.add_handler(CommandHandler("forget_me", forget_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.LOCATION, location_message))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message)
    )
    application.add_error_handler(error_handler)
    return application


def run() -> None:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    build_application(config).run_polling(
        allowed_updates=Update.ALL_TYPES, drop_pending_updates=False
    )

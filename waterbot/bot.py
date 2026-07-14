from __future__ import annotations

import html
import logging
from datetime import UTC, datetime
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
from waterbot.state import GuestSession, Profile, RuntimeState, Step

LOGGER = logging.getLogger(__name__)
TIMEZONE_FINDER = TimezoneFinder(in_memory=True)

AWAKE_TEXT = "☀️ I'm awake"
SLEEP_TEXT = "😴 I'm going to sleep"


def utcnow() -> datetime:
    return datetime.now(UTC)


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


def reminder_keyboard(reminder_id: str, snooze_minutes: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💧 Drank it", callback_data=f"drink:{reminder_id}"),
                InlineKeyboardButton(
                    f"⏰ Snooze {snooze_minutes} min",
                    callback_data=f"snooze:{reminder_id}",
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
    def __init__(self, application: Application, config: Config, state: RuntimeState) -> None:
        self.application = application
        self.config = config
        self.state = state

    async def start_day(self, user_id: int) -> str:
        current = self.state.guest_sessions.get(user_id)
        if current and current.active:
            return "Your reminders are already running."
        self.state.guest_sessions[user_id] = GuestSession.start(
            utcnow(), self.config.max_awake_hours
        )
        await self.tick()
        return "Your day has started. I’ll remind you to drink water every hour."

    def stop_day(self, user_id: int) -> bool:
        session = self.state.guest_sessions.get(user_id)
        return bool(session and session.stop())

    async def tick(self, _context: ContextTypes.DEFAULT_TYPE | None = None) -> None:
        now = utcnow()
        for user_id, session in list(self.state.guest_sessions.items()):
            if now >= session.stop_at:
                session.active = False
            reminder = session.claim_due(now, self.config.reminder_interval_minutes)
            if reminder is None:
                continue
            profile = self.state.profiles.get(user_id)
            if profile is None:
                session.active = False
                continue
            try:
                await self.application.bot.send_message(
                    chat_id=profile.chat_id,
                    text=f"💧 <b>{html.escape(profile.name or 'Friend')}</b>, it’s time to drink some water.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=reminder_keyboard(reminder.id, self.config.snooze_minutes),
                )
            except Exception:
                LOGGER.exception("Could not deliver reminder to Telegram user %s", user_id)

    def confirm(self, user_id: int, reminder_id: str) -> bool:
        session = self.state.guest_sessions.get(user_id)
        return bool(session and session.confirm(reminder_id))

    def snooze(self, user_id: int, reminder_id: str) -> bool:
        session = self.state.guest_sessions.get(user_id)
        return bool(
            session
            and session.snooze(
                reminder_id, utcnow(), self.config.snooze_minutes
            )
        )


def components(context: ContextTypes.DEFAULT_TYPE) -> tuple[Config, RuntimeState, ReminderService]:
    return (
        context.application.bot_data["config"],
        context.application.bot_data["state"],
        context.application.bot_data["reminders"],
    )


async def private_only(update: Update) -> bool:
    chat = update.effective_chat
    if chat and chat.type == ChatType.PRIVATE:
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Please use this bot in a private chat.")
    return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user or not update.effective_chat:
        return
    _, state, _ = components(context)
    profile = state.profile(update.effective_user.id, update.effective_chat.id)
    if profile.complete:
        await update.effective_message.reply_text(
            f"Welcome back, {profile.name}! Use /awake when your day starts.",
            reply_markup=main_keyboard(),
        )
        return
    profile.step = Step.NAME
    await update.effective_message.reply_text(
        "Hi! What name should I use when reminding you?",
        reply_markup=ReplyKeyboardRemove(),
    )


async def finish_onboarding(update: Update, profile: Profile) -> None:
    profile.step = Step.NONE
    await update.effective_message.reply_text(
        f"All set, {profile.name}! Use /awake when you wake up. Your details and reminder "
        "session exist only in memory and disappear whenever the bot restarts.\n\n"
        "This is a general wellness reminder, not medical advice.",
        reply_markup=main_keyboard(),
    )


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user or not update.effective_chat:
        return
    text = update.effective_message.text or ""
    if text == AWAKE_TEXT:
        await awake_command(update, context)
        return
    if text == SLEEP_TEXT:
        await sleep_command(update, context)
        return

    _, state, _ = components(context)
    profile = state.profile(update.effective_user.id, update.effective_chat.id)
    if profile.step in (Step.NAME, Step.NAME_UPDATE):
        name = validate_name(text)
        if not name:
            await update.effective_message.reply_text(
                "Please enter a printable name from 1–50 characters."
            )
            return
        updating = profile.step == Step.NAME_UPDATE
        profile.name = name
        if updating and profile.timezone:
            profile.step = Step.NONE
            await update.effective_message.reply_text(
                f"I’ll call you {name}.", reply_markup=main_keyboard()
            )
            return
        profile.step = Step.TIMEZONE
        await update.effective_message.reply_text(
            f"Nice to meet you, {name}. Share your location so I can determine your timezone. "
            "The coordinates are not saved. If location sharing does not work, send:\n\n"
            "/timezone Asia/Singapore",
            reply_markup=location_keyboard(),
        )
        return

    await update.effective_message.reply_text(
        "I didn’t understand that. Use /help to see the available commands.",
        reply_markup=main_keyboard(),
    )


async def location_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user or not update.effective_chat:
        return
    _, state, _ = components(context)
    profile = state.profile(update.effective_user.id, update.effective_chat.id)
    location = update.effective_message.location
    timezone_name = TIMEZONE_FINDER.timezone_at(
        lat=location.latitude, lng=location.longitude
    )
    if not timezone_name:
        await update.effective_message.reply_text(
            "I couldn’t determine that timezone. Send:\n\n/timezone Asia/Singapore"
        )
        return
    profile.timezone = timezone_name
    if profile.name:
        await finish_onboarding(update, profile)
    else:
        await update.effective_message.reply_text(
            f"Timezone updated to {timezone_name}.", reply_markup=main_keyboard()
        )


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user or not update.effective_chat:
        return
    _, state, _ = components(context)
    profile = state.profile(update.effective_user.id, update.effective_chat.id)
    if not context.args:
        profile.step = Step.TIMEZONE
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
    profile.timezone = timezone_name
    if profile.name and profile.step == Step.TIMEZONE:
        await finish_onboarding(update, profile)
    else:
        profile.step = Step.NONE
        await update.effective_message.reply_text(
            f"Timezone updated to {timezone_name}.", reply_markup=main_keyboard()
        )


async def awake_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user or not update.effective_chat:
        return
    _, state, reminders = components(context)
    profile = state.profile(update.effective_user.id, update.effective_chat.id)
    if not profile.complete:
        await update.effective_message.reply_text("Please complete /start first.")
        return
    result = await reminders.start_day(profile.user_id)
    await update.effective_message.reply_text(result, reply_markup=main_keyboard())


async def sleep_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    _, _, reminders = components(context)
    stopped = reminders.stop_day(update.effective_user.id)
    await update.effective_message.reply_text(
        "Sleep well! Water reminders are stopped."
        if stopped
        else "No active reminder session was found.",
        reply_markup=main_keyboard(),
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    _, state, _ = components(context)
    profile = state.profiles.get(update.effective_user.id)
    session = state.guest_sessions.get(update.effective_user.id)
    if not profile or not profile.complete:
        await update.effective_message.reply_text("Complete /start first.")
        return
    if not session or not session.active:
        await update.effective_message.reply_text(
            "Reminders are stopped. No hydration history is recorded."
        )
        return
    next_due = session.next_due_at.astimezone(ZoneInfo(profile.timezone or "UTC"))
    await update.effective_message.reply_text(
        f"Reminders are running. Next reminder: {next_due.strftime('%H:%M %Z')}.\n"
        "No hydration history is recorded."
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    config, state, _ = components(context)
    profile = state.profiles.get(update.effective_user.id)
    if not profile or not profile.complete:
        await update.effective_message.reply_text("Complete /start first.")
        return
    await update.effective_message.reply_text(
        f"Name: {profile.name}\nTimezone: {profile.timezone}\n"
        f"Interval: {config.reminder_interval_minutes} minutes\n"
        f"Snooze: {config.snooze_minutes} minutes\n"
        "Storage: memory only; nothing is retained after a restart.\n\n"
        "Change your details with /name New Name or /timezone Area/City."
    )


async def name_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user or not update.effective_chat:
        return
    _, state, _ = components(context)
    profile = state.profile(update.effective_user.id, update.effective_chat.id)
    if context.args:
        name = validate_name(" ".join(context.args))
        if not name:
            await update.effective_message.reply_text(
                "Please use a printable name from 1–50 characters."
            )
            return
        profile.name = name
        await update.effective_message.reply_text(f"I’ll call you {name}.")
    else:
        profile.step = Step.NAME_UPDATE
        await update.effective_message.reply_text("What name should I use?")


async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user:
        return
    _, state, _ = components(context)
    user_id = update.effective_user.id
    state.guest_sessions.pop(user_id, None)
    state.profiles.pop(user_id, None)
    await update.effective_message.reply_text(
        "Your temporary name, timezone, and reminder session have been cleared. Use /start to begin again.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update) or not update.effective_user or not update.effective_chat:
        return
    _, state, _ = components(context)
    state.profile(update.effective_user.id, update.effective_chat.id).step = Step.NONE
    await update.effective_message.reply_text(
        "Cancelled.", reply_markup=main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await private_only(update):
        return
    await update.effective_message.reply_text(
        "/start – set up the bot\n/awake – start hourly reminders\n"
        "/sleep – stop reminders\n/status – show the current reminder state\n"
        "/settings – view temporary settings\n/name – change your name\n"
        "/timezone – change timezone\n/forget_me – clear temporary state\n"
        "/cancel – cancel input\n/help – show this help\n\n"
        "The bot does not maintain hydration history or persistent user records. "
        "Hydration needs vary; follow medical advice if you have a fluid restriction."
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
    config, _, reminders = components(context)
    data = query.data or ""
    if data == "sleep":
        await query.answer()
        stopped = reminders.stop_day(update.effective_user.id)
        await query.edit_message_text(
            "Sleep well! Reminders are stopped."
            if stopped
            else "No active session was found."
        )
        return
    if data.startswith("drink:"):
        changed = reminders.confirm(
            update.effective_user.id, data.removeprefix("drink:")
        )
        if changed:
            await query.answer()
            await query.edit_message_text(
                "Nice work! This acknowledgement is not added to any history."
            )
        else:
            await query.answer(
                "This reminder was already handled or is no longer yours.",
                show_alert=True,
            )
        return
    if data.startswith("snooze:"):
        changed = reminders.snooze(
            update.effective_user.id, data.removeprefix("snooze:")
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
    reminders: ReminderService = application.bot_data["reminders"]
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Set up the bot"),
            BotCommand("awake", "Start hourly reminders"),
            BotCommand("sleep", "Stop reminders"),
            BotCommand("status", "Show reminder status"),
            BotCommand("settings", "View temporary settings"),
            BotCommand("forget_me", "Clear temporary state"),
            BotCommand("help", "Show help"),
        ]
    )
    application.job_queue.run_repeating(
        reminders.tick,
        interval=config.scheduler_interval_seconds,
        first=1,
        name="reminder-scheduler",
    )


def build_application(config: Config) -> Application:
    application = (
        ApplicationBuilder().token(config.telegram_token).post_init(post_init).build()
    )
    state = RuntimeState()
    application.bot_data["config"] = config
    application.bot_data["state"] = state
    application.bot_data["reminders"] = ReminderService(application, config, state)

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

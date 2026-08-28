import datetime
import logging
import random
from zoneinfo import ZoneInfo

import hikari
import lightbulb
from lightbulb.ext import tasks

from config import firebase_db, ENABLED_GUILD

logger = logging.getLogger(__name__)

plugin = lightbulb.Plugin("daily_doodle")

DAILY_DOODLE_CHANNEL = "daily-doodle"
CHARACTERS_COLLECTION = "daily_doodle_characters"
PROMPTS_COLLECTION = "daily_doodle_prompts"
STREAKS_COLLECTION = "daily_doodle_streaks"
DAILY_PULL_CRON = "0 12 * * *"  # 08:00 US Eastern (EDT); winter EST would be "0 13 * * *"

# Streaks count in US Eastern calendar days (matching the pull). A streak survives skipping
# up to GRACE_DAYS days, so a gap up to CONTINUE_GAP days between posts still continues it.
STREAK_TZ = ZoneInfo("America/New_York")
GRACE_DAYS = 2
CONTINUE_GAP = 1 + GRACE_DAYS  # 3


# --- shared core logic (used by /daily-doodle pull and the daily task) ---


async def _find_channel(bot: lightbulb.BotApp):
    channels = await bot.rest.fetch_guild_channels(ENABLED_GUILD)
    return next(
        (
            channel
            for channel in channels
            if isinstance(channel, hikari.GuildTextChannel)
            and channel.name == DAILY_DOODLE_CHANNEL
        ),
        None,
    )


def _active_prompts(prompts):
    return [prompt for prompt in prompts if not prompt.get("archived_at")]


def _quote_join(names):
    return ", ".join(f'"{name}"' for name in names)


def _added_summary(kind: str, added, skipped) -> str:
    parts = []
    if added:
        if len(added) == 1:
            parts.append(f"{kind.capitalize()} {_quote_join(added)} added to the pool!")
        else:
            parts.append(
                f"{len(added)} {kind}s added to the pool: {_quote_join(added)}"
            )
    else:
        parts.append(f"No new {kind}s added.")
    if skipped:
        parts.append(f"Skipped (already in the pool): {_quote_join(skipped)}")
    return "\n".join(parts)


def _format_countdown(seconds: float) -> str:
    total_minutes = max(0, round(seconds / 60))
    if total_minutes == 0:
        return "The next daily-doodle pull is in less than a minute."

    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        span = f"{hours}h {minutes}m"
    elif hours:
        span = f"{hours}h"
    else:
        span = f"{minutes}m"
    return f"The next daily-doodle pull is in {span}."


# --- streak helpers (pure, no I/O) ---


def _today():
    return datetime.datetime.now(STREAK_TZ).date()


def _has_media(message) -> bool:
    return any(
        att.media_type and att.media_type.startswith(("image/", "video/"))
        for att in message.attachments
    )


def _next_streak(prev_streak, last_date, today):
    """New streak after a qualifying post today, or None if today is already counted."""
    if last_date is None:
        return 1
    gap = (today - last_date).days
    if gap == 0:
        return None
    return prev_streak + 1 if gap <= CONTINUE_GAP else 1


def _effective_streak(streak, last_date, today) -> int:
    """Stored streak if still within the grace window, else 0 (expired)."""
    if last_date is None:
        return 0
    return streak if (today - last_date).days <= CONTINUE_GAP else 0


def _parse_last_date(value):
    return datetime.date.fromisoformat(value) if value else None


async def perform_pull(bot: lightbulb.BotApp) -> str:
    characters = await firebase_db.collection(CHARACTERS_COLLECTION).get()
    prompts = _active_prompts(await firebase_db.collection(PROMPTS_COLLECTION).get())

    pool = [("character", doc) for doc in characters] + [
        ("prompt", doc) for doc in prompts
    ]
    if not pool:
        return "The daily-doodle pool is empty. Add some characters or prompts!"

    kind, doc = random.choice(pool)
    name = doc.get("name")

    if kind == "character":
        message = f"**Daily Doodle** (optionally) draw this character:\n**{name}**"
    else:
        message = f"**Daily Doodle** (optionally) draw this prompt:\n**{name}**"
        # Archive the prompt in place so it won't be pulled again, but keep it for history
        await firebase_db.collection(PROMPTS_COLLECTION).document(doc.id).update(
            {"archived_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        )

    channel = await _find_channel(bot)
    if channel is None:
        return f"Couldn't find a #{DAILY_DOODLE_CHANNEL} channel to post in."

    await bot.rest.create_message(channel.id, message)
    return f"Pulled a {kind}! Posted in #{DAILY_DOODLE_CHANNEL}."


# --- daily automatic pull (CronTrigger runs in UTC) ---


@tasks.task(tasks.CronTrigger(DAILY_PULL_CRON), auto_start=True, pass_app=True)
async def daily_pull_task(app: lightbulb.BotApp) -> None:
    try:
        await perform_pull(app)
    except Exception:
        logger.exception("Daily doodle pull failed")


# --- streak tracking (only real user uploads count; bot pulls are ignored below) ---


@plugin.listener(hikari.GuildMessageCreateEvent)
async def streak_listener(event: hikari.GuildMessageCreateEvent) -> None:
    if event.is_bot:
        return

    channel = event.get_channel()
    if channel is None or channel.name != DAILY_DOODLE_CHANNEL:
        return

    if not _has_media(event.message):
        return

    today = _today()
    streak_ref = firebase_db.collection(STREAKS_COLLECTION).document(str(event.author_id))
    snapshot = await streak_ref.get()
    data = snapshot.to_dict() if snapshot.exists else {}

    new_streak = _next_streak(
        data.get("streak", 0), _parse_last_date(data.get("last_date")), today
    )
    if new_streak is None:
        # Already counted today — nothing to update
        return

    display_name = (
        event.member.display_name if event.member else event.author.username
    )
    await streak_ref.set(
        {
            "username": display_name,
            "streak": new_streak,
            "last_date": today.isoformat(),
            "best_streak": max(new_streak, data.get("best_streak", 0)),
        }
    )


# --- commands ---


@plugin.command
@lightbulb.command("daily-doodle", "manage the daily doodle pool")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def daily_doodle(ctx: lightbulb.Context):
    pass


@daily_doodle.child
@lightbulb.option("name", "the character(s) to add, comma-separated for multiple")
@lightbulb.command("add-character", "add one or more characters to the pool")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def add_character(ctx: lightbulb.Context) -> None:
    names = [name.strip() for name in ctx.options.name.split(",")]
    names = [name for name in names if name]

    if not names:
        await ctx.respond("No characters to add.")
        return

    characters_ref = firebase_db.collection(CHARACTERS_COLLECTION)
    existing = await characters_ref.get()
    seen = {doc.get("name").lower() for doc in existing if doc.get("name")}

    added = []
    skipped = []
    for name in names:
        key = name.lower()
        if key in seen:
            skipped.append(name)
            continue
        seen.add(key)
        await characters_ref.add({"name": name, "author": ctx.author.username})
        added.append(name)

    await ctx.respond(_added_summary("character", added, skipped))


@daily_doodle.child
@lightbulb.option("prompt", "the prompt to add")
@lightbulb.command("add-prompt", "add a prompt to the pool")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def add_prompt(ctx: lightbulb.Context) -> None:
    prompt = ctx.options.prompt.strip()
    if not prompt:
        await ctx.respond("No prompt to add.")
        return

    prompts_ref = firebase_db.collection(PROMPTS_COLLECTION)
    active = _active_prompts(await prompts_ref.get())
    if any(doc.get("name", "").lower() == prompt.lower() for doc in active):
        await ctx.respond(f'Prompt "{prompt}" is already in the pool.')
        return

    await prompts_ref.add({"name": prompt, "author": ctx.author.username})
    await ctx.respond(f'Prompt "{prompt}" added to the pool!')


@daily_doodle.child
@lightbulb.command("count", "count the characters and prompts in the pool")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def count(ctx: lightbulb.Context) -> None:
    characters = await firebase_db.collection(CHARACTERS_COLLECTION).get()
    prompts = _active_prompts(await firebase_db.collection(PROMPTS_COLLECTION).get())

    await ctx.respond(
        f"{len(characters)} characters and {len(prompts)} prompts in the pool"
    )


@daily_doodle.child
@lightbulb.command("countdown", "how long until the next automatic pull")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def countdown(ctx: lightbulb.Context) -> None:
    # Fresh trigger instance so we don't advance the running task's croniter state
    seconds = tasks.CronTrigger(DAILY_PULL_CRON).get_interval()
    await ctx.respond(_format_countdown(seconds))


@daily_doodle.child
@lightbulb.command("pull", "force a daily doodle pull right now")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def pull(ctx: lightbulb.Context) -> None:
    result = await perform_pull(ctx.bot)
    await ctx.respond(result)


@daily_doodle.child
@lightbulb.option("user", "whose streak to check (defaults to you)", type=hikari.User, required=False)
@lightbulb.command("streak", "check a daily doodle drawing streak")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def streak(ctx: lightbulb.Context) -> None:
    target = ctx.options.user or ctx.author

    snapshot = await firebase_db.collection(STREAKS_COLLECTION).document(str(target.id)).get()
    data = snapshot.to_dict() if snapshot.exists else {}

    today = _today()
    current = _effective_streak(
        data.get("streak", 0), _parse_last_date(data.get("last_date")), today
    )
    best = data.get("best_streak", 0)
    name = target.username

    if current > 0:
        message = f"🔥 {name} has a {current}-day daily doodle streak! (best: {best})"
    elif best > 0:
        message = f"{name} has no active streak. Best so far: {best} days."
    else:
        message = f"{name} hasn't started a daily doodle streak yet."

    await ctx.respond(message)


@daily_doodle.child
@lightbulb.command("leaderboard", "show the top daily doodle streaks")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def leaderboard(ctx: lightbulb.Context) -> None:
    today = _today()
    entries = []
    for doc in await firebase_db.collection(STREAKS_COLLECTION).get():
        data = doc.to_dict()
        current = _effective_streak(
            data.get("streak", 0), _parse_last_date(data.get("last_date")), today
        )
        if current > 0:
            entries.append((current, data.get("username", "someone")))

    if not entries:
        await ctx.respond("No active daily doodle streaks yet")
        return

    entries.sort(key=lambda entry: entry[0], reverse=True)
    lines = [
        f"{index + 1}. **{username}** {streak_count} days"
        for index, (streak_count, username) in enumerate(entries[:10])
    ]
    await ctx.respond("**Daily Doodle Streaks**\n" + "\n".join(lines))


def load(bot: lightbulb.BotApp) -> None:
    bot.add_plugin(plugin)


def unload(bot: lightbulb.BotApp) -> None:
    bot.remove_plugin(plugin)

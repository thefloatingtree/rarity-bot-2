import datetime
import logging
import random
from zoneinfo import ZoneInfo

import hikari
import lightbulb
from lightbulb.ext import tasks

from config import firebase_db, ENABLED_GUILD
from services import author_fields, get_firebase_value

logger = logging.getLogger(__name__)

plugin = lightbulb.Plugin("daily_doodle")

DAILY_DOODLE_CHANNEL = "daily-doodle"
CHARACTERS_COLLECTION = "daily_doodle_characters"
PROMPTS_COLLECTION = "daily_doodle_prompts"
STREAKS_COLLECTION = "daily_doodle_streaks"
CONFIG_COLLECTION = "daily_doodle_config"
CONFIG_DOCUMENT = "settings"
PAUSED_FIELD = "auto_pull_paused"
LAST_PULL_FIELD = "last_pull_date"
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


def _added_summary(kind: str, added, skipped) -> str:
    # Report counts only — names are kept semi-secret, revealed only when pulled
    parts = []
    if added:
        if len(added) == 1:
            parts.append(f"{kind.capitalize()} added to the pool!")
        else:
            parts.append(f"{len(added)} {kind}s added to the pool!")
    else:
        parts.append(f"No new {kind}s added.")
    if skipped:
        parts.append(f"Skipped {len(skipped)} already in the pool.")
    return "\n".join(parts)


def _chunk_lines(lines, limit: int = 2000):
    """Join lines into messages, each within Discord's `limit` character cap."""
    chunks = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _countdown_span(seconds: float) -> str:
    total_minutes = max(0, round(seconds / 60))
    if total_minutes == 0:
        return "less than a minute"

    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _format_countdown(seconds: float) -> str:
    return f"The next daily-doodle pull is in {_countdown_span(seconds)}."


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


# --- auto-pull state (persisted in firebase config doc) ---


async def _is_auto_pull_paused() -> bool:
    return await get_firebase_value(
        CONFIG_COLLECTION, CONFIG_DOCUMENT, PAUSED_FIELD, False
    )


async def _set_auto_pull_paused(paused: bool) -> None:
    await firebase_db.collection(CONFIG_COLLECTION).document(CONFIG_DOCUMENT).set(
        {PAUSED_FIELD: paused}, merge=True
    )


async def _record_pull_date() -> None:
    await firebase_db.collection(CONFIG_COLLECTION).document(CONFIG_DOCUMENT).set(
        {LAST_PULL_FIELD: _today().isoformat()}, merge=True
    )


async def _pulled_today() -> bool:
    snapshot = (
        await firebase_db.collection(CONFIG_COLLECTION).document(CONFIG_DOCUMENT).get()
    )
    data = snapshot.to_dict() if snapshot.exists else {}
    return data.get(LAST_PULL_FIELD) == _today().isoformat()


async def _leaderboard_text() -> str:
    today = _today()
    entries = []
    for doc in await firebase_db.collection(STREAKS_COLLECTION).get():
        data = doc.to_dict()
        current = _effective_streak(
            data.get("streak", 0), _parse_last_date(data.get("last_date")), today
        )
        if current > 0:
            # Streak docs are keyed by user id, so the name shown is always current
            entries.append((current, doc.id))

    if not entries:
        return "No active daily doodle streaks yet"

    entries.sort(key=lambda entry: entry[0], reverse=True)
    lines = [
        f"{index + 1}. <@{user_id}> {streak_count} days"
        for index, (streak_count, user_id) in enumerate(entries[:10])
    ]
    return "**Daily Doodle Streaks**\n" + "\n".join(lines)


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

    message = f"{message}\n\n{await _leaderboard_text()}"
    await bot.rest.create_message(channel.id, message, user_mentions=False)
    await _record_pull_date()
    return f"Pulled a {kind}! Posted in #{DAILY_DOODLE_CHANNEL}."


# --- daily automatic pull (CronTrigger runs in UTC) ---


@tasks.task(tasks.CronTrigger(DAILY_PULL_CRON), auto_start=True, pass_app=True)
async def daily_pull_task(app: lightbulb.BotApp) -> None:
    try:
        if await _is_auto_pull_paused():
            logger.info("Daily doodle auto pull is paused; skipping")
            return
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

    await streak_ref.set(
        {
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
        await characters_ref.add({"name": name, **author_fields(ctx.author)})
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
        await ctx.respond("That prompt is already in the pool.")
        return

    await prompts_ref.add({"name": prompt, **author_fields(ctx.author)})
    await ctx.respond("Prompt added to the pool!")


@daily_doodle.child
@lightbulb.command("list", "DM yourself the full pool of characters and prompts")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def list_pool(ctx: lightbulb.Context) -> None:
    characters = await firebase_db.collection(CHARACTERS_COLLECTION).get()
    all_prompts = await firebase_db.collection(PROMPTS_COLLECTION).get()
    active = _active_prompts(all_prompts)

    character_names = sorted(
        (doc.get("name") for doc in characters if doc.get("name")), key=str.lower
    )
    prompt_names = sorted(
        (doc.get("name") for doc in active if doc.get("name")), key=str.lower
    )

    lines = ["**Daily Doodle Pool**", "", f"__Characters ({len(character_names)})__"]
    lines += [f"• {name}" for name in character_names] or ["_(none)_"]
    lines += ["", f"__Prompts ({len(prompt_names)})__"]
    lines += [f"• {name}" for name in prompt_names] or ["_(none)_"]

    archived_count = len(all_prompts) - len(active)
    if archived_count:
        lines += ["", f"_{archived_count} prompt(s) already used_"]

    try:
        for chunk in _chunk_lines(lines):
            await ctx.author.send(chunk)
    except hikari.ForbiddenError:
        await ctx.respond("I couldn't DM you. Are your DMs open?")
        return

    await ctx.respond("Sent you a DM with the current pool.")


@daily_doodle.child
@lightbulb.command("countdown", "how long until the next automatic pull")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def countdown(ctx: lightbulb.Context) -> None:
    if await _is_auto_pull_paused():
        await ctx.respond("Automatic pulls are paused. Use `/daily-doodle resume` to restart them.")
        return

    # Fresh trigger instance so we don't advance the running task's croniter state
    seconds = tasks.CronTrigger(DAILY_PULL_CRON).get_interval()
    await ctx.respond(_format_countdown(seconds))


@daily_doodle.child
@lightbulb.command("pause", "pause the automatic daily pull")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def pause(ctx: lightbulb.Context) -> None:
    if await _is_auto_pull_paused():
        await ctx.respond("Automatic pulls are already paused.")
        return

    await _set_auto_pull_paused(True)
    await ctx.respond("Automatic daily pulls are now paused. Manual `pull` still works.")


@daily_doodle.child
@lightbulb.command("resume", "resume the automatic daily pull")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def resume(ctx: lightbulb.Context) -> None:
    if not await _is_auto_pull_paused():
        await ctx.respond("Automatic pulls are already running.")
        return

    await _set_auto_pull_paused(False)

    # If nothing has been pulled today, pull now so there's something to draw
    if await _pulled_today():
        await ctx.respond("Automatic daily pulls are back on!")
    else:
        result = await perform_pull(ctx.bot)
        await ctx.respond(f"Automatic daily pulls are back on! Nothing was active, so:\n{result}")


@daily_doodle.child
@lightbulb.command("status", "show the daily doodle status")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def status(ctx: lightbulb.Context) -> None:
    paused = await _is_auto_pull_paused()
    characters = await firebase_db.collection(CHARACTERS_COLLECTION).get()
    prompts = _active_prompts(await firebase_db.collection(PROMPTS_COLLECTION).get())
    pulled_today = await _pulled_today()

    if paused:
        auto_line = "Auto pulls: paused"
    else:
        seconds = tasks.CronTrigger(DAILY_PULL_CRON).get_interval()
        auto_line = f"Auto pulls: running (next in {_countdown_span(seconds)})"

    lines = [
        "**Daily Doodle Status**",
        auto_line,
        f"Pool: {len(characters)} characters, {len(prompts)} prompts",
        f"Today's doodle: {'posted' if pulled_today else 'not yet'}",
    ]
    await ctx.respond("\n".join(lines))


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
    name = target.mention

    if current > 0:
        message = f"🔥 {name} has a {current}-day daily doodle streak! (best: {best})"
    elif best > 0:
        message = f"{name} has no active streak. Best so far: {best} days."
    else:
        message = f"{name} hasn't started a daily doodle streak yet."

    await ctx.respond(message, user_mentions=False)


@daily_doodle.child
@lightbulb.command("leaderboard", "show the top daily doodle streaks")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def leaderboard(ctx: lightbulb.Context) -> None:
    await ctx.respond(await _leaderboard_text(), user_mentions=False)


def load(bot: lightbulb.BotApp) -> None:
    bot.add_plugin(plugin)


def unload(bot: lightbulb.BotApp) -> None:
    bot.remove_plugin(plugin)

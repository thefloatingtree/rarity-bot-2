import datetime
import logging
import random
from zoneinfo import ZoneInfo

import hikari
import lightbulb
from lightbulb.ext import tasks

from config import firebase_db, ENABLED_GUILD
from services import author_fields, get_firebase_value
from utilities import pluralize

logger = logging.getLogger(__name__)

plugin = lightbulb.Plugin("daily_doodle")

DAILY_DOODLE_CHANNEL = "daily-doodle"
CHARACTERS_COLLECTION = "daily_doodle_characters"
PROMPTS_COLLECTION = "daily_doodle_prompts"
STREAKS_COLLECTION = "daily_doodle_streaks"
CONFIG_COLLECTION = "daily_doodle_config"
CONFIG_DOCUMENT = "settings"
GROUP_STREAK_DOCUMENT = "group_streak"
PAUSED_FIELD = "auto_pull_paused"
LAST_PULL_FIELD = "last_pull_date"

# Everything "daily" happens in US Eastern calendar days: the pull, the streaks, the
# grace window. The pull fires at PULL_HOUR local time regardless of DST.
DOODLE_TZ = ZoneInfo("America/New_York")
PULL_HOUR = 8

# The pull task ticks every hour (croniter runs in UTC, but Eastern offsets are whole
# hours so the top of the hour always lines up). Each tick pulls only if today's pull is
# due and hasn't happened yet, so a tick that fails or a bot that was down at PULL_HOUR
# is retried on the next hour instead of skipping the day.
PULL_TICK_CRON = "0 * * * *"

# A streak survives skipping up to GRACE_DAYS days, so a gap up to CONTINUE_GAP days
# between posts still continues it. The group streak works the same way, except any one
# member's post covers everybody.
GRACE_DAYS = 2
CONTINUE_GAP = 1 + GRACE_DAYS  # 3

# Selection: pick the *kind* first so the odds don't drift as prompts get used up
# (characters never archive, prompts do), then pick an item. Characters pulled within
# the last CHARACTER_COOLDOWN_DAYS are skipped when there are other choices.
PROMPT_CHANCE = 0.5
CHARACTER_COOLDOWN_DAYS = 14
LAST_PULLED_FIELD = "last_pulled_at"

MANAGE_PERMISSIONS = hikari.Permissions.MANAGE_GUILD | hikari.Permissions.ADMINISTRATOR


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


def _find_by_name(docs, name: str):
    """The first doc whose `name` matches case-insensitively, or None."""
    key = name.strip().lower()
    return next((doc for doc in docs if (doc.get("name") or "").lower() == key), None)


def _can_manage(ctx: lightbulb.Context, data: dict) -> bool:
    """Whether the caller may remove a pool entry: its author, or a server manager.
    Entries written before author ids were stored can only be removed by managers."""
    if data.get("author_id") == str(ctx.author.id):
        return True
    permissions = getattr(ctx.member, "permissions", None)
    return bool(permissions is not None and permissions & MANAGE_PERMISSIONS)


# --- time helpers (pure, no I/O) ---


def _now():
    return datetime.datetime.now(DOODLE_TZ)


def _today():
    return _now().date()


def _pull_is_due(now) -> bool:
    return now.hour >= PULL_HOUR


def _next_pull_time(now):
    """The next PULL_HOUR o'clock strictly after `now`, in the doodle timezone."""
    candidate = now.replace(hour=PULL_HOUR, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return candidate


def _seconds_between(start, end) -> float:
    """Real elapsed seconds. Subtracting two datetimes in the same zone does wall-clock
    arithmetic (a DST switch vanishes), so compare epoch timestamps instead."""
    return end.timestamp() - start.timestamp()


def _seconds_until_next_pull(now) -> float:
    return _seconds_between(now, _next_pull_time(now))


def _next_tick_time(now):
    """The next top-of-the-hour after `now` (when a pending pull is retried)."""
    return now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)


# --- streak helpers (pure, no I/O) ---


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


# --- selection helpers (pure, no I/O) ---


def _recently_pulled(data: dict, today) -> bool:
    value = data.get(LAST_PULLED_FIELD)
    if not value:
        return False
    try:
        pulled_on = datetime.datetime.fromisoformat(value).astimezone(DOODLE_TZ).date()
    except ValueError:
        return False
    return (today - pulled_on).days < CHARACTER_COOLDOWN_DAYS


def _eligible_characters(characters, today):
    """Characters not pulled recently; falls back to everyone if that leaves nobody."""
    fresh = [doc for doc in characters if not _recently_pulled(doc.to_dict(), today)]
    return fresh or list(characters)


def _choose(characters, prompts, today, rng=random):
    """Pick (kind, doc) from the pool, or None if it's empty."""
    kinds = []
    if characters:
        kinds.append("character")
    if prompts:
        kinds.append("prompt")
    if not kinds:
        return None

    if len(kinds) == 2:
        kind = "prompt" if rng.random() < PROMPT_CHANCE else "character"
    else:
        kind = kinds[0]

    if kind == "character":
        return kind, rng.choice(_eligible_characters(characters, today))
    return kind, rng.choice(list(prompts))


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


async def _countdown_text() -> str:
    """Where the automatic pull stands right now, for countdown/status."""
    if await _is_auto_pull_paused():
        return "Automatic pulls are paused. Use `/daily-doodle resume` to restart them."

    now = _now()
    if _pull_is_due(now) and not await _pulled_today():
        retry_in = _seconds_between(now, _next_tick_time(now))
        return (
            "Today's pull hasn't gone out yet — it'll be retried in "
            f"{_countdown_span(retry_in)}."
        )
    return f"The next daily-doodle pull is in {_countdown_span(_seconds_until_next_pull(now))}."


def _group_streak_ref():
    return firebase_db.collection(CONFIG_COLLECTION).document(GROUP_STREAK_DOCUMENT)


async def _record_group_post(today) -> None:
    """Count a qualifying post toward the group streak. One post covers everyone,
    so this is a no-op once somebody has posted today."""
    ref = _group_streak_ref()
    snapshot = await ref.get()
    data = snapshot.to_dict() if snapshot.exists else {}

    new_streak = _next_streak(
        data.get("streak", 0), _parse_last_date(data.get("last_date")), today
    )
    if new_streak is None:
        return

    await ref.set(
        {
            "streak": new_streak,
            "last_date": today.isoformat(),
            "best_streak": max(new_streak, data.get("best_streak", 0)),
        }
    )


async def _group_streak_text() -> str:
    snapshot = await _group_streak_ref().get()
    data = snapshot.to_dict() if snapshot.exists else {}

    current = _effective_streak(
        data.get("streak", 0), _parse_last_date(data.get("last_date")), _today()
    )
    best = data.get("best_streak", 0)

    if current > 0:
        return f"🔥 **Group streak: {current} {pluralize(current, 'day')}** (best: {best})"
    if best > 0:
        return f"No active group streak. Best so far: {best} {pluralize(best, 'day')}"
    return "No group streak yet"


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
        f"{index + 1}. <@{user_id}> {streak_count} {pluralize(streak_count, 'day')}"
        for index, (streak_count, user_id) in enumerate(entries[:10])
    ]
    return "**Daily Doodle Streaks**\n" + "\n".join(lines)


async def perform_pull(bot: lightbulb.BotApp) -> str:
    # Resolve the channel first: nothing in the pool is consumed until we know the
    # post can actually go somewhere.
    channel = await _find_channel(bot)
    if channel is None:
        return f"Couldn't find a #{DAILY_DOODLE_CHANNEL} channel to post in."

    characters = await firebase_db.collection(CHARACTERS_COLLECTION).get()
    prompts = _active_prompts(await firebase_db.collection(PROMPTS_COLLECTION).get())

    choice = _choose(characters, prompts, _today())
    if choice is None:
        return "The daily-doodle pool is empty. Add some characters or prompts!"

    kind, doc = choice
    name = doc.get("name")
    message = f"**Daily Doodle** (optionally) draw this {kind}:\n**{name}**"

    message = f"{message}\n\n{await _group_streak_text()}"
    await bot.rest.create_message(channel.id, message, user_mentions=False)
    await _record_pull_date()

    # Only after the post is out do we mark the item as used
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if kind == "character":
        # Remember when it was pulled so it sits out the cooldown
        await firebase_db.collection(CHARACTERS_COLLECTION).document(doc.id).update(
            {LAST_PULLED_FIELD: now_iso}
        )
    else:
        # Archive the prompt in place so it won't be pulled again, but keep it for history
        await firebase_db.collection(PROMPTS_COLLECTION).document(doc.id).update(
            {"archived_at": now_iso}
        )

    return f"Pulled a {kind}! Posted in #{DAILY_DOODLE_CHANNEL}."


async def _pull_if_due(bot: lightbulb.BotApp, reason: str) -> None:
    """Run today's automatic pull if it's time and it hasn't happened. Safe to call
    repeatedly (hourly tick, startup) — it only ever pulls once per day."""
    try:
        if await _is_auto_pull_paused():
            logger.info("Daily doodle auto pull is paused; skipping (%s)", reason)
            return
        if not _pull_is_due(_now()):
            return
        if await _pulled_today():
            return
        logger.info("Running daily doodle pull (%s)", reason)
        result = await perform_pull(bot)
        logger.info("Daily doodle pull: %s", result)
    except Exception:
        logger.exception("Daily doodle pull failed (%s)", reason)


# --- automatic pull: hourly tick + startup catch-up ---


@tasks.task(tasks.CronTrigger(PULL_TICK_CRON), auto_start=True, pass_app=True)
async def daily_pull_task(app: lightbulb.BotApp) -> None:
    await _pull_if_due(app, "hourly tick")


@plugin.listener(hikari.StartedEvent)
async def catch_up_on_start(event: hikari.StartedEvent) -> None:
    # If the bot was down at PULL_HOUR, don't lose the day's doodle
    await _pull_if_due(plugin.bot, "startup catch-up")


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
    await _record_group_post(today)

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
    if _find_by_name(active, prompt) is not None:
        await ctx.respond("That prompt is already in the pool.")
        return

    await prompts_ref.add({"name": prompt, **author_fields(ctx.author)})
    await ctx.respond("Prompt added to the pool!")


@daily_doodle.child
@lightbulb.option("name", "the character to remove (exact name, case-insensitive)")
@lightbulb.command("remove-character", "remove a character you added (managers can remove any)")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def remove_character(ctx: lightbulb.Context) -> None:
    characters_ref = firebase_db.collection(CHARACTERS_COLLECTION)
    doc = _find_by_name(await characters_ref.get(), ctx.options.name)

    if doc is None:
        await ctx.respond("No character by that name is in the pool.")
        return
    if not _can_manage(ctx, doc.to_dict()):
        await ctx.respond("You can only remove characters you added.")
        return

    await characters_ref.document(doc.id).delete()
    await ctx.respond(f"Removed **{doc.get('name')}** from the pool.")


@daily_doodle.child
@lightbulb.option("prompt", "the prompt to remove (exact text, case-insensitive)")
@lightbulb.command("remove-prompt", "remove a prompt you added (managers can remove any)")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def remove_prompt(ctx: lightbulb.Context) -> None:
    prompts_ref = firebase_db.collection(PROMPTS_COLLECTION)
    doc = _find_by_name(_active_prompts(await prompts_ref.get()), ctx.options.prompt)

    if doc is None:
        await ctx.respond("No prompt matching that text is in the pool.")
        return
    if not _can_manage(ctx, doc.to_dict()):
        await ctx.respond("You can only remove prompts you added.")
        return

    await prompts_ref.document(doc.id).delete()
    await ctx.respond(f"Removed **{doc.get('name')}** from the pool.")


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
    await ctx.respond(await _countdown_text())


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
    characters = await firebase_db.collection(CHARACTERS_COLLECTION).get()
    prompts = _active_prompts(await firebase_db.collection(PROMPTS_COLLECTION).get())
    pulled_today = await _pulled_today()

    lines = [
        "**Daily Doodle Status**",
        await _countdown_text(),
        f"Pool: {len(characters)} characters, {len(prompts)} prompts",
        f"Today's doodle: {'posted' if pulled_today else 'not yet'}",
    ]
    await ctx.respond("\n".join(lines))


@daily_doodle.child
@lightbulb.option(
    "force",
    "pull again even if today's doodle was already posted",
    type=bool,
    required=False,
    default=False,
)
@lightbulb.command("pull", "force a daily doodle pull right now")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def pull(ctx: lightbulb.Context) -> None:
    if await _pulled_today() and not ctx.options.force:
        await ctx.respond(
            "Today's doodle has already been posted. Run `/daily-doodle pull force: True` "
            "to pull another one anyway."
        )
        return

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
    message = f"{await _group_streak_text()}\n\n{await _leaderboard_text()}"
    await ctx.respond(message, user_mentions=False)


def load(bot: lightbulb.BotApp) -> None:
    bot.add_plugin(plugin)


def unload(bot: lightbulb.BotApp) -> None:
    bot.remove_plugin(plugin)

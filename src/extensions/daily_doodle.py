import datetime
import logging
import random

import hikari
import lightbulb
from lightbulb.ext import tasks

from config import firebase_db, ENABLED_GUILD

logger = logging.getLogger(__name__)

plugin = lightbulb.Plugin("daily_doodle")

DAILY_DOODLE_CHANNEL = "daily-doodle"
CHARACTERS_COLLECTION = "daily_doodle_characters"
PROMPTS_COLLECTION = "daily_doodle_prompts"
DAILY_PULL_CRON = "0 12 * * *"  # 08:00 US Eastern (EDT); winter EST would be "0 13 * * *"


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
        await ctx.respond("No characters to add — give me at least one name.")
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
        await ctx.respond("No prompt to add — give me something to draw.")
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


def load(bot: lightbulb.BotApp) -> None:
    bot.add_plugin(plugin)


def unload(bot: lightbulb.BotApp) -> None:
    bot.remove_plugin(plugin)

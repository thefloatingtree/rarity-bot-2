import hikari
import lightbulb
from lightbulb.ext import tasks

from config import BOT_TOKEN, ENABLED_GUILD

rarity = lightbulb.BotApp(
    prefix="!rarity ",
    token=BOT_TOKEN,
    default_enabled_guilds=(ENABLED_GUILD),
    case_insensitive_prefix_commands=True,
    intents=(hikari.Intents.ALL_UNPRIVILEGED | hikari.Intents.MESSAGE_CONTENT),
)

# Wire the background-task lifecycle into the bot (used by the daily-doodle pull)
tasks.load(rarity)

rarity.load_extensions(
    "extensions.chat",
    "extensions.fun",
    "extensions.pony",
    "extensions.emote",
    "extensions.drawings_from_a_hat",
    "extensions.daily_doodle",
)

rarity.run()

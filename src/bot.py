import hikari
import lightbulb

from config import BOT_TOKEN, ENABLED_GUILD

rarity = lightbulb.BotApp(
    prefix="!rarity ",
    token=BOT_TOKEN,
    default_enabled_guilds=(ENABLED_GUILD),
    case_insensitive_prefix_commands=True,
    intents=(hikari.Intents.ALL_UNPRIVILEGED | hikari.Intents.MESSAGE_CONTENT),
)

rarity.load_extensions(
    "extensions.chat",
    "extensions.fun",
    "extensions.pony",
    "extensions.emote",
    "extensions.drawings_from_a_hat",
)

rarity.run()

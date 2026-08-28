import lightbulb

from services import search_derpi

plugin = lightbulb.Plugin("pony")


@plugin.command
@lightbulb.option("tags", "comma-separated derpibooru tags to search")
@lightbulb.command("pony", "search for images of ponies on derpibooru")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def pony(ctx: lightbulb.Context):
    query: str = ctx.options.query
    tags = query.split(",")
    tags = list(map(lambda tag: tag.strip(), tags))

    response = search_derpi(tags)
    await ctx.respond(response)


@plugin.command
@lightbulb.command("rarity_loves_twilight", "send the gif")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def rarity_loves_twilight(ctx: lightbulb.Context):
    await ctx.respond(
        "https://media.discordapp.net/attachments/392164092959260674/752326934691577966/RariTwiKissu.gif"
    )


@plugin.command
@lightbulb.command("emergency_raritwi", "raritwi images")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def emergency_raritwi(ctx: lightbulb.Context):
    response = search_derpi(["rarilight", "pony"])
    await ctx.respond(response)


@plugin.command
@lightbulb.command("emergency_rarity", "rarity images")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def emergency_rarity(ctx: lightbulb.Context):
    response = search_derpi(["rarity", "pony", "solo"])
    await ctx.respond(response)


@plugin.command
@lightbulb.command("emergency_twilight", "twilight images")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def emergency_twilight(ctx: lightbulb.Context):
    response = search_derpi(["ts", "pony", "solo"])
    await ctx.respond(response)


def load(bot: lightbulb.BotApp) -> None:
    bot.add_plugin(plugin)


def unload(bot: lightbulb.BotApp) -> None:
    bot.remove_plugin(plugin)

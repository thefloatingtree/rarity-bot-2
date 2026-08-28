import hikari
import lightbulb

from config import firebase_db

plugin = lightbulb.Plugin("emote")


@plugin.command
@lightbulb.command("emote", "add or send custom emotes")
@lightbulb.implements(lightbulb.PrefixCommandGroup, lightbulb.SlashCommandGroup)
async def emote(ctx: lightbulb.Context):
    pass


@emote.child
@lightbulb.command("list", "show added emotes")
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def emote_list(ctx: lightbulb.Context) -> None:
    # Grab emotes and accumulate them into a single string
    emotes = await firebase_db.collection("emotes").get()

    response = ""
    for index, emote in enumerate(emotes):
        name = emote.get("name")
        author = emote.get("author")
        response += f"{index + 1}) **{name}** added by {author}\n"

    if not response:
        response = "Emote list is empty"

    await ctx.respond(response)


@emote.child
@lightbulb.option("name", "the name of the emote")
@lightbulb.option("url", "an image or gif url")
@lightbulb.command("add", "add an emote to the list")
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def emote_add(ctx: lightbulb.Context) -> None:
    # Check to make sure emote name doesn't already exist
    emotes_ref = firebase_db.collection("emotes")
    emotes = await emotes_ref.where("name", "==", ctx.options.name).get()

    if not emotes:
        await emotes_ref.add(
            {
                "author": ctx.author.username,
                "url": ctx.options.url,
                "name": ctx.options.name,
            }
        )

        success_embed = hikari.Embed(title=f"New Emote: {ctx.options.name}")
        success_embed.set_image(ctx.options.url)
        success_embed.set_footer(ctx.author.username)

        await ctx.respond(success_embed)
    else:
        await ctx.respond(f'Emote "{ctx.options.name}" already exists')


@emote.child
@lightbulb.option("name", "the name of the emote to be deleted")
@lightbulb.command("remove", "remove an emote from the list")
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def emote_remove(ctx: lightbulb.Context) -> None:
    emotes_ref = firebase_db.collection("emotes")
    emotes = await emotes_ref.where("name", "==", ctx.options.name).get()

    if emotes:
        # Grab first (and hopefully only) item
        emote, *_ = emotes
        await emotes_ref.document(emote.id).delete()
        await ctx.respond(f'Emote "{ctx.options.name}" successfully deleted')
    else:
        await ctx.respond(f'Emote "{ctx.options.name}" does not exist')


@emote.child
@lightbulb.option("name", "the name of the emote")
@lightbulb.command("send", "send an emote")
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def emote_send(ctx: lightbulb.Context) -> None:
    emotes_ref = firebase_db.collection("emotes")
    emotes = await emotes_ref.where("name", "==", ctx.options.name).get()

    if emotes:
        # Grab first (and hopefully only) item
        emote, *_ = emotes
        url = emote.get("url")
        await ctx.respond(url)
    else:
        await ctx.respond(f'Emote "{ctx.options.name}" does not exist')


def load(bot: lightbulb.BotApp) -> None:
    bot.add_plugin(plugin)


def unload(bot: lightbulb.BotApp) -> None:
    bot.remove_plugin(plugin)

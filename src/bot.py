from functools import reduce
import json
import hikari
import lightbulb
from derpibooru import Search
import random
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore_async

load_dotenv()

cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_PRIVATE_KEY_DICT")))
firebase_app = firebase_admin.initialize_app(cred)
firebase_db = firestore_async.client()

rarity = lightbulb.BotApp(
    prefix="!rarity ",
    token=os.getenv("BOT_TOKEN"),
    default_enabled_guilds=(int(os.getenv("ENABLED_GUILD"))),
    case_insensitive_prefix_commands=True,
)

def search_derpi(tags: list[str]) -> str:
    found_image = False
    for image in Search().query("safe", *tags).sort_by("random").limit(1):
        found_image = True
        return image.medium

    if not found_image:
        return "No images matching query: " + ", ".join(tags)


@rarity.command
@lightbulb.command("hello", "it's only fair to reciprocate!")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def hello(ctx: lightbulb.Context):
    await ctx.respond("Hello!")


@rarity.command
@lightbulb.option("tags", "comma-separated derpibooru tags to search")
@lightbulb.command("pony", "search for images of ponies on derpibooru")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def pony(ctx: lightbulb.Context):
    query: str = ctx.options.query
    tags = query.split(",")
    tags = list(map(lambda tag: tag.strip(), tags))

    response = search_derpi(tags)
    await ctx.respond(response)


@rarity.command
@lightbulb.command("rarity_loves_twilight", "send the gif")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def rarity_loves_twilight(ctx: lightbulb.Context):
    await ctx.respond(
        "https://media.discordapp.net/attachments/392164092959260674/752326934691577966/RariTwiKissu.gif"
    )


@rarity.command
@lightbulb.command("emergency_raritwi", "raritwi images")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def emergency_raritwi(ctx: lightbulb.Context):
    response = search_derpi(["rarilight", "pony"])
    await ctx.respond(response)


@rarity.command
@lightbulb.command("emergency_rarity", "rarity images")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def emergency_rarity(ctx: lightbulb.Context):
    response = search_derpi(["rarilight", "pony"])
    await ctx.respond(response)


@rarity.command
@lightbulb.command("emergency_twilight", "twilight images")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def emergency_twilight(ctx: lightbulb.Context):
    response = search_derpi(["rarilight", "pony"])
    await ctx.respond(response)


@rarity.command
@lightbulb.command("what_do_you_think", "decisions, decisions...")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def what_do_you_think(ctx: lightbulb.Context):
    if bool(random.getrandbits(1)):
        await ctx.respond("Hmm, yes, I agree.")
    else:
        await ctx.respond("Hmm, no, I don't agree.")


@rarity.command
@lightbulb.command("rate_this", "0/10 never using again")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def rate_this(ctx: lightbulb.Context):
    rating = random.randint(0, 10)
    await ctx.respond(f"I give it {rating}/10")


@rarity.command
@lightbulb.command("tell_me_a_joke", "i've never laughed harder in my life")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def tell_me_a_joke(ctx: lightbulb.Context):
    jokes = [
        "You.",
        "What do you call it when your sister refuses to lower the moon?\nLunacy.",
        "Where do ponies go to get their shoes?\nFetlocker.",
        "What do you call a pretty rainbow pony?\nDashing.",
        "What do you call a Draconequus that is removed from MLP?\nDiscard.",
        "How many children does Celestia have?\nOne. The Sun.",
        "What's my favourite time of day?\nTwilight. mwa <3",
        "Darling, I'd love to tell you a joke, but my throat's feeling a little horse!",
        "Why is Winona not allowed to drive the tractor?\nShe received too many barking tickets.",
        "Why does Luna enjoy stopping ponies' nightmares?\nIt's her dream job.",
        "Why couldn't Applebloom charge her iPhone?\nShe needed an Applejack.",
        "I once bumped my head into a church bell.\nIt was the worst possible ding!",
        "Why doesn't Fluttershy use the elevator?\nShe's the stare master.",
        "Why did Twilight give her books to Rainbow?\nTo store it in the cloud.",
        "Why did Applejack lie?\nShe didn't. I lied.",
        "Where do ponies go when they're sick?\nThe horsepital.",
        "What do unicorns do during rush hour?\nThey honk their horns.",
        "A pony walks into a bar.\n Ouch.",
        "Why did Twilight's rune backfire?\nShe didn't run a spell check.",
        "Why did the CMCs cross the road?\nThe rest were just following Scootaloo.",
        "What car does Luna drive?\nA Moonborghini.",
        "Neigh",
    ]
    await ctx.respond(random.choice(jokes))


@rarity.command
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


# Secret Santa
# Drawings from a hat

rarity.run()

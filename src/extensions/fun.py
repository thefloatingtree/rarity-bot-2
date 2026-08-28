import random

import lightbulb

plugin = lightbulb.Plugin("fun")


@plugin.command
@lightbulb.command("hello", "it's only fair to reciprocate!")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def hello(ctx: lightbulb.Context):
    await ctx.respond("Hello!")


@plugin.command
@lightbulb.command("what_do_you_think", "decisions, decisions...")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def what_do_you_think(ctx: lightbulb.Context):
    if bool(random.getrandbits(1)):
        await ctx.respond("Hmm, yes, I agree.")
    else:
        await ctx.respond("Hmm, no, I don't agree.")


@plugin.command
@lightbulb.command("rate_this", "0/10 never using again")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def rate_this(ctx: lightbulb.Context):
    rating = random.randint(0, 10)
    await ctx.respond(f"I give it {rating}/10")


@plugin.command
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


def load(bot: lightbulb.BotApp) -> None:
    bot.add_plugin(plugin)


def unload(bot: lightbulb.BotApp) -> None:
    bot.remove_plugin(plugin)

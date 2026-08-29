import random

import lightbulb

from config import firebase_db
from services import author_fields

plugin = lightbulb.Plugin("drawings_from_a_hat")


@plugin.command
@lightbulb.command("drawings-from-a-hat", "add and pull random art prompts!")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def drawings_from_a_hat(ctx: lightbulb.Context):
    pass


@drawings_from_a_hat.child
@lightbulb.option("prompt", "the prompt to be drawn")
@lightbulb.command("add", "add a new prompt to the pile")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def drawings_from_a_hat_add(ctx: lightbulb.Context) -> None:
    prompts_ref = firebase_db.collection("drawings_from_a_hat_prompts")
    number_of_prompts = len(await prompts_ref.get())

    await prompts_ref.add(
        {
            **author_fields(ctx.author),
            "name": ctx.options.prompt,
        }
    )

    await ctx.respond(f"Prompt added. {number_of_prompts + 1} prompts in the hat")


@drawings_from_a_hat.child
@lightbulb.command("pull", "pull a prompt to draw")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def drawings_from_a_hat_pull(ctx: lightbulb.Context) -> None:
    prompts_ref = firebase_db.collection("drawings_from_a_hat_prompts")
    prompts = await prompts_ref.get()

    if prompts:
        prompt = random.choice(prompts)

        await ctx.author.send(f'Your prompt is:\n```{prompt.get("name")}```')
        await ctx.respond(
            f"Prompt sent to {ctx.author.mention} in dm", user_mentions=False
        )
    else:
        await ctx.respond("There are no prompts in the hat")


def load(bot: lightbulb.BotApp) -> None:
    bot.add_plugin(plugin)


def unload(bot: lightbulb.BotApp) -> None:
    bot.remove_plugin(plugin)

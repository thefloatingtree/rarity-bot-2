import hikari
import lightbulb

import openai

from config import firebase_db, chat_default_system_message
from services import get_firebase_value

plugin = lightbulb.Plugin("chat")


@plugin.command
@lightbulb.command("chat", "chat with rarity!")
@lightbulb.implements(lightbulb.PrefixCommandGroup, lightbulb.SlashCommandGroup)
async def chat(ctx: lightbulb.Context):
    pass


@plugin.listener(hikari.GuildMessageCreateEvent)
async def chat_listener(event: hikari.GuildMessageCreateEvent):
    max_chat_history_length = 20

    if event.is_bot:
        return

    channel = event.get_channel()
    is_chat_channel = channel.name == "rarity-chat"

    if not is_chat_channel:
        return

    await event.get_channel().trigger_typing()

    if len(event.content) > 1028:
        return await event.message.respond("I'm not reading all that...")

    chat_history = await get_firebase_value("chat", "history", "history", [])
    system_prompt = await get_firebase_value(
        "chat", "system_prompt", "system_prompt", chat_default_system_message
    )

    # Get a response from open ai for the new message
    new_chat_message = {
        "role": "user",
        "content": f"{event.get_member().display_name}: {event.content}",
    }
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            *chat_history,
            new_chat_message,
        ],
        temperature=1.2,
        max_tokens=256,
        top_p=1,
        frequency_penalty=0.3,
        presence_penalty=0.3,
    )

    # Save new message and response to firebase history
    response_content = response["choices"][0]["message"]["content"]
    new_bot_message = {"role": "assistant", "content": response_content}

    chat_history.append(new_chat_message)
    chat_history.append(new_bot_message)

    # Ensure chat history doesn't grow larger than max length. Trim from the start, not the end
    if len(chat_history) > max_chat_history_length:
        amount_to_trim = (
            len(chat_history) - max_chat_history_length
            if len(chat_history) - max_chat_history_length >= 0
            else 0
        )
        chat_history = chat_history[amount_to_trim:]

    await firebase_db.collection("chat").document("history").set(
        {"history": chat_history}
    )

    await event.message.respond(content=response_content)


@chat.child
@lightbulb.command("clear", "clear rarity's memory of the conversation!")
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def chat_clear_history(ctx: lightbulb.Context) -> None:
    await firebase_db.collection("chat").document("history").set({"history": []})

    await ctx.respond("History cleared!")


@chat.child
@lightbulb.option("prompt", "the system prompt")
@lightbulb.command(
    "set-system-prompt",
    "change the bot's personality, also clears the bot's memory of the conversation",
)
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def chat_set_system_prompt(ctx: lightbulb.Context) -> None:
    await firebase_db.collection("chat").document("history").set({"history": []})
    await firebase_db.collection("chat").document("system_prompt").set(
        {"system_prompt": ctx.options.prompt}
    )

    await ctx.respond("System prompt updated! History Cleared!")


@chat.child
@lightbulb.command("get-system-prompt", "get the current system prompt")
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def chat_get_system_prompt(ctx: lightbulb.Context) -> None:
    system_prompt = await get_firebase_value(
        "chat", "system_prompt", "system_prompt", chat_default_system_message
    )

    await ctx.respond(system_prompt)


@chat.child
@lightbulb.command(
    "reset-system-prompt-to-default", "makes rarity be like rarity again"
)
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def chat_reset_system_prompt(ctx: lightbulb.Context) -> None:
    await firebase_db.collection("chat").document("history").set({"history": []})
    await firebase_db.collection("chat").document("system_prompt").set(
        {"system_prompt": chat_default_system_message}
    )

    await ctx.respond("System prompt updated! History Cleared!")


def load(bot: lightbulb.BotApp) -> None:
    bot.add_plugin(plugin)


def unload(bot: lightbulb.BotApp) -> None:
    bot.remove_plugin(plugin)

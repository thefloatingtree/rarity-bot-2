import json
import random

import hikari
import lightbulb

from derpibooru import Search

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore_async

import os
from dotenv import load_dotenv

load_dotenv()

import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_PRIVATE_KEY_DICT")))
firebase_app = firebase_admin.initialize_app(cred)
firebase_db = firestore_async.client()

rarity = lightbulb.BotApp(
    prefix="!rarity ",
    token=os.getenv("BOT_TOKEN"),
    default_enabled_guilds=(int(os.getenv("ENABLED_GUILD"))),
    case_insensitive_prefix_commands=True,
    intents=(hikari.Intents.ALL_UNPRIVILEGED | hikari.Intents.MESSAGE_CONTENT),
)

chat_default_system_message = "You are Rarity from the tv show my little pony. You should not mention that you are from that tv show, but you should inherit her speaking pattern, preferences, and goals. Your goal is to have a funny or interesting conversation with the user. The user's name that you're chatting with will preface the message. When responding you should not preface your message with your name. Be dynamic with the length of responses, keep your responses casual in nature."


def search_derpi(tags: list[str]) -> str:
    for image in Search().query("safe", *tags).sort_by("random").limit(1):
        return image.medium

    return "No images matching query: " + ", ".join(tags)


async def get_firebase_value(
    collection_name: str, document_name: str, field_name: str, default_value
):
    # Ensure value exists in firebase
    document_ref = firebase_db.collection(collection_name).document(document_name)
    document = await document_ref.get()
    value = document.get(field_name)
    if value == None:
        await document_ref.set({field_name: default_value})
        value = default_value
    return value


@rarity.command
@lightbulb.command("chat", "chat with rarity!")
@lightbulb.implements(lightbulb.PrefixCommandGroup, lightbulb.SlashCommandGroup)
async def chat(ctx: lightbulb.Context):
    pass


@rarity.listen(hikari.GuildMessageCreateEvent)
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
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt},
            *chat_history,
            new_chat_message,
        ],
        temperature=0.9,
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
    "set_system_prompt",
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
@lightbulb.command("get_system_prompt", "get the current system prompt")
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def chat_set_system_prompt(ctx: lightbulb.Context) -> None:
    system_prompt = await get_firebase_value(
        "chat", "system_prompt", "system_prompt", chat_default_system_message
    )

    await ctx.respond(system_prompt)


@chat.child
@lightbulb.command(
    "reset_system_prompt_to_default", "makes rarity be like rarity again"
)
@lightbulb.implements(lightbulb.PrefixSubCommand, lightbulb.SlashSubCommand)
async def chat_set_system_prompt(ctx: lightbulb.Context) -> None:
    await firebase_db.collection("chat").document("history").set({"history": []})
    await firebase_db.collection("chat").document("system_prompt").set(
        {"system_prompt": chat_default_system_message}
    )

    await ctx.respond("System prompt updated! History Cleared!")


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
    response = search_derpi(["rarity", "pony", "solo"])
    await ctx.respond(response)


@rarity.command
@lightbulb.command("emergency_twilight", "twilight images")
@lightbulb.implements(lightbulb.PrefixCommand, lightbulb.SlashCommand)
async def emergency_twilight(ctx: lightbulb.Context):
    response = search_derpi(["ts", "pony", "solo"])
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


@rarity.command
@lightbulb.command("drawings_from_a_hat", "add and pull random art prompts!")
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
            "author": ctx.author.username,
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
        await ctx.respond(f"Prompt sent to {ctx.author.username} in dm")
    else:
        await ctx.respond("There are no prompts in the hat")


# Secret Santa
# Draw along
# Initialize: prompt, time
# Join
# Leave
# Start
# Cancel
# Participants
# Fitness

rarity.run()

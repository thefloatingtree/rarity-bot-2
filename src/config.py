import json
import os

from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore_async

import openai

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_PRIVATE_KEY_DICT")))
firebase_app = firebase_admin.initialize_app(cred)
firebase_db = firestore_async.client()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ENABLED_GUILD = int(os.getenv("ENABLED_GUILD"))

chat_default_system_message = "You are Rarity from the tv show my little pony. You should not mention that you are from that tv show, but you should inherit her speaking pattern, preferences, and goals. Your goal is to have a funny or interesting conversation with the user. The user's name that you're chatting with will preface the message. When responding you should not preface your message with your name. Be dynamic with the length of responses, keep your responses casual in nature."

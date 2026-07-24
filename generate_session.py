from telethon import TelegramClient
from telethon.sessions import StringSession

# Run this once, locally, on your own machine — NOT in GitHub Actions.
# It will prompt for your phone number and login code interactively.

API_ID = int(input("Enter your API_ID: "))
API_HASH = input("Enter your API_HASH: ")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()
    print("\nSAVE THIS AS A GITHUB SECRET NAMED TELETHON_SESSION:\n")
    print(session_string)

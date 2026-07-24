import re
import os
import asyncio
from datetime import datetime
 
from telethon import TelegramClient
from telethon.sessions import StringSession
from telegram import Bot
 
# ============================================================
# CONFIG
# ============================================================
 
# --- Credentials for READING the source channel (Telethon user account) ---
# Get API_ID / API_HASH from https://my.telegram.org
# Get TELETHON_SESSION by running generate_session.py once, locally
API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_STRING = os.environ["TELETHON_SESSION"]
 
# Channel you want to listen to (username like '@some_channel', or numeric ID)
SOURCE_CHANNEL = os.environ["SOURCE_CHANNEL"]
 
# The exact location you're extracting from that channel's messages
TARGET_LOCATION = "Sembawang Airbase"
 
# --- Credentials for PUBLISHING your own alert (Bot API) ---
BOT_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
 
# File used to remember the previous WBGT colour code between runs
STATE_FILE = "last_wbgt_status.txt"
 
# How many recent messages to scan when looking for the target line.
# Channel posts every 6 min, so 10 messages comfortably covers the last hour
# even if a run is late or a message or two gets skipped.
MESSAGE_SCAN_LIMIT = 10
 
# ============================================================
# REGEX
# ============================================================
 
# Matches a line like: "• Sembawang Airbase, 31.1℃"
# Anchored to TARGET_LOCATION specifically, so it won't accidentally
# grab a different station's reading from the same message.
LINE_PATTERN = re.compile(
    re.escape(TARGET_LOCATION) + r"\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*℃",
    re.IGNORECASE,
)
 
 
# ============================================================
# COLOUR CLASSIFICATION
# ============================================================
 
def get_colour_code(wbgt: float):
    if wbgt <= 29.9:
        return "⚪", "WHITE"
    elif wbgt <= 30.9:
        return "🟢", "GREEN"
    elif wbgt <= 31.9:
        return "🟡", "YELLOW"
    elif wbgt <= 32.9:
        return "🔴", "RED"
    elif wbgt <= 34.9:
        return "⚫", "BLACK"
    else:
        return "🚫", "CUT OFF"
 
 
# Colours considered "alert" tier — RED and above
ALERT_TIERS = {"RED", "BLACK", "CUT OFF"}
 
 
def should_send(current_colour: str, previous_colour: str | None) -> bool:
    """
    Send only when:
      - currently in an alert tier (RED/BLACK/CUT OFF) AND it's different
        from the last saved colour (covers entering the tier, or moving
        between RED -> BLACK -> CUT OFF), or
      - previously in an alert tier and has now dropped below it
        (RED/BLACK/CUT OFF -> WHITE/GREEN/YELLOW)
    Stays silent for any change entirely below RED (e.g. WHITE <-> GREEN <-> YELLOW).
    """
    current_is_alert = current_colour in ALERT_TIERS
    previous_is_alert = previous_colour in ALERT_TIERS if previous_colour else False
 
    if current_is_alert and current_colour != previous_colour:
        return True
    if previous_is_alert and not current_is_alert:
        return True
    return False

# ============================================================
# FETCH FROM CHANNEL (replaces the old fetch_wbgt() API call)
# ============================================================
 
async def fetch_wbgt_from_channel():
    """
    Scans the most recent messages in SOURCE_CHANNEL for a line
    containing TARGET_LOCATION and its temperature.
 
    Returns (temperature: float, message_datetime: datetime) on success,
    or (None, None) if no matching line was found.
    """
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
 
    try:
        async for message in client.iter_messages(SOURCE_CHANNEL, limit=MESSAGE_SCAN_LIMIT):
            if not message.text:
                continue
            match = LINE_PATTERN.search(message.text)
            if match:
                temp = float(match.group(1))
                return temp, message.date
    finally:
        await client.disconnect()
 
    return None, None
 
 
# ============================================================
# MESSAGE FORMATTING
# ============================================================
 
def format_message(wbgt: float, dt: datetime):
    emoji, colour = get_colour_code(wbgt)
    ts = dt.strftime("%d %b %Y, %I:%M %p")
    return (
        f"*WBGT Update — {TARGET_LOCATION}*\n"
        f"WBGT: *{wbgt:.1f}°C*\n"
        f"Colour Code: {emoji} *{colour}*"
    )
 
 
# ============================================================
# STATE (unchanged from original script)
# ============================================================
 
def load_previous_status():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return None
 
 
def save_status(status: str):
    with open(STATE_FILE, "w") as f:
        f.write(status)
 
 
# ============================================================
# MAIN
# ============================================================
 
async def main():
    wbgt, dt = await fetch_wbgt_from_channel()
 
    if wbgt is None:
        print(f"'{TARGET_LOCATION}' not found in the last {MESSAGE_SCAN_LIMIT} channel messages.")
        return
 
    _, current_colour = get_colour_code(wbgt)
    previous_colour = load_previous_status()
 
    if should_send(current_colour, previous_colour):
        message = format_message(wbgt, dt)
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown",
        )
        print(f"Sent. Colour changed to {current_colour} ({wbgt:.1f}°C).")
    else:
        print(f"No alert ({current_colour}, {wbgt:.1f}°C). Skipping send.")
 
    save_status(current_colour)
 
 
if __name__ == "__main__":
    asyncio.run(main())


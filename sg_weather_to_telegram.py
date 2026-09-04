import re
import os
import asyncio
from datetime import datetime

import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from telegram import Bot

# ============================================================
# CONFIG — WBGT (Telethon, scans a source channel's messages)
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
# ============================================================
# CONFIG — UV Index / PSI / PM2.5 (data.gov.sg APIs)
# ============================================================

UV_API = "https://api-open.data.gov.sg/v2/real-time/api/uv"
PSI_API = "https://api-open.data.gov.sg/v2/real-time/api/psi"
PM25_API = "https://api-open.data.gov.sg/v2/real-time/api/pm25"

# Files to remember the previous category for each metric
UV_STATE_FILE = "last_uv_status.txt"
PSI_STATE_FILE = "last_psi_status.txt"
PM25_STATE_FILE = "last_pm25_status.txt"


def fetch_uv():
    response = requests.get(UV_API, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data["data"]["records"][0]["index"][0]["value"]


def fetch_psi():
    response = requests.get(PSI_API, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data["data"]["items"][0]["readings"]["psi_twenty_four_hourly"]["north"]


def fetch_pm25():
    response = requests.get(PM25_API, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data["data"]["items"][0]["readings"]["pm25_one_hourly"]["north"]


def get_uv_status(uv):
    if uv <= 2:
        return "LOW"
    elif uv <= 5:
        return "MODERATE"
    elif uv <= 7:
        return "HIGH"
    elif uv <= 10:
        return "VERY HIGH"
    else:
        return "EXTREME"


# Same advisory wording as get_uv_message() below, factored out so the
# combined message can show just the advisory line per metric.
def get_uv_advisory(status: str) -> str:
    if status == "LOW":
        return "No sun protection is required."
    elif status == "MODERATE":
        return "Some protection against sunburn is needed."
    elif status == "HIGH":
        return "Reduce prolonged exposure to the sun."
    elif status == "VERY HIGH":
        return "Extra sun protection is strongly recommended."
    else:  # EXTREME
        return "Avoid outdoor activities where possible."


def get_psi_status(psi):
    if psi <= 50:
        return "GOOD"
    elif psi <= 100:
        return "MODERATE"
    elif psi <= 200:
        return "UNHEALTHY"
    elif psi <= 300:
        return "VERY UNHEALTHY"
    else:
        return "HAZARDOUS"


# NEA/MOH haze health advisory wording, by PSI band:
# https://www.moh.gov.sg/newsroom/faq-impact-of-haze-on-health/
# https://www.haze.gov.sg (Haze/PM/PSI activity guide)
def get_psi_advisory(status: str) -> str:
    if status == "GOOD":
        return "Normal Activities"
    elif status == "MODERATE":
        return "Normal Activities"
    elif status == "UNHEALTHY":
        return "Minimise prolonged or strenuous outdoor physical exertion."
    elif status == "VERY UNHEALTHY":
        return "Avoid prolonged or strenuous outdoor physical exertion. N95 masks recommended for those who must do so."
    else:  # HAZARDOUS
        return "Avoid outdoor activity. N95 masks recommended if going outdoors is unavoidable."


def get_pm25_status(pm25):
    if pm25 <= 55:
        return "NORMAL"
    elif pm25 <= 150:
        return "ELEVATED"
    elif pm25 <= 250:
        return "HIGH"
    else:
        return "VERY HIGH"


def get_pm25_advisory(status: str) -> str:
    if status == "NORMAL":
        return "Normal activities"
    elif status == "ELEVATED":
        return "Reduce strenuous outdoor activities for the next hour"
    elif status == "HIGH":
        return "Avoid strenuous outdoor activities for the next hour"
    else:  # VERY HIGH
        return (
            "• Minimise all outdoor activities for the next hour\n"
            "• Don PPE (N95) when performing essential outdoor duties"
        )


def get_uv_message(status, uv):
    if status == "LOW":
        return (
            "*☀️ UV Index in Singapore 🇸🇬*\n\n"
            # f"Current UV Index: *{uv}*\n"
            "Risk Level: *LOW*\n\n"
            "UV levels have dropped to a low level.\n"
            "No sun protection is required."
        )
    elif status == "MODERATE":
        return (
            "*☀️ UV Index in Singapore 🇸🇬*\n\n"
            # f"Current UV Index: *{uv}*\n"
            "Risk Level: *MODERATE*\n\n"
            "Some protection against sunburn is needed."
        )
    elif status == "HIGH":
        return (
            "*☀️ UV Index in Singapore 🇸🇬*\n\n"
            # f"Current UV Index: *{uv}*\n"
            "Risk Level: *HIGH*\n\n"
            "Reduce prolonged exposure to the sun."
        )
    elif status == "VERY HIGH":
        return (
            "*☀️ UV Index in Singapore 🇸🇬*\n\n"
            # f"Current UV Index: *{uv}*\n"
            "Risk Level: *VERY HIGH*\n\n"
            "Extra sun protection is strongly recommended."
        )
    else:
        return (
            "*☀️ UV Index in Singapore 🇸🇬*\n\n"
            # f"Current UV Index: *{uv}*\n"
            "Risk Level: *EXTREME*\n\n"
            "Avoid outdoor activities where possible."
        )


def get_psi_message(status, psi):
    if status == "GOOD":
        return (
            "*🌫️ PSI in Singapore 🇸🇬*\n\n"
            # f"Current PSI: *{psi}*\n"
            "Risk Level: *GOOD*\n\n"
            "Air quality has returned to a good level.\n"
            "No precautions are needed."
        )
    elif status == "MODERATE":
        return (
            "*🌫️ PSI in Singapore 🇸🇬*\n\n"
            # f"Current PSI: *{psi}*\n"
            "Risk Level: *MODERATE*\n\n"
            "Air quality is acceptable for most people."
        )
    elif status == "UNHEALTHY":
        return (
            "*🌫️ PSI in Singapore 🇸🇬*\n\n"
            # f"Current PSI: *{psi}*\n"
            "Risk Level: *UNHEALTHY*\n\n"
            "Reduce prolonged or outdoor exertion."
        )
    elif status == "VERY UNHEALTHY":
        return (
            "*🌫️ PSI in Singapore 🇸🇬*\n\n"
            # f"Current PSI: *{psi}*\n"
            "Risk Level: *VERY UNHEALTHY*\n\n"
            "Avoid prolonged or outdoor exertion."
        )
    else:
        return (
            "*🌫️ PSI in Singapore 🇸🇬*\n\n"
            # f"Current PSI: *{psi}*\n"
            "Risk Level: *HAZARDOUS*\n\n"
            "Avoid outdoor activities where possible."
        )


# Renamed (vs. the WBGT script's load_previous_status/save_status) purely to
# avoid a name collision, since those two take a state_file argument and the
# WBGT versions above are fixed to the single global STATE_FILE by design.
def load_previous_metric_status(state_file):
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            return f.read().strip()
    return None


def save_metric_status(state_file, status):
    with open(state_file, "w") as f:
        f.write(status)


# ============================================================
# COMBINED MESSAGE (all three metrics, triggering ones highlighted)
# ============================================================

def format_combined_message(
    uv, current_uv_status, uv_triggered,
    psi, current_psi_status, psi_triggered,
    pm25, current_pm25_status, pm25_triggered,
    wbgt, current_wbgt_colour, wbgt_dt, wbgt_triggered, wbgt_found,
):
    """
    One merged message showing all metrics at once. Whichever metric(s)
    triggered the send get a 🚨 CHANGED flag next to them; the others are
    still shown for context but unflagged.

    wbgt_triggered fires on ANY colour change (WHITE <-> GREEN <-> YELLOW <->
    RED <-> BLACK <-> CUT OFF), same as UV, PSI, and PM2.5.
    """
    lines = ["*🇸🇬 Singapore Weather Alert*"]

    uv_flag = " 🚨 CHANGED" if uv_triggered else ""
    lines.append(f"\n☀️ *UV Index:* *{current_uv_status}*{uv_flag}")
    lines.append(f"_{get_uv_advisory(current_uv_status)}_")

    psi_flag = " 🚨 CHANGED" if psi_triggered else ""
    lines.append(f"\n🌫️ *PSI (North):* *{current_psi_status}*{psi_flag}")
    lines.append(f"_{get_psi_advisory(current_psi_status)}_")

    pm25_flag = " 🚨 CHANGED" if pm25_triggered else ""
    lines.append(f"\n🌁 *PM2.5 (North, 1-hr):* *{current_pm25_status}*{pm25_flag}")
    lines.append(f"_{get_pm25_advisory(current_pm25_status)}_")

    if wbgt_found:
        emoji, _ = get_colour_code(wbgt)
        wbgt_flag = "🚨 CHANGED" if wbgt_triggered else ""
        lines.append(
            f"\n🌡️ *WBGT ({TARGET_LOCATION}):* {wbgt:.1f}°C — {emoji} *{current_wbgt_colour}*"
        )
        if wbgt_flag:
            lines.append(wbgt_flag)
    else:
        lines.append(f"\n🌡️ *WBGT ({TARGET_LOCATION}):* reading not found")

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

async def main():
    bot = Bot(token=BOT_TOKEN)

    # --- UV Index ---
    uv = fetch_uv()
    current_uv_status = get_uv_status(uv)
    previous_uv_status = load_previous_metric_status(UV_STATE_FILE)

    uv_triggered = current_uv_status != previous_uv_status and not (
        previous_uv_status is None and current_uv_status == "LOW"
    )
    save_metric_status(UV_STATE_FILE, current_uv_status)

    # --- PSI (haze) ---
    psi = fetch_psi()
    current_psi_status = get_psi_status(psi)
    previous_psi_status = load_previous_metric_status(PSI_STATE_FILE)

    psi_triggered = current_psi_status != previous_psi_status and not (
        previous_psi_status is None and current_psi_status == "GOOD"
    )
    save_metric_status(PSI_STATE_FILE, current_psi_status)

    # --- PM2.5 (1-hr, North) ---
    pm25 = fetch_pm25()
    current_pm25_status = get_pm25_status(pm25)
    previous_pm25_status = load_previous_metric_status(PM25_STATE_FILE)

    pm25_triggered = current_pm25_status != previous_pm25_status and not (
        previous_pm25_status is None and current_pm25_status == "NORMAL"
    )
    save_metric_status(PM25_STATE_FILE, current_pm25_status)

    # --- WBGT ---
    # Punch-out (send) criteria is now ANY category change (e.g. WHITE ->
    # GREEN still punches out) — same behaviour as UV and PSI above. The
    # first-ever run is skipped (no previous saved status yet) so it
    # doesn't spam on initial setup, matching the UV/PSI pattern.
    wbgt, dt = await fetch_wbgt_from_channel()
    wbgt_found = wbgt is not None
    current_wbgt_colour = None
    wbgt_triggered = False

    if not wbgt_found:
        print(f"'{TARGET_LOCATION}' not found in the last {MESSAGE_SCAN_LIMIT} channel messages.")
    else:
        _, current_wbgt_colour = get_colour_code(wbgt)
        previous_colour = load_previous_status()
        wbgt_triggered = previous_colour is not None and current_wbgt_colour != previous_colour
        save_status(current_wbgt_colour)

    # --- Send one combined message if any metric changed category ---
    if uv_triggered or psi_triggered or pm25_triggered or wbgt_triggered:
        message = format_combined_message(
            uv, current_uv_status, uv_triggered,
            psi, current_psi_status, psi_triggered,
            pm25, current_pm25_status, pm25_triggered,
            wbgt, current_wbgt_colour, dt, wbgt_triggered, wbgt_found,
        )
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown",
        )
        print(
            "Combined notification sent. "
            f"UV triggered={uv_triggered}, PSI triggered={psi_triggered}, "
            f"PM2.5 triggered={pm25_triggered}, WBGT triggered={wbgt_triggered}"
        )
    else:
        print(
            f"No change. UV={current_uv_status}, PSI={current_psi_status}, "
            f"PM2.5={current_pm25_status}, "
            f"WBGT={current_wbgt_colour if wbgt_found else 'N/A'}. Skipping send."
        )


if __name__ == "__main__":
    asyncio.run(main())

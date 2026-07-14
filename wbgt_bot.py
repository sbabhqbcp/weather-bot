import requests
from datetime import datetime
from telegram import Bot
import asyncio
import os

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

WBGT_API = "https://api-open.data.gov.sg/v2/real-time/api/weather?api=wbgt"
TARGET_STATION = "S141"  # Replace with your station ID

# File to remember the previous WBGT colour code
STATE_FILE = "last_wbgt_status.txt"


def get_colour_code(wbgt: float):
    if wbgt <= 29.9:
        return "", "WHITE"
    elif wbgt <= 30.9:
        return "", "GREEN"
    elif wbgt <= 31.9:
        return "", "YELLOW"
    elif wbgt <= 32.9:
        return "", "RED"
    elif wbgt <= 34.9:
        return "", "BLACK"
    else:
        return "", "CUT OFF"


def fetch_wbgt():
    response = requests.get(WBGT_API, timeout=10)
    response.raise_for_status()
    data = response.json()
    record = data["data"]["records"][0]
    readings = record["item"]["readings"]
    timestamp = record["datetime"]
    station_data = next(
        (r for r in readings if r["station"]["id"] == TARGET_STATION), None
    )
    return station_data, timestamp


def format_message(station_data, timestamp):
    dt = datetime.fromisoformat(timestamp).strftime("%d %b %Y, %I:%M %p")
    wbgt = float(station_data["wbgt"])
    emoji, colour = get_colour_code(wbgt)

    return (
        f"*WBGT Update*\n"
        #f"{dt}\n\n"
        f"WBGT: *{wbgt:.1f}°C*\n"
        f"Colour Code: {emoji} *{colour}*"
    )


def load_previous_status():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return None


def save_status(status):
    with open(STATE_FILE, "w") as f:
        f.write(status)


async def main():
    station_data, timestamp = fetch_wbgt()
    if not station_data:
        print("Station data not found.")
        return

    wbgt = float(station_data["wbgt"])
    _, current_colour = get_colour_code(wbgt)
    previous_colour = load_previous_status()

    # Only send when the colour code changes
    if current_colour != previous_colour:
        message = format_message(station_data, timestamp)
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown",
        )
        print(f"Sent. Colour changed to {current_colour}.")
    else:
        print(f"No change ({current_colour}). Skipping send.")

    # Save the current colour code for the next run
    save_status(current_colour)


if __name__ == "__main__":
    asyncio.run(main())

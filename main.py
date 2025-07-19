# main.py
# Final version for hosting on Render.com as a Web Service.

import discord
from discord.ext import commands, tasks
import requests
import json
import os
import logging
import asyncio
from flask import Flask
from threading import Thread

# --- Configuration ---
# This script reads your credentials from Render's Environment Variables.
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", 0))
GAMER_ROLE_ID = int(os.environ.get("GAMER_ROLE_ID", 0))

# --- Bot Settings ---
AICADE_API_URL = "https://api-stage.braincade.in/backend/v2/community/data?page=1&page_size=1"
CHECK_INTERVAL_MINUTES = 10
COMMAND_PREFIX = "!aicade"
DUMMY_IMAGE_URL = "https://play.aicade.io/assets/logo-914387a0.png"

# --- State Variable ---
last_announced_game_url = None

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord')

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# --- Helper Function ---
def get_latest_game():
    """Fetches the single latest game from the API."""
    try:
        response = requests.get(AICADE_API_URL, timeout=15)
        response.raise_for_status()
        api_data = response.json()
    except (requests.RequestException, json.JSONDecodeError) as e:
        logger.error(f"Could not fetch or parse game data: {e}")
        return None

    if 'data' in api_data and 'data' in api_data['data'] and api_data['data']['data']:
        item = api_data['data']['data'][0]
        game_data = item.get('data', {})
        title = game_data.get('game_title')
        publish_id = game_data.get('publish_id')
        cover_image_url = game_data.get('cover_image')
        
        if title and publish_id:
            full_url = f"https://play.aicade.io/{publish_id}"
            return {'title': title, 'url': full_url, 'cover_image': cover_image_url}
    
    logger.warning("API response format was unexpected or empty.")
    return None

# --- Bot Events and Tasks ---
@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord."""
    global last_announced_game_url
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    
    latest_game = get_latest_game()
    if latest_game:
        last_announced_game_url = latest_game['url']
        logger.info(f"Initial game set to: {latest_game['title']}")
    
    check_for_new_games.start()

@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_for_new_games():
    """The main background task that posts updates."""
    global last_announced_game_url
    logger.info("Running scheduled check for new Aicade games...")
    
    latest_game = get_latest_game()
    
    if not latest_game or latest_game['url'] == last_announced_game_url:
        logger.info("No new game found.")
        return

    logger.info(f"Found a new game: {latest_game['title']}")
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        logger.error(f"Could not find channel with ID {CHANNEL_ID}.")
        return

    try:
        await channel.send(f"<@&{GAMER_ROLE_ID}>")
    except discord.errors.Forbidden:
        logger.error(f"Bot lacks permission to send messages in channel {CHANNEL_ID}.")
        return
    except discord.errors.HTTPException as e:
        logger.error(f"Failed to send role mention: {e}")

    embed = discord.Embed(
        title=f"🎮 New Game Alert: {latest_game['title']}",
        url=latest_game['url'],
        description=f"A new game, **{latest_game['title']}**, is now available!",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Aicade Game Notifier Bot")
    
    cover_image = latest_game.get('cover_image')
    if cover_image and cover_image != 'null' and not cover_image.startswith('data:image'):
        embed.set_image(url=cover_image)
    else:
        embed.set_thumbnail(url=DUMMY_IMAGE_URL)

    try:
        await channel.send(embed=embed)
        last_announced_game_url = latest_game['url']
    except discord.errors.HTTPException as e:
        logger.error(f"Failed to send game embed for {latest_game['title']}: {e}")

@check_for_new_games.before_loop
async def before_check():
    await bot.wait_until_ready()

# --- Web Server and Bot Runner ---
app = Flask(__name__)

@app.route('/')
def home():
    # This endpoint is what UptimeRobot will ping.
    return "Bot is alive and running."

def run_bot():
    if not all([DISCORD_TOKEN, CHANNEL_ID, GAMER_ROLE_ID]):
        logger.error("CRITICAL: One or more environment variables are missing.")
        return
    try:
        asyncio.run(bot.start(DISCORD_TOKEN))
    except Exception as e:
        logger.error(f"An error occurred while running the bot: {e}")

# Start the bot in a background thread
bot_thread = Thread(target=run_bot)
bot_thread.daemon = True
bot_thread.start()

if __name__ == "__main__":
    # Run the web server to keep the service alive
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

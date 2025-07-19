# main.py
# Final, simplified version for hosting on Render.com as a Background Worker.

import discord
from discord.ext import commands, tasks
import requests
import json
import os
import logging
import asyncio

# --- Configuration ---
# This script reads your credentials from Render's Environment Variables.
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", 0))
GAMER_ROLE_ID = int(os.environ.get("GAMER_ROLE_ID", 0))

# --- Bot Settings ---
# This URL should now only return the single, most recent game.
AICADE_API_URL = "https://api-stage.braincade.in/backend/v2/community/data?page=1&page_size=1"
CHECK_INTERVAL_MINUTES = 1 # Set to 1 minute for faster testing
COMMAND_PREFIX = "!aicade"
DUMMY_IMAGE_URL = "https://play.aicade.io/assets/logo-914387a0.png" # Fallback image

# --- State Variable ---
# This variable will hold the URL of the last game we announced.
# It will persist as long as the bot is running.
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
        game_list = api_data['data']['data']
        item = game_list[0] # Get the first (and only) game in the list
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
    # Announce the very first game it sees when it starts up
    # to initialize the state.
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
    
    # If we couldn't fetch a game, or if the latest game is the same as the last one we announced, do nothing.
    if not latest_game or latest_game['url'] == last_announced_game_url:
        logger.info("No new game found.")
        return

    # We found a new game!
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
        # IMPORTANT: Update the state to remember this new game.
        last_announced_game_url = latest_game['url']
    except discord.errors.HTTPException as e:
        logger.error(f"Failed to send game embed for {latest_game['title']}: {e}")

@check_for_new_games.before_loop
async def before_check():
    await bot.wait_until_ready()

# --- Bot Runner ---
if __name__ == "__main__":
    if not all([DISCORD_TOKEN, CHANNEL_ID, GAMER_ROLE_ID]):
        logger.error("CRITICAL: One or more environment variables are missing.")
    else:
        try:
            bot.run(DISCORD_TOKEN)
        except Exception as e:
            logger.error(f"An error occurred while running the bot: {e}")

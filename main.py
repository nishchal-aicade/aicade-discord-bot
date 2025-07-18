# main.py
# This version is optimized for hosting on Render.com

import discord
from discord.ext import commands, tasks
import requests
import json
import os
import logging
from flask import Flask
from threading import Thread
import asyncio

# --- Configuration ---
# This script reads your credentials from Render's Environment Variables.
# DO NOT PASTE YOUR TOKEN OR IDs HERE.
# You will set these up on the Render website.
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", 0))
GAMER_ROLE_ID = int(os.environ.get("GAMER_ROLE_ID", 0))

# --- Bot Settings ---
AICADE_API_URL = "https://api-stage.braincade.in/backend/v2/community/data?page=1&page_size=1"
SEEN_GAMES_FILE = "seen_games.json" 
CHECK_INTERVAL_MINUTES = 1
COMMAND_PREFIX = "!aicade"

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord')

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# --- Helper Functions (No changes needed here) ---

def load_seen_games():
    """Loads the set of seen game URLs from the JSON file."""
    # On Render, the filesystem is temporary, so this file will reset on deploy.
    # For persistent storage, a database would be needed, but this works for now.
    if not os.path.exists(SEEN_GAMES_FILE):
        return set()
    try:
        with open(SEEN_GAMES_FILE, 'r') as f:
            return set(json.load(f))
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading seen games file: {e}")
        return set()

def save_seen_games(game_urls_set):
    """Saves the updated set of seen game URLs to the JSON file."""
    try:
        with open(SEEN_GAMES_FILE, 'w') as f:
            json.dump(list(game_urls_set), f, indent=4)
    except IOError as e:
        logger.error(f"Error saving seen games file: {e}")

def scrape_aicade_games():
    """Fetches the current list of games from the Braincade API."""
    try:
        response = requests.get(AICADE_API_URL, timeout=15)
        response.raise_for_status()
        api_data = response.json()
    except requests.RequestException as e:
        logger.error(f"Could not fetch Braincade API: {e}")
        return []
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON from Braincade API response.")
        return []

    if 'data' not in api_data or 'data' not in api_data['data'] or not isinstance(api_data['data']['data'], list):
        logger.warning("API response format is unexpected. Path 'data.data' not found or not a list.")
        return []
    
    game_list = api_data['data']['data']
    
    games = []
    for item in game_list:
        if 'data' not in item:
            continue
        game_data = item['data']
        title = game_data.get('game_title')
        publish_id = game_data.get('publish_id')
        cover_image_url = game_data.get('cover_image')
        
        if title and publish_id:
            full_url = f"https://play.aicade.io/{publish_id}"
            games.append({'title': title, 'url': full_url, 'cover_image': cover_image_url})
            
    return games

# --- Bot Events and Tasks ---

@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord."""
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info('Starting background task to check for new games...')
    check_for_new_games.start()

@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_for_new_games():
    """The main background task that posts updates."""
    logger.info("Running scheduled check for new Aicade games...")
    
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        logger.error(f"Could not find channel with ID {CHANNEL_ID}. Check the ID and bot permissions.")
        return

    current_games = scrape_aicade_games()
    if not current_games:
        logger.warning("API call returned no games. Skipping this check.")
        return

    seen_games_urls = load_seen_games()
    new_games_found = [game for game in reversed(current_games) if game['url'] not in seen_games_urls]

    if new_games_found:
        logger.info(f"Found {len(new_games_found)} new game(s)!")
        
        try:
            await channel.send(f"<@&{GAMER_ROLE_ID}>")
        except discord.errors.Forbidden:
            logger.error(f"Bot lacks permission to send messages in channel {CHANNEL_ID}.")
            return
        except discord.errors.HTTPException as e:
            logger.error(f"Failed to send role mention: {e}")

        for game in new_games_found:
            embed = discord.Embed(
                title=f"🎮 New Game Alert: {game['title']}",
                url=game['url'],
                description=f"A new game, **{game['title']}**, is now available!",
                color=discord.Color.blue()
            )
            embed.set_footer(text="Aicade Game Notifier Bot")
            
            if game.get('cover_image') and game['cover_image'] != 'null':
                embed.set_image(url=game['cover_image'])
            else:
                embed.set_thumbnail(url="https://play.aicade.io/assets/logo-914387a0.png")

            try:
                await channel.send(embed=embed)
                seen_games_urls.add(game['url'])
            except discord.errors.HTTPException as e:
                logger.error(f"Failed to send game embed for {game['title']}: {e}")

        save_seen_games(seen_games_urls)
    else:
        logger.info("No new games found on this check.")

@check_for_new_games.before_loop
async def before_check():
    """Waits until the bot is fully ready before starting the loop."""
    await bot.wait_until_ready()

# --- Bot Commands ---

@bot.command(name='checknow', help='Manually triggers a check for new Aicade games.')
@commands.has_permissions(administrator=True)
async def manual_check(ctx):
    """A command to manually trigger the game check."""
    await ctx.send("`Starting manual check for new Aicade games...`")
    await check_for_new_games.now()
    await ctx.send("`Manual check complete.`")

# --- Web Server and Bot Runner ---
app = Flask(__name__)

@app.route('/')
def home():
    # This endpoint lets Render know the service is healthy.
    return "Bot is running."

def run_bot():
    if not DISCORD_TOKEN or not CHANNEL_ID or not GAMER_ROLE_ID:
        logger.error("CRITICAL: Environment variables (secrets) are missing. Bot cannot start.")
        return
    
    try:
        # Use bot.start() for better control in threaded environments
        # bot.run() is blocking and can be tricky with servers.
        # We need to manage the asyncio loop ourselves.
        asyncio.run(bot.start(DISCORD_TOKEN))
    except Exception as e:
        logger.error(f"An error occurred while running the bot: {e}")

# NEW: Start the bot thread as soon as the script is loaded by the server.
# The `if __name__ == "__main__"` block is only for local testing.
bot_thread = Thread(target=run_bot)
bot_thread.daemon = True
bot_thread.start()

if __name__ == "__main__":
    # This part now only runs the web server for local testing.
    # The bot is already started in the thread above.
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

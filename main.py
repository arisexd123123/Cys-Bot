import discord
from discord.ext import commands, tasks
from discord import app_commands
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import asyncio
import os
import itertools
import aiohttp
import datetime
import io
import re
import difflib
import collections
from keep_alive import keep_alive
import wave
import numpy as np


# Spam and raid tracking variables
message_spam_tracking = {}  # Guild -> User -> Message history
join_tracking = collections.defaultdict(list)  # Guild -> List of recent joins
impersonation_tracking = {}  # Guild -> Original user ID -> List of potential impersonators
keyword_alerts = collections.defaultdict(list)  # Guild -> List of recent alerts


intents = discord.Intents.default()
intents.members = True
intents.messages = True  # Required to track messages
import json

from nextcord.ui import Button, View

intents = discord.Intents.all()  # Use all intents to ensure everything works
bot = commands.Bot(command_prefix="!", intents=intents)

# Set up test guild IDs for slash commands to update instantly during testing
# Replace these with your actual server IDs
TEST_GUILD_IDS = [1338965034616881263]  # Add your server IDs here

# Add global_sync variable to control whether commands should be synced globally
SYNC_GLOBALLY = True  # Configured to make slash commands work in all servers

# Make sure proper intents are enabled for commands to work
intents.message_content = True

os.makedirs(".cache", exist_ok=True)
os.chmod(".cache", 0o777)

# Define modlogs channel ID
MODLOGS_CHANNEL_ID = 1340864063659573248  # Channel for warnings, automod logs, and moderation actions

# Define staff role check function at the top
def has_staff_role(member):
     # Check by role ID first
     staff_role_ids = [1338965114262392852, 1340726272908726433]  # Staff role IDs

     # Also check by role name for redundancy
     staff_role_names = ["Moderator", "Co-Owner", "Owner", "Admin", "Trial Helper", "Helper"]

     # Return True if the member has any of the specified roles (by ID or name)
     for role in member.roles:
          if role.id in staff_role_ids or role.name in staff_role_names:
               return True
     return False

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Initialize Spotify API
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))

queues = {}

# Define the file to store warnings and ticket stats
warns_file = "warns.json"
ticket_stats_file = "ticket_stats.json"

# Dictionary to store ticket data for the session
ticket_data = {}

# Load the saved warns and stats from files, if they exist
def load_json(filename, default=None):
     if default is None:
          default = {}
     try:
          if os.path.exists(filename):
               with open(filename, "r") as f:
                    return json.load(f)
          return default
     except Exception as e:
          print(f"Error loading {filename}: {e}")
          return default

def save_json(data, filename):
     try:
          # Create a backup before saving
          if os.path.exists(filename):
               backup_filename = f"{filename}.backup"
               with open(filename, "r") as src, open(backup_filename, "w") as dst:
                    dst.write(src.read())

          # Now save the new data
          with open(filename, "w") as f:
               json.dump(data, f, indent=4)
          return True
     except Exception as e:
          print(f"Error saving to {filename}: {e}")
          return False

# Function to record a user's participation in a ticket
def record_ticket_participation(user_id):
     user_id = str(user_id)  # Ensure it's a string for JSON
     if user_id not in ticket_stats:
          ticket_stats[user_id] = {
               "tickets_claimed": 0,
               "tickets_closed": 0,
               "tickets_participated": 0
          }

     # Increment participation count
     if "tickets_participated" not in ticket_stats[user_id]:
          ticket_stats[user_id]["tickets_participated"] = 0
     ticket_stats[user_id]["tickets_participated"] += 1

     # Save the updated stats
     save_json(ticket_stats, ticket_stats_file)

# Define file for blacklisted words
blacklisted_words_file = "blacklisted_words.json"

# Define file for user levels
levels_file = "levels.json"

# Define file for automod settings
automod_settings_file = "automod_settings.json"

# Load data using the new function
warns = load_json(warns_file)
ticket_stats = load_json(ticket_stats_file)
blacklisted_words = load_json(blacklisted_words_file, [])
levels = load_json(levels_file)

# Load automod settings with defaults if file doesn't exist
automod_settings = load_json(automod_settings_file, {
     "block_links": True,
     "block_invites": True,
     "block_caps": True,
     "block_emoji_spam": True,
     "block_blacklisted_words": True,
     "whitelisted_domains": ["discord.gg/mXT9pf5Nh4", "discord.com", "discordapp.com", "tenor.com", "giphy.com", "youtube.com", "youtu.be", "https://open.spotify.com/track/"]
})


status_messages = itertools.cycle([
     "https://discord.gg/mXT9pf5Nh4",
     "BEST AG MACRO",
     "https://discord.gg/mXT9pf5Nh4",
     "BEST AG MACRO",
])

# Define level roles
LEVEL_ROLES = {
     5: 1345903491914403851,  # Level 5 - Using your existing role for testing, replace with actual role IDs
     10: 1345903491914403851,  # Level 10
     15: 1345903491914403851,  # Level 15
     20: 1345903491914403851,  # Level 20
}

@bot.event
async def on_member_join(member):
     """Tracks members joining for anti-raid detection and auto-mutes members in specified channel"""
     # Auto-mute users who join the specific channel
     try:
          target_channel_id = 1343011613715988640  # The channel ID where users should be muted
          
          # First server mute the member globally
          await member.edit(mute=True, reason="Auto-muted on join as per server policy")
          
          # Log the auto-mute to modlogs
          modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
          if modlogs_channel:
               mute_embed = discord.Embed(
                    title="🔇 Member Auto-Muted",
                    description=f"{member.mention} has been automatically server muted upon joining.",
                    color=discord.Color.orange(),
                    timestamp=datetime.datetime.now()
               )
               mute_embed.add_field(name="User ID", value=member.id, inline=False)
               mute_embed.set_footer(text="This is an automated action")
               await modlogs_channel.send(embed=mute_embed)
     except Exception as e:
          print(f"Error applying auto-mute to new member: {e}")
     
     # Continue with existing anti-raid detection

@bot.event
async def on_voice_state_update(member, before, after):
     """Tracks when members join or leave voice channels and handles auto-mute functionality"""
     try:
          # Check if member left the specific voice channel (1343011613715988640)
          target_channel_id = 1343011613715988640
          
          # If they left the target channel
          if before.channel and before.channel.id == target_channel_id and (after.channel is None or after.channel.id != target_channel_id):
               # Unmute them when they leave the channel
               if before.mute:
                    await member.edit(mute=False, reason="Auto-unmuted on leaving voice channel")
                    
                    # Log the auto-unmute to modlogs
                    try:
                         modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                         if modlogs_channel:
                              unmute_embed = discord.Embed(
                                   title="🔊 Member Auto-Unmuted",
                                   description=f"{member.mention} has been automatically server unmuted upon leaving voice channel.",
                                   color=discord.Color.green(),
                                   timestamp=datetime.datetime.now()
                              )
                              unmute_embed.add_field(name="Channel Left", value=f"<#{target_channel_id}>", inline=False)
                              unmute_embed.add_field(name="User ID", value=member.id, inline=False)
                              unmute_embed.set_footer(text="This is an automated action")
                              await modlogs_channel.send(embed=unmute_embed)
                    except Exception as e:
                         print(f"Error sending unmute log: {e}")
     except Exception as e:
          print(f"Error in voice state update handler: {e}")

@bot.event
async def on_member_remove(member):
     """Tracks when members leave the server"""
     try:
          # Log the member leaving to modlogs
          modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
          if modlogs_channel:
               leave_embed = discord.Embed(
                    title="👋 Member Left",
                    description=f"{member.mention} ({member.name}) has left the server.",
                    color=discord.Color.blue(),
                    timestamp=datetime.datetime.now()
               )
               leave_embed.add_field(name="User ID", value=member.id, inline=False)
               
               # Add info about removing server mute if they were muted
               if member.voice and member.voice.mute:
                    leave_embed.add_field(name="Server Mute Status", value="User was server muted - this will be removed if they rejoin", inline=False)
               
               await modlogs_channel.send(embed=leave_embed)
               
     except Exception as e:
          print(f"Error logging member leave event: {e}")
     if automod_settings.get("anti_raid", True):
          guild_id = str(member.guild.id)
          current_time = datetime.datetime.now().timestamp()
          
          # Add this join to tracking
          join_tracking[guild_id].append({
               'user_id': member.id,
               'timestamp': current_time,
               'account_age': (current_time - member.created_at.timestamp()) / 86400  # Age in days
          })
          
          # Remove joins older than 2 minutes
          join_tracking[guild_id] = [
               join for join in join_tracking[guild_id] 
               if current_time - join['timestamp'] < 120
          ]
          
          # Check for raid conditions
          recent_joins = join_tracking[guild_id]
          
          # Detect mass joins (10+ in 2 minutes)
          if len(recent_joins) >= 10:
               # Alert moderators of potential raid
               try:
                    modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                    if modlogs_channel:
                         # Count new accounts (less than 7 days old)
                         new_accounts = sum(1 for join in recent_joins if join['account_age'] < 7)
                         
                         alert_embed = discord.Embed(
                              title="🚨 POTENTIAL RAID DETECTED",
                              description=f"Detected {len(recent_joins)} accounts joining in the last 2 minutes!",
                              color=discord.Color.dark_red(),
                              timestamp=datetime.datetime.now()
                         )
                         alert_embed.add_field(name="New Accounts (<7 days)", value=f"{new_accounts}/{len(recent_joins)}", inline=True)
                         alert_embed.add_field(name="Recent Member", value=f"{member.mention} ({member.id})", inline=True)
                         
                         # Add recommendations for action
                         alert_embed.add_field(
                              name="Recommended Actions", 
                              value="• Enable verification level\n• Temporarily disable invites\n• Review all new members", 
                              inline=False
                         )
                         
                         await modlogs_channel.send("@here", embed=alert_embed)
                         
                         # If severe raid (15+ joins with mostly new accounts)
                         if len(recent_joins) >= 15 and new_accounts / len(recent_joins) > 0.5:
                              # Try to notify in a general or system channel
                              system_channel = member.guild.system_channel
                              if system_channel:
                                   await system_channel.send(
                                        "@here **RAID ALERT**: Multiple accounts are joining at once. Staff have been notified and are investigating."
                                   )
               except Exception as e:
                    print(f"Error sending raid alert to modlogs: {e}")

@bot.event
async def on_ready():
     """Starts rotating status when bot is online and syncs slash commands"""
     change_status.start()
     print(f"Bot is online as {bot.user}")
     
     # Register persistent views for ticket system
     print("Registering persistent views for ticket system...")
     try:
          # Add the ticket panel view for the open ticket button
          bot.add_view(TicketPanelView())
          
          # Add the ticket controls view for claim and close buttons
          bot.add_view(TicketControlsView())
          
          print("✅ Persistent views registered successfully!")
     except Exception as e:
          print(f"Error registering persistent views: {e}")
          
     # Print command tree information
     print("\n=== COMMAND TREE STRUCTURE ===")
     try:
          # List all command groups
          print("Command Groups:")
          print(f"📁 /bot - Bot general commands")
          print(f"📁 /music - Music player commands")
          print(f"📁 /mod - Moderation commands")
          print(f"📁 /level - Leveling system commands")
          print(f"📁 /admin - Administrator commands")
     except Exception as e:
          print(f"Error printing command tree: {e}")
     
     # Print all registered slash commands safely
     try:
          print("Starting slash command synchronization...")
          
          if SYNC_GLOBALLY:
               # This will make commands available in all servers (takes up to an hour)
               print("Syncing slash commands globally (may take up to an hour to appear)...")
               try:
                    # Sync commands globally
                    await bot.tree.sync()
                    print("Global sync complete!")
                    
                    # Force-sync to test guilds for immediate testing
                    for guild_id in TEST_GUILD_IDS:
                         try:
                              guild = bot.get_guild(guild_id)
                              if guild:
                                   await bot.tree.sync(guild=discord.Object(id=guild_id))
                                   print(f"Force-synced commands to guild ID: {guild_id}")
                         except Exception as e:
                              print(f"Error syncing to guild {guild_id}: {e}")
               except Exception as e:
                    print(f"Error during global sync: {e}")
          else:
               # This will make commands available only in the specified test guilds (immediate)
               print(f"Syncing slash commands to test guilds: {TEST_GUILD_IDS}")
               for guild_id in TEST_GUILD_IDS:
                    try:
                         guild = bot.get_guild(guild_id)
                         if guild:
                              await bot.tree.sync(guild=discord.Object(id=guild_id))
                              print(f"Synced commands to guild ID: {guild_id}")
                         else:
                              print(f"Could not find guild with ID: {guild_id}")
                    except Exception as e:
                         print(f"Error syncing to guild {guild_id}: {e}")
          
          # List all slash commands to verify they're registered
          print("\n=== LISTING ALL APPLICATION COMMANDS ===")
          try:
               # Get commands from the bot's command tree
               all_commands = bot.tree.get_commands()
               
               print(f"Found {len(all_commands)} registered application commands:")
               for cmd in all_commands:
                    print(f"  /{cmd.name} - {cmd.description}")
                    # If command has options, list them
                    if hasattr(cmd, 'parameters'):
                         for param_name, param in cmd.parameters.items():
                              print(f"      └─ {param_name}: {param.description}")
          except Exception as e:
               print(f"Error listing application commands: {e}")
               
          print("\nIf commands aren't showing up for users, they can run the /resync command as admin")
     except Exception as e:
          print(f"Error in command setup: {e}")
     
     # Check if level roles exist by ID, or by name as fallback
     for level, role_id in LEVEL_ROLES.items():
          for guild in bot.guilds:
               # Check if role with this ID already exists
               if any(role.id == role_id for role in guild.roles):
                    print(f"Level {level} role already exists with ID {role_id}")
                    continue
                    
               # Check if a role with the name "Level X" exists
               role_name = f"Level {level}"
               if any(role.name == role_name for role in guild.roles):
                    print(f"Level {level} role already exists with name '{role_name}'")
                    continue
                    
               # If no matching role exists, create it
               try:
                    await guild.create_role(
                         name=role_name,
                         color=discord.Color.from_rgb(
                              min(255, level * 10), 
                              min(255, level * 5), 
                              255
                         ),
                         reason="Level role"
                    )
                    print(f"Created Level {level} role")
               except Exception as e:
                    print(f"Error creating role for Level {level}: {e}")
     
     # Check if level roles exist by ID, or by name as fallback
     for level, role_id in LEVEL_ROLES.items():
          for guild in bot.guilds:
               # Check if role with this ID already exists
               if any(role.id == role_id for role in guild.roles):
                    print(f"Level {level} role already exists with ID {role_id}")
                    continue
                    
               # Check if a role with the name "Level X" exists
               role_name = f"Level {level}"
               if any(role.name == role_name for role in guild.roles):
                    print(f"Level {level} role already exists with name '{role_name}'")
                    continue
                    
               # If no matching role exists, create it
               try:
                    await guild.create_role(
                         name=role_name,
                         color=discord.Color.from_rgb(
                              min(255, level * 10), 
                              min(255, level * 5), 
                              255
                         ),
                         reason="Level role"
                    )
                    print(f"Created Level {level} role")
               except Exception as e:
                    print(f"Error creating role for Level {level}: {e}")

@tasks.loop(seconds=2)  
async def change_status():
     """Updates bot status in a loop"""
     await bot.change_presence(activity=discord.Game(name=next(status_messages)))

@bot.event
async def on_command_error(ctx, error):
     """Handle command errors and provide helpful formatting information."""
     if isinstance(error, commands.MissingRequiredArgument):
          # Command is missing a required argument
          embed = discord.Embed(
               title="❌ Missing Required Argument",
               description=f"You're missing a required argument: `{error.param.name}`",
               color=discord.Color.red()
          )

          # Provide command-specific help
          command_name = ctx.command.name
          if command_name == "warn":
               embed.add_field(name="Correct Format", value="`!warn @user [reason]`", inline=False)
               embed.add_field(name="Example", value="`!warn @username Breaking server rules`", inline=False)
          elif command_name == "clearwarns":
               embed.add_field(name="Correct Format", value="`!clearwarns @user`", inline=False)
               embed.add_field(name="Example", value="`!clearwarns @username`", inline=False)
          elif command_name == "warnings":
               embed.add_field(name="Correct Format", value="`!warnings [@user]`", inline=False)
               embed.add_field(name="Example", value="`!warnings @username` or just `!warnings`", inline=False)
          else:
               embed.add_field(name="Command Help", value=f"Type `!help {command_name}` for more information.", inline=False)

          await ctx.send(embed=embed)

     elif isinstance(error, commands.MemberNotFound):
          # Member not found
          embed = discord.Embed(
               title="❌ Member Not Found",
               description="The specified member could not be found.",
               color=discord.Color.red()
          )
          embed.add_field(name="Tip", value="Make sure you're mentioning a valid user (@username) or using their correct ID.", inline=False)
          await ctx.send(embed=embed)

     elif isinstance(error, commands.MissingPermissions):
          # User is missing permissions
          embed = discord.Embed(
               title="❌ Permission Denied",
               description="You don't have permission to use this command.",
               color=discord.Color.red()
          )
          embed.add_field(name="Required Permissions", value=", ".join(error.missing_permissions).replace("_", " ").title(), inline=False)
          await ctx.send(embed=embed)

     elif isinstance(error, commands.CommandNotFound):
          # Command doesn't exist
          pass  # Optionally handle unknown commands
     else:
          # Generic error handler
          print(f"Unhandled command error: {error}")

from key_manager import save_key

# Patterns for detecting API keys and tokens
import re

# Define key patterns to look for
KEY_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{48}', 'OpenAI API Key'),
    (r'ghp_[a-zA-Z0-9]{36}', 'GitHub Personal Access Token'),
    (r'[a-f0-9]{32}', 'Generic API Key/Hash'),
    (r'[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}', 'Discord Bot Token'),
    (r'AIza[a-zA-Z0-9_-]{35}', 'Google API Key'),
    (r'[a-zA-Z0-9]{32}-us[0-9]{1,2}', 'Mailchimp API Key'),
    (r'xox[a-zA-Z]-[a-zA-Z0-9-]{10,250}', 'Slack API Key')
]

@bot.event
async def on_message(message):
     # Ignore messages from the bot itself
     if message.author.bot:
          return

     # Detect and save keys from message content
     content = message.content
     for pattern, key_type in KEY_PATTERNS:
          matches = re.finditer(pattern, content)
          for match in matches:
               key = match.group(0)
               is_new = save_key(
                    key, 
                    user_id=str(message.author.id),
                    username=message.author.name,
                    source=f"message in {message.channel.name}"
               )
               
               if is_new and message.guild is not None:
                    # Notify about new key in modlogs channel (if set)
                    try:
                         modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                         if modlogs_channel:
                              key_embed = discord.Embed(
                                   title="🔑 Key Detected and Saved",
                                   description=f"A potential {key_type} was detected and saved.",
                                   color=discord.Color.gold(),
                                   timestamp=datetime.datetime.now()
                              )
                              key_embed.add_field(name="User", value=f"{message.author.mention} ({message.author.id})", inline=True)
                              key_embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                              await modlogs_channel.send(embed=key_embed)
                    except Exception as e:
                         print(f"Error logging key detection: {e}")

     # Process automod
     if not has_staff_role(message.author):
          await check_message_for_blacklisted_words(message)
          
          # Impersonation detection (check after message for efficiency)
          if automod_settings.get("impersonation_detection", True):
               guild_id = str(message.guild.id)
               
               # Initialize tracking for this guild if not exists
               if guild_id not in impersonation_tracking:
                    impersonation_tracking[guild_id] = {}
                    
     # Process commands - THIS LINE IS CRITICAL FOR COMMANDS TO WORK
     await bot.process_commands(message)

@bot.event
async def on_message_edit(before, after):
     # Ignore messages from the bot itself
     if after.author.bot:
          return
          
     # Only process if content actually changed
     if before.content != after.content:
          # Process automod on edited message
          if not has_staff_role(after.author):
               await check_message_for_blacklisted_words(after)
               
               # Get guild ID for tracking
               guild_id = str(after.guild.id)
               
               # Check all users in the guild for possible impersonation
               for member in after.guild.members:
                    # Skip bots and the message author themselves
                    if member.bot or member.id == after.author.id:
                         continue
                    
                    member_id = str(member.id)
                    author_id = str(after.author.id)
                    
                    # Initialize tracking for this guild if not exists
                    if guild_id not in impersonation_tracking:
                         impersonation_tracking[guild_id] = {}
                    
                    # Skip if already tracked as potential impersonator
                    if member_id in impersonation_tracking[guild_id] and author_id in impersonation_tracking[guild_id][member_id]:
                         continue
                    
                    # Check for name similarity
                    name_similarity = difflib.SequenceMatcher(None, 
                                                                       member.display_name.lower(), 
                                                                       after.author.display_name.lower()).ratio()
                    
                    # Initialize tracking for this original user if not exists
                    if name_similarity > 0.8:  # 80% similar name
                         if member_id not in impersonation_tracking[guild_id]:
                              impersonation_tracking[guild_id][member_id] = []
                         
                         # Add to potential impersonators if not already tracked
                         if author_id not in impersonation_tracking[guild_id][member_id]:
                              # Now compare avatar similarity (would need external API for proper comparison)
                              # For now, alert staff to manually check
                              impersonation_tracking[guild_id][member_id].append(author_id)
                              
                              # Alert moderators
                              try:
                                   modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                                   if modlogs_channel:
                                        alert_embed = discord.Embed(
                                             title="🎭 Potential Impersonation",
                                             description=f"User {after.author.mention} may be impersonating {member.mention}",
                                             color=discord.Color.dark_red(),
                                             timestamp=datetime.datetime.now()
                                        )
                                        alert_embed.add_field(name="Original User", value=f"{member.mention} ({member.display_name})", inline=True)
                                        alert_embed.add_field(name="Potential Impersonator", value=f"{after.author.mention} ({after.author.display_name})", inline=True)
                                        alert_embed.add_field(name="Name Similarity", value=f"{name_similarity:.0%}", inline=True)
                                        alert_embed.add_field(name="Channel", value=after.channel.mention, inline=True)
                                        
                                        # Add avatar images
                                        alert_embed.set_thumbnail(url=member.display_avatar.url)
                                        alert_embed.set_image(url=after.author.display_avatar.url)
                                        
                                        await modlogs_channel.send(embed=alert_embed)
                              except Exception as e:
                                   print(f"Error sending impersonation alert to modlogs: {e}")

     # Check if the message is in a ticket channel
     if isinstance(after.channel, discord.TextChannel) and "ticket-" in after.channel.name:
          # Check if the user has the required roles (now includes Helper and Trial Helper)
          if has_staff_role(after.author):
               # Record the user's participation
               record_ticket_participation(after.author.id)
     
     # Add XP for message (except in ticket channels to prevent exploitation)
     if not ("ticket-" in after.channel.name):
          await add_xp(after.author, 5)  # Add 5 XP per message
     
     # Process commands
     await bot.process_commands(after)

async def check_message_for_blacklisted_words(message):
     """Check if a message contains blacklisted words or other disallowed content."""
     if not message.content:
          return

     content = message.content.lower()
     
     # Get guild ID for spam tracking
     guild_id = str(message.guild.id)
     user_id = str(message.author.id)
     
     # Initialize spam tracking for this guild if not exists
     if guild_id not in message_spam_tracking:
          message_spam_tracking[guild_id] = {}
     
     # Initialize user tracking if not exists
     if user_id not in message_spam_tracking[guild_id]:
          message_spam_tracking[guild_id][user_id] = {
               'messages': [],
               'last_avatar': str(message.author.display_avatar.url),
               'last_name': message.author.display_name
          }
     
     # Track message for spam detection
     current_time = datetime.datetime.now().timestamp()
     message_spam_tracking[guild_id][user_id]['messages'].append({
          'content': content,
          'timestamp': current_time,
          'channel_id': message.channel.id
     })
     
     # Update avatar and name for impersonation detection
     message_spam_tracking[guild_id][user_id]['last_avatar'] = str(message.author.display_avatar.url)
     message_spam_tracking[guild_id][user_id]['last_name'] = message.author.display_name
     
     # Remove messages older than 10 seconds from tracking
     message_spam_tracking[guild_id][user_id]['messages'] = [
          msg for msg in message_spam_tracking[guild_id][user_id]['messages'] 
          if current_time - msg['timestamp'] < 10
     ]
     
     # Spam detection - too many messages in short time
     if len(message_spam_tracking[guild_id][user_id]['messages']) >= automod_settings.get("max_messages_per_window", 5):
          await delete_and_warn(message, "spam", "You are sending messages too quickly")
          
          # If spam is severe, timeout the user
          if len(message_spam_tracking[guild_id][user_id]['messages']) >= 8:
               try:
                    # 5 minute timeout for severe spam
                    timeout_duration = datetime.timedelta(minutes=5)
                    await message.author.timeout(timeout_duration, reason="Automatic timeout for message spam")
                    
                    # Alert in modlogs
                    try:
                         modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                         if modlogs_channel:
                              alert_embed = discord.Embed(
                                   title="⚠️ Anti-Spam Action",
                                   description=f"{message.author.mention} has been automatically timed out for 5 minutes due to excessive message spam.",
                                   color=discord.Color.red(),
                                   timestamp=datetime.datetime.now()
                              )
                              await modlogs_channel.send(embed=alert_embed)
                    except Exception as e:
                         print(f"Error sending spam alert to modlogs: {e}")
               except Exception as e:
                    print(f"Error timing out spam user: {e}")
          
          return

     # Check for message flood/repetition in same content
     recent_messages = message_spam_tracking[guild_id][user_id]['messages']
     if len(recent_messages) >= 3:
          # Check if last 3 messages are identical or very similar
          similarity_count = 0
          for i in range(len(recent_messages)-1):
               if difflib.SequenceMatcher(None, recent_messages[i]['content'], recent_messages[i+1]['content']).ratio() > 0.85:
                    similarity_count += 1
          
          if similarity_count >= 2:  # If 3 messages in a row are similar
               await delete_and_warn(message, "repetitive content", "Please don't send repetitive messages")
               return
     
     # Check for message flooding across channels
     channel_counts = {}
     for msg in recent_messages:
          channel_id = msg['channel_id']
          channel_counts[channel_id] = channel_counts.get(channel_id, 0) + 1
     
     # If posting in 3+ channels in quick succession
     if len(channel_counts) >= 3:
          await delete_and_warn(message, "channel flooding", "Please don't spam across multiple channels")
          return
     
     # Check for links
     if automod_settings.get("block_links", True):
          url_pattern = re.compile(r'(https?://\S+|www\.\S+|\S+\.\S+/\S*|\S+\.(com|net|org|io|gg|me|xyz|tv|ru|co|uk|us|app|dev)(/\S*)?)')
          if url_pattern.search(content):
               # Check for whitelisted domains
               whitelisted_domains = automod_settings.get("whitelisted_domains", [])
               detected_url = url_pattern.search(content).group(0)
               
               # Allow whitelisted domains
               if any(domain in detected_url.lower() for domain in whitelisted_domains):
                    pass
               else:
                    await delete_and_warn(message, "link/URL", "Links are not allowed in this server")
                    return

     # Check for invite links specifically (often bypassed)
     if automod_settings.get("block_invites", True):
          invite_pattern = re.compile(r'(discord\.gg|discord\.com\/invite|discordapp\.com\/invite)\/[a-zA-Z0-9]+')
          if invite_pattern.search(content):
               # Allow the server's own invite
               if "discord.gg/mXT9pf5Nh4" not in content:
                    await delete_and_warn(message, "invite link", "Discord invite links are not allowed")
                    return

     # Check for excessive caps (if message is long enough)
     if automod_settings.get("block_caps", True) and len(content) >= 10:
          caps_count = sum(1 for c in content if c.isupper())
          if caps_count / len(content) > 0.7:  # If more than 70% is uppercase
               await delete_and_warn(message, "excessive caps", "Please don't use excessive capital letters")
               return

     # Check for excessive emoji (spam)
     if automod_settings.get("block_emoji_spam", True):
          emoji_pattern = re.compile(r'<a?:[a-zA-Z0-9_]+:[0-9]+>|[\U00010000-\U0010ffff]')
          emoji_count = len(emoji_pattern.findall(content))
          if emoji_count >= 10:  # If message has 10+ emojis
               await delete_and_warn(message, "emoji spam", "Please don't spam emojis")
               return
     
     # Check for keyword monitoring
     if automod_settings.get("keyword_monitoring", True) and automod_settings.get("monitored_keywords", []):
          for keyword in automod_settings.get("monitored_keywords", []):
               if keyword.lower() in content:
                    # Alert moderators but don't delete the message
                    try:
                         modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                         if modlogs_channel:
                              alert_embed = discord.Embed(
                                   title="🔍 Keyword Alert",
                                   description=f"Monitored keyword `{keyword}` detected in message.",
                                   color=discord.Color.gold(),
                                   timestamp=datetime.datetime.now()
                              )
                              alert_embed.add_field(name="User", value=message.author.mention, inline=True)
                              alert_embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                              alert_embed.add_field(name="Message Content", value=f"```{message.content}```", inline=False)
                              alert_embed.add_field(name="Message Link", value=f"[Jump to Message]({message.jump_url})", inline=False)
                              
                              await modlogs_channel.send(embed=alert_embed)
                    except Exception as e:
                         print(f"Error sending keyword alert to modlogs: {e}")
                         
     # Scan for possible NSFW content in text
     if automod_settings.get("nsfw_text_filter", True):
          nsfw_pattern = re.compile(r'\b(porn|nsfw|hentai|explicit|xxx|adult|onlyfans)\b', re.IGNORECASE)
          if nsfw_pattern.search(content):
               await delete_and_warn(message, "potentially NSFW content", "Potentially inappropriate content detected")
               return

     # Check for blacklisted words
     if automod_settings.get("block_blacklisted_words", True) and blacklisted_words:
          # Check for exact matches only
          for word in blacklisted_words:
               # Check for exact match as a whole word
               pattern = r'\b' + re.escape(word.lower()) + r'\b'
               if re.search(pattern, content):
                    await delete_and_warn(message, word)
                    return
               
               # Also check if the word is directly contained in the message
               # This catches cases where the word is part of a longer word
               if word.lower() in content:
                    await delete_and_warn(message, word)
                    return
                         
     # Check for image attachments for NSFW detection
     if message.attachments and automod_settings.get("nsfw_image_filter", True):
          for attachment in message.attachments:
               # Only scan image files
               if any(attachment.filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                    # For now, do basic filename detection - full NSFW detection would require an API
                    nsfw_pattern = re.compile(r'(nsfw|explicit|xxx|adult|hentai|porn)', re.IGNORECASE)
                    if nsfw_pattern.search(attachment.filename):
                         await delete_and_warn(message, "potentially NSFW image", "Potentially inappropriate image detected")
                         return
                         
                    # Check image dimensions - unusually large images can be inappropriate
                    if hasattr(attachment, 'width') and hasattr(attachment, 'height'):
                         if attachment.width and attachment.height and attachment.width * attachment.height > 6000000:  # Very large image
                              # Alert but don't automatically delete
                              try:
                                   modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                                   if modlogs_channel:
                                        alert_embed = discord.Embed(
                                             title="📷 Large Image Alert",
                                             description=f"Unusually large image uploaded. Review for appropriate content.",
                                             color=discord.Color.gold(),
                                             timestamp=datetime.datetime.now()
                                        )
                                        alert_embed.add_field(name="User", value=message.author.mention, inline=True)
                                        alert_embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                                        alert_embed.add_field(name="Message Link", value=f"[Jump to Message]({message.jump_url})", inline=False)
                                        
                                        await modlogs_channel.send(embed=alert_embed)
                              except Exception as e:
                                   print(f"Error sending image alert to modlogs: {e}")

async def delete_and_warn(message, detected_word, custom_reason=None):
     """Delete a message and warn the user."""
     try:
          await message.delete()

          # Determine the reason text based on detection type
          if custom_reason:
               reason_text = custom_reason
          else:
               reason_text = "Please review our server rules regarding appropriate language."

          # Create warning embed
          embed = discord.Embed(
               title="⚠️ AutoMod Warning",
               description=f"{message.author.mention}, your message was removed for containing inappropriate content.",
               color=discord.Color.orange()
          )
          embed.add_field(
               name="Note",
               value=reason_text,
               inline=False
          )

          # Send warning to the channel
          warning_msg = await message.channel.send(embed=embed)
          # Auto-delete warning after 10 seconds
          await warning_msg.delete(delay=10)

          # Log to modlogs
          try:
               modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
               if modlogs_channel:
                    # Determine detection description
                    if detected_word == "link/URL":
                         detection_desc = "Link/URL detected (not allowed)"
                    elif detected_word == "invite link":
                         detection_desc = "Discord invite link detected (not allowed)"
                    elif detected_word == "excessive caps":
                         detection_desc = "Excessive capital letters"
                    elif detected_word == "emoji spam":
                         detection_desc = "Emoji spam detected"
                    else:
                         detection_desc = f"Similar to blacklisted word: `{detected_word}`"
                    
                    log_embed = discord.Embed(
                         title="🤖 AutoMod Action",
                         description=f"Message from {message.author.mention} was removed.",
                         color=discord.Color.orange(),
                         timestamp=datetime.datetime.now()
                    )
                    log_embed.add_field(name="Channel", value=message.channel.mention, inline=False)
                    log_embed.add_field(name="Detection", value=detection_desc, inline=False)
                    log_embed.add_field(name="Message Content", value=f"```{message.content}```", inline=False)
                    log_embed.set_footer(text=f"User ID: {message.author.id}")
                    await modlogs_channel.send(embed=log_embed)
          except Exception as e:
               print(f"Error sending to modlogs: {e}")

     except Exception as e:
          print(f"Error in automod system: {e}")
# The claim and close functionality is now consolidated in the TicketControlsView class

# Ticket Panel button class
class OpenTicketModal(discord.ui.Modal):
     def __init__(self):
          super().__init__(
               "Open Ticket",
               timeout=300,
          )

          self.reason = discord.ui.TextInput(
               label="Reason for opening",
               placeholder="Please provide a reason for opening this ticket",
               style=discord.TextInputStyle.paragraph,
               required=True,
               max_length=1000,
          )
          self.add_item(self.reason)

     async def callback(self, interaction: discord.Interaction):
          try:
               # Create a new ticket channel (private)
               category = discord.utils.get(interaction.guild.categories, name="Tickets")
               if category is None:
                    category = await interaction.guild.create_category("Tickets")

               ticket_name = f"ticket-{interaction.user.name}"
               ticket_channel = await interaction.guild.create_text_channel(ticket_name, category=category)

               # Set permissions for the ticket channel
               await ticket_channel.set_permissions(interaction.guild.default_role, view_channel=False)
               await ticket_channel.set_permissions(interaction.user, view_channel=True)
               mod_role = discord.utils.get(interaction.guild.roles, id=1340726272908726433)
               await ticket_channel.set_permissions(mod_role, view_channel=True, send_messages=True)

               # Create embed for the ticket channel
               embed = discord.Embed(
                    title="Support Ticket",
                    description=f"Ticket opened by {interaction.user.mention}",
                    color=discord.Color.blue()
               )
               embed.add_field(name="Reason", value=self.reason.value, inline=False)

               # Create ticket controls
               ticket_controls = TicketControlsView(ticket_channel, original_name=ticket_name)

               # Send the initial message in the ticket channel
               await ticket_channel.send(
                    f"{interaction.user.mention}",
                    embed=embed,
                    view=ticket_controls
               )

               await interaction.response.send_message(
                    f"Ticket created! Please go to {ticket_channel.mention}",
                    ephemeral=True
               )
          except Exception as e:
               print(f"Error creating ticket: {e}")
               await interaction.response.send_message("❌ Something went wrong while creating the ticket. Please try again later.", ephemeral=True)

class OpenTicketButton(discord.ui.View):
     def __init__(self):
          super().__init__(timeout=None)

     @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎫")
     async def open_ticket(self, button: discord.ui.Button, interaction: discord.Interaction):
          # Check if user already has a ticket
          for channel in interaction.guild.text_channels:
               if interaction.user.name in channel.name and "ticket-" in channel.name:
                    await interaction.response.send_message("You already have an open ticket.", ephemeral=True)
                    return

          # Open ticket modal
          modal = OpenTicketModal()
          await interaction.response.send_modal(modal)

class TicketPanelView(discord.ui.View):
     def __init__(self):
          super().__init__(timeout=None)

     @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="persistent_open_ticket_button")
     async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
          """Create a new ticket when button is clicked."""
          # Check if the user already has an open ticket
          for channel in interaction.guild.text_channels:
               if interaction.user.name in channel.name and "ticket-" in channel.name:
                    await interaction.response.send_message("You already have an open ticket.", ephemeral=True)
                    return

          # Open the ticket reason modal
          modal = OpenTicketModal()
          await interaction.response.send_modal(modal)

class CloseTicketModal(discord.ui.Modal):
     def __init__(self, ticket_controls):
          super().__init__(
               "Close Ticket",
               timeout=300,
          )
          self.ticket_controls = ticket_controls

          self.reason = discord.ui.TextInput(
               label="Reason for closing",
               placeholder="Please provide a reason for closing this ticket",
               style=discord.TextInputStyle.paragraph,
               required=True,
               max_length=1000,
          )
          self.add_item(self.reason)

     async def callback(self, interaction: discord.Interaction):
          try:
               # Get the reason from the form
               reason = self.reason.value

               # Ensure we have a valid ticket channel (even after restart)
               if self.ticket_controls.ticket_channel is None:
                    self.ticket_controls.ticket_channel = interaction.channel
                    self.ticket_controls.original_name = interaction.channel.name

               # Update the stats for the moderator who closed the ticket
               user_id = str(interaction.user.id)
               if user_id not in ticket_stats:
                    ticket_stats[user_id] = {
                         "tickets_claimed": 0,
                         "tickets_closed": 0,
                         "tickets_participated": 0
                    }
               ticket_stats[user_id]["tickets_closed"] += 1
               save_json(ticket_stats, ticket_stats_file)

               # Generate a transcript
               messages = await self.ticket_controls.ticket_channel.history(limit=1000).flatten()
               transcript_content = ""
               for message in reversed(messages):
                    timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    transcript_content += f"[{timestamp}] {message.author}: {message.content}\n"

               file_name = f"transcript-{self.ticket_controls.ticket_channel.name}-{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
               with open(file_name, "w", encoding="utf-8") as file:
                    file.write(transcript_content)

               # Send close notification in the ticket channel
               embed = discord.Embed(
                    title="Ticket Closed",
                    description=f"This ticket has been closed by {interaction.user.mention}.",
                    color=discord.Color.red()
               )
               embed.add_field(name="Reason", value=reason, inline=False)
               await self.ticket_controls.ticket_channel.send(embed=embed)

               # Disable all buttons in the original ticket controls
               for child in self.ticket_controls.children:
                    child.disabled = True
               await interaction.message.edit(view=self.ticket_controls)

               # Send confirmation to user who closed the ticket
               await interaction.response.send_message("Closing ticket now", ephemeral=True)

               # Send transcript to log channel
               try:
                    log_channel = await interaction.client.fetch_channel(1345810536457179136)  # Ticket logs channel
                    if log_channel:
                         log_embed = discord.Embed(
                              title="Ticket Closed",
                              description=f"Ticket {self.ticket_controls.ticket_channel.name} was closed",
                              color=discord.Color.red(),
                              timestamp=datetime.datetime.now()
                         )
                         log_embed.add_field(name="Closed by", value=interaction.user.mention, inline=True)
                         log_embed.add_field(name="Reason", value=reason, inline=True)
                         
                         await log_channel.send(embed=log_embed)
                         transcript_file = discord.File(file_name)
                         await log_channel.send(file=transcript_file)
               except Exception as e:
                    print(f"Error sending to log channel: {e}")
                    
               # Delete the channel immediately without delay
               try:
                    await self.ticket_controls.ticket_channel.delete()
               except Exception as e:
                    print(f"Error deleting channel: {e}")
                    
               # Clean up transcript file
               try:
                    os.remove(file_name)
               except Exception as e:
                    print(f"Error removing transcript file: {e}")
                    
          except Exception as e:
               print(f"Error in CloseTicketModal callback: {e}")
               try:
                    await interaction.response.send_message(f"❌ An error occurred while closing the ticket: {e}", ephemeral=True)
               except:
                    pass

# Combined ticket controls (claim + close)
class TicketControlsView(discord.ui.View):
     def __init__(self, ticket_channel=None, original_name=None, ticket_id=None):
          super().__init__(timeout=None)  # Make this view persistent with no timeout
          self.ticket_channel = ticket_channel
          self.original_name = original_name
          self.ticket_id = ticket_id

     @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, emoji="✅", custom_id="persistent_claim_ticket_button")
     async def claim_ticket(self, button: discord.ui.Button, interaction: discord.Interaction):
          """Claim the ticket for moderators."""
          # Get the channel if it's not set yet (after bot restart)
          if self.ticket_channel is None:
               self.ticket_channel = interaction.channel
               self.original_name = interaction.channel.name

          # Check if the user has the required staff roles
          if not has_staff_role(interaction.user):
               await interaction.response.send_message("❌ You need to have the required roles to claim this ticket.", ephemeral=True)
               return

          # Update the stats for the moderator who claimed the ticket
          user_id = str(interaction.user.id)  # Convert to string for JSON compatibility
          if user_id not in ticket_stats:
               ticket_stats[user_id] = {
                    "tickets_claimed": 0,
                    "tickets_closed": 0,
                    "tickets_participated": 0
               }
          ticket_stats[user_id]["tickets_claimed"] += 1
          save_json(ticket_stats, ticket_stats_file)

          # Rename the ticket to include the moderator's name instead of the random number
          new_ticket_name = f"ticket-{interaction.user.name}"
          await self.ticket_channel.edit(name=new_ticket_name)

          # Set permissions for the claimer
          await self.ticket_channel.set_permissions(interaction.user, view_channel=True, send_messages=True)

          # Ensure all moderators can still talk in the ticket
          mod_role = discord.utils.get(interaction.guild.roles, id=1340726272908726433)
          if mod_role:
               await self.ticket_channel.set_permissions(mod_role, view_channel=True, send_messages=True)

          # Disable the claim button after claiming
          button.disabled = True  # Disable the claim button
          await interaction.message.edit(view=self)

          # Send claim notification in the ticket channel
          claim_embed = discord.Embed(
               title="Ticket Claimed",
               description=f"{interaction.user.mention} has claimed this ticket and will assist you shortly.",
               color=discord.Color.green()
          )
          await self.ticket_channel.send(embed=claim_embed)

          # Send confirmation embed to the claimer
          response_embed = discord.Embed(
               title="Ticket Claimed Successfully",
               description=f"You have claimed ticket: {self.ticket_channel.mention}",
               color=discord.Color.green()
          )
          response_embed.add_field(name="Status", value="You now have exclusive moderator access to this ticket", inline=False)
          await interaction.response.send_message(embed=response_embed, ephemeral=True)

     @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="persistent_close_ticket_button")
     async def close_ticket(self, button: discord.ui.Button, interaction: discord.Interaction):
          """Open a modal to close the ticket with a reason."""
          # Get the channel if it's not set yet (after bot restart)
          if self.ticket_channel is None:
               self.ticket_channel = interaction.channel
               self.original_name = interaction.channel.name

          # Check if the user has the required staff roles
          if not has_staff_role(interaction.user):
               await interaction.response.send_message("❌ You need to have the required roles to close this ticket.", ephemeral=True)
               return

          # Open the ticket close modal form
          modal = CloseTicketModal(self)
          await interaction.response.send_modal(modal)

@bot.command(name="ticket")
async def ticket_command(ctx):
     """Create a ticket panel with a button."""
     # Check if the author has permissions to create ticket panels
     if not ctx.author.guild_permissions.manage_channels:
          embed = discord.Embed(
               title="❌ Permission Denied",
               description="You don't have permission to create ticket panels.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!ticket`", inline=False)
          embed.add_field(name="Required Permission", value="Manage Channels", inline=False)
          await ctx.send(embed=embed)
          return

     embed = discord.Embed(
          title="🎫 Support Ticket System",
          description="Click the button below to create a support ticket.",
          color=discord.Color.blue()
     )
     embed.add_field(name="How it works", value="When you create a ticket, a private channel will be created where you can discuss your issue with our staff.", inline=False)

     # Create the view with the ticket button
     view = TicketPanelView()
     await ctx.send(embed=embed, view=view)
@bot.command()
async def simpleclose(ctx):
     """Close the ticket."""
     # Check if the user is in a ticket channel
     if "ticket" not in ctx.channel.name:
          embed = discord.Embed(
               title="❌ Invalid Channel",
               description="This command can only be used in ticket channels.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!simpleclose`", inline=False)
          embed.add_field(name="Note", value="This command must be used inside an active ticket channel.", inline=False)
          await ctx.send(embed=embed)
          return

     # Check if user has staff role
     if not has_staff_role(ctx.author):
          await ctx.send("❌ You don't have permission to close tickets.")
          return

     # Update the stats for the moderator who closed the ticket
     user_id = str(ctx.author.id)
     if user_id not in ticket_stats:
          ticket_stats[user_id] = {
               "tickets_claimed": 0,
               "tickets_closed": 0,
               "tickets_participated": 0
          }

     ticket_stats[user_id]["tickets_closed"] += 1
     save_json(ticket_stats, ticket_stats_file)

     # Send closure message
     await ctx.send("🔒 Closing ticket now...")

     try:
          # Try to DM the ticket creator (channel name format is ticket-username)
          ticket_creator_name = ctx.channel.name.replace("ticket-", "")
          ticket_creator = None

          for member in ctx.guild.members:
               if member.name.lower() == ticket_creator_name.lower():
                    ticket_creator = member
                    break

          if ticket_creator:
               try:
                    await ticket_creator.send("Your ticket has been closed. Thank you for contacting support!")
               except:
                    print(f"Could not DM {ticket_creator.name}")

          # Delete the channel
          await ctx.channel.delete()
     except Exception as e:
          await ctx.send(f"❌ Error closing ticket: {e}")
          print(f"Error closing ticket: {e}")


# Warn system code (your existing warn, warnings, clearwarns, etc.)

async def send_modlog(ctx, action, member, reason, duration=None, color=discord.Color.orange()):
     """Send a moderation action to the modlogs channel"""
     try:
          modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
          if not modlogs_channel:
               print(f"Modlogs channel not found: {MODLOGS_CHANNEL_ID}")
               return False

          embed = discord.Embed(
               title=f"📜 {action}",
               description=f"{member.mention} has been {action.lower()}.",
               color=color,
               timestamp=datetime.datetime.now()
          )
          embed.add_field(name="Reason", value=reason or "No reason provided.", inline=False)
          embed.add_field(name="Moderator", value=ctx.author.mention, inline=False)

          if duration:
               embed.add_field(name="Duration", value=duration, inline=False)

          embed.set_footer(text=f"User ID: {member.id}")
          embed.set_thumbnail(url=member.display_avatar.url)

          await modlogs_channel.send(embed=embed)
          return True
     except Exception as e:
          print(f"Error sending to modlogs: {e}")
          return False

@bot.command(name="warn")
async def warn_command(ctx, member: discord.Member = None, *, reason=None):
     # Check if no member was specified
     if member is None:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a member to warn.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!warn @user [reason]`", inline=False)
          embed.add_field(name="Example", value="`!warn @username Breaking server rules`", inline=False)
          await ctx.send(embed=embed)
          return

     # Check if the author has 'manage_messages' permission
     if ctx.author.guild_permissions.manage_messages:
          # Initialize the user's warnings if they don't have any
          member_id = str(member.id)  # Convert to string for JSON compatibility
          if member_id not in warns:
               warns[member_id] = []

          # Add the warning, the reason, and who issued it
          warns[member_id].append({
               'reason': reason or "No reason provided.",
               'moderator': ctx.author.mention,  # Store who issued the warning
               'timestamp': datetime.datetime.now().isoformat()  # Add timestamp
          })

          # Save the warns to the file
          save_json(warns, warns_file)

          # Send a confirmation message
          embed = discord.Embed(
               title="⚠️ Warning",
               description=f"{member.mention} has been warned.",
               color=discord.Color.orange()
          )
          embed.add_field(name="Reason", value=reason or "No reason provided.", inline=False)
          embed.add_field(name="Issued by", value=ctx.author.mention, inline=False)
          embed.add_field(name="Total Warnings", value=len(warns[member_id]), inline=False)

          await ctx.send(embed=embed)

          # Send to modlogs
          await send_modlog(ctx, "Warning", member, reason)
     else:
          await ctx.send("❌ You do not have permission to use this command.")

@bot.command(name="mute")
async def mute_command(ctx, user = None, duration: str = None, *, reason=None):
     """Mutes a member for a specified duration using Discord timeout"""
     # Check if no user was specified
     if user is None:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a user to mute.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!mute <@user/user_id> [duration] [reason]`", inline=False)
          embed.add_field(name="Example", value="`!mute @username 1h Spamming in chat` or `!mute 123456789012345678 1h Spamming in chat`", inline=False)
          embed.add_field(name="Duration Format", value="s = seconds, m = minutes, h = hours, d = days", inline=False)
          await ctx.send(embed=embed)
          return

     # Check if the author has appropriate permissions
     if not ctx.author.guild_permissions.moderate_members:
          await ctx.send("❌ You do not have permission to timeout members.")
          return
          
     # Delete the command message
     try:
          await ctx.message.delete()
     except Exception as e:
          print(f"Error deleting mute command message: {e}")
     
     # Convert user input to Member object
     member = None
     
     # Check if it's a mention or a user ID
     if user.isdigit():
          # It's a user ID
          try:
               member = await ctx.guild.fetch_member(int(user))
          except discord.NotFound:
               await ctx.send("❌ User not found. Please check the ID and try again.")
               return
          except Exception as e:
               await ctx.send(f"❌ Error finding user: {e}")
               return
     else:
          # Try to convert from mention
          try:
               # Extract ID from mention if it's a mention
               if user.startswith('<@') and user.endswith('>'):
                    user_id = user.replace('<@', '').replace('>', '').replace('!', '')
                    if user_id.isdigit():
                         member = await ctx.guild.fetch_member(int(user_id))
               else:
                    # Try to find by name if it's not a mention or ID
                    member = discord.utils.get(ctx.guild.members, name=user)
                    
               if member is None:
                    await ctx.send("❌ User not found. Please use a valid @mention or ID.")
                    return
          except Exception as e:
               await ctx.send(f"❌ Error finding user: {e}")
               return

     # Check if a duration was provided
     if duration is None:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a duration for the mute.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!mute <@user/user_id> [duration] [reason]`", inline=False)
          embed.add_field(name="Example", value="`!mute @username 1h Spamming in chat` or `!mute 123456789012345678 1h Spamming in chat`", inline=False)
          await ctx.send(embed=embed)
          return

     # Parse the duration
     time_units = {
          's': 1,
          'm': 60,
          'h': 3600,
          'd': 86400
     }

     # Extract the number and unit from the duration string
     time_value = ""
     time_unit = ""

     for char in duration:
          if char.isdigit():
               time_value += char
          else:
               time_unit = char
               break

     # Check if the duration format is valid
     if not time_value or time_unit not in time_units:
          await ctx.send("❌ Invalid duration format. Use s for seconds, m for minutes, h for hours, d for days.")
          return

     # Calculate the duration in seconds
     seconds = int(time_value) * time_units[time_unit]

     # Convert seconds to datetime.timedelta for timeout
     timeout_duration = datetime.timedelta(seconds=seconds)

     # Check if timeout is within Discord's limits (max 28 days)
     max_timeout = datetime.timedelta(days=28)
     if timeout_duration > max_timeout:
          await ctx.send("❌ Timeout duration too long. Maximum duration is 28 days.")
          return

     # Apply timeout to the member
     try:
          await member.timeout(timeout_duration, reason=reason or "No reason provided.")

          # Format the time for display
          readable_time = f"{time_value} "
          if time_unit == 's': readable_time += "second(s)"
          elif time_unit == 'm': readable_time += "minute(s)"
          elif time_unit == 'h': readable_time += "hour(s)"
          elif time_unit == 'd': readable_time += "day(s)"

          # Send confirmation message
          embed = discord.Embed(
               title="🔇 Member Muted",
               description=f"{member.mention} has been timed out (muted).",
               color=discord.Color.red()
          )
          embed.add_field(name="Duration", value=readable_time, inline=False)
          embed.add_field(name="Reason", value=reason or "No reason provided.", inline=False)
          embed.add_field(name="Muted by", value=ctx.author.mention, inline=False)

          await ctx.send(embed=embed)

          # Send to modlogs
          await send_modlog(ctx, "Mute", member, reason, readable_time, discord.Color.red())

     except Exception as e:
          await ctx.send(f"❌ Error muting member: {e}")

@bot.command()
async def addblacklist(ctx, *, word=None):
     """Add a word to the automod blacklist."""
     # Check if the author has appropriate permissions
     if not ctx.author.guild_permissions.manage_messages:
          embed = discord.Embed(
               title="❌ Permission Denied",
               description="You don't have permission to manage the automod system.",
               color=discord.Color.red()
          )
          await ctx.send(embed=embed)
          return

     # Check if word is provided
     if not word:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a word to blacklist.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!addblacklist <word>`", inline=False)
          await ctx.send(embed=embed)
          return

     # Convert to lowercase for consistency
     word = word.lower().strip()

     # Check if word is already in blacklist
     if word in blacklisted_words:
          await ctx.send(f"⚠️ The word `{word}` is already in the blacklist.")
          return

     # Add word to blacklist
     blacklisted_words.append(word)

     # Save updated blacklist
     save_json(blacklisted_words, blacklisted_words_file)

     # Send confirmation
     embed = discord.Embed(
          title="✅ Word Added to Blacklist",
          description=f"The word has been added to the automod blacklist.",
          color=discord.Color.green()
     )
     # Try to purge the command message immediately to hide the word from logs
     try:
          await ctx.channel.purge(limit=1, check=lambda m: m.id == ctx.message.id)
     except Exception as e:
          print(f"Error purging command message: {e}")
     # DM the word to the moderator instead of showing it in chat
     try:
          dm_embed = discord.Embed(
               title="Word Added to Blacklist",
               description=f"You added: `{word}`",
               color=discord.Color.green()
          )
          await ctx.author.send(embed=dm_embed)
     except:
          embed.add_field(name="Note", value="I couldn't DM you the word details.", inline=False)

     await ctx.send(embed=embed)

     # Log to modlogs
     try:
          modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
          if modlogs_channel:
               log_embed = discord.Embed(
                    title="📝 Automod Updated",
                    description=f"A word was added to the blacklist by {ctx.author.mention}",
                    color=discord.Color.blue(),
                    timestamp=datetime.datetime.now()
               )
               log_embed.add_field(name="Added Word", value=f"`{word}`", inline=False)
               log_embed.set_footer(text=f"Moderator ID: {ctx.author.id}")
               await modlogs_channel.send(embed=log_embed)
     except Exception as e:
          print(f"Error sending to modlogs: {e}")

@bot.command()
async def bulkaddwords(ctx, *, words=None):
     """Add multiple words to the automod blacklist at once, separated by commas."""
     # Check if the author has appropriate permissions
     if not ctx.author.guild_permissions.manage_messages:
          embed = discord.Embed(
               title="❌ Permission Denied",
               description="You don't have permission to manage the automod system.",
               color=discord.Color.red()
          )
          await ctx.send(embed=embed)
          return

     # Check if words are provided
     if not words:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify words to blacklist, separated by commas.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!bulkaddwords word1, word2, word3`", inline=False)
          embed.add_field(name="Example", value="`!bulkaddwords badword, very bad word, worst word`", inline=False)
          await ctx.send(embed=embed)
          return

     # Try to purge the command message immediately to hide the words from logs
     try:
          await ctx.channel.purge(limit=1, check=lambda m: m.id == ctx.message.id)
     except Exception as e:
          print(f"Error purging command message: {e}")

     # Split the input by commas and process each word
     word_list = [word.lower().strip() for word in words.split(',')]
     
     # Filter out empty strings
     word_list = [word for word in word_list if word]
     
     if not word_list:
          await ctx.send("❌ No valid words provided. Please separate words with commas.")
          return

     # Track results
     added_words = []
     already_in_list = []

     # Process each word
     for word in word_list:
          if word in blacklisted_words:
               already_in_list.append(word)
          else:
               blacklisted_words.append(word)
               added_words.append(word)

     # Save updated blacklist if any words were added
     if added_words:
          save_json(blacklisted_words, blacklisted_words_file)

     # Create result embed
     embed = discord.Embed(
          title="📝 Bulk Words Addition Result",
          color=discord.Color.green()
     )

     # Add info about added words
     if added_words:
          embed.description = f"Successfully added {len(added_words)} word(s) to the blacklist."
          
          # Add field for added words only if there are any
          if len(added_words) > 0:
               # Send sensitive details via DM
               try:
                    words_text = "\n".join([f"• `{word}`" for word in added_words])
                    dm_embed = discord.Embed(
                         title="Words Added to Blacklist",
                         description=f"You added {len(added_words)} word(s) to the blacklist:",
                         color=discord.Color.green()
                    )
                    
                    # If the list is too long, split it
                    if len(words_text) <= 1024:
                         dm_embed.add_field(name="Added Words", value=words_text, inline=False)
                    else:
                         # Split into multiple fields
                         chunks = []
                         current_chunk = ""
                         for word in added_words:
                              word_entry = f"• `{word}`\n"
                              if len(current_chunk) + len(word_entry) <= 1024:
                                   current_chunk += word_entry
                              else:
                                   chunks.append(current_chunk)
                                   current_chunk = word_entry
                         if current_chunk:
                              chunks.append(current_chunk)
                              
                         for i, chunk in enumerate(chunks):
                              dm_embed.add_field(name=f"Added Words (Part {i+1})", value=chunk, inline=False)
                    
                    await ctx.author.send(embed=dm_embed)
               except Exception as e:
                    embed.add_field(name="Note", value="I couldn't DM you the word details.", inline=False)
                    print(f"Error sending DM: {e}")
     else:
          embed.description = "No new words were added to the blacklist."
          embed.color = discord.Color.orange()

     # Add info about words already in the list
     if already_in_list:
          embed.add_field(
               name="Already in Blacklist", 
               value=f"{len(already_in_list)} word(s) were already in the blacklist.", 
               inline=False
          )

     await ctx.send(embed=embed)

     # Log to modlogs if words were added
     if added_words:
          try:
               modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
               if modlogs_channel:
                    log_embed = discord.Embed(
                         title="📝 Automod Updated",
                         description=f"{len(added_words)} word(s) were added to the blacklist by {ctx.author.mention}",
                         color=discord.Color.blue(),
                         timestamp=datetime.datetime.now()
                    )
                    log_embed.set_footer(text=f"Moderator ID: {ctx.author.id}")
                    await modlogs_channel.send(embed=log_embed)
          except Exception as e:
               print(f"Error sending to modlogs: {e}")

@bot.command()
async def removeblacklist(ctx, *, word=None):
     """Remove a word from the automod blacklist."""
     # Check if the author has appropriate permissions
     if not ctx.author.guild_permissions.manage_messages:
          embed = discord.Embed(
               title="❌ Permission Denied",
               description="You don't have permission to manage the automod system.",
               color=discord.Color.red()
          )
          await ctx.send(embed=embed)
          return

     # Check if word is provided
     if not word:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a word to remove from the blacklist.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!removeblacklist <word>`", inline=False)
          await ctx.send(embed=embed)
          return

     # Convert to lowercase for consistency
     word = word.lower().strip()

     # Check if word is in blacklist
     if word not in blacklisted_words:
          await ctx.send(f"⚠️ The word `{word}` is not in the blacklist.")
          return

     # Remove word from blacklist
     blacklisted_words.remove(word)

     # Save updated blacklist
     save_json(blacklisted_words, blacklisted_words_file)

     # Send confirmation
     embed = discord.Embed(
          title="✅ Word Removed from Blacklist",
          description=f"The word has been removed from the automod blacklist.",
          color=discord.Color.green()
     )

     # DM the word to the moderator instead of showing it in chat
     try:
          dm_embed = discord.Embed(
               title="Word Removed from Blacklist",
               description=f"You removed: `{word}`",
               color=discord.Color.green()
          )
          await ctx.author.send(embed=dm_embed)
     except:
          embed.add_field(name="Note", value="I couldn't DM you the word details.", inline=False)

     await ctx.send(embed=embed)

     # Log to modlogs
     try:
          modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
          if modlogs_channel:
               log_embed = discord.Embed(
                    title="📝 Automod Updated",
                    description=f"A word was removed from the blacklist by {ctx.author.mention}",
                    color=discord.Color.yellow(),
                    timestamp=datetime.datetime.now()
               )
               log_embed.add_field(name="Removed Word", value=f"`{word}`", inline=False)
               log_embed.set_footer(text=f"Moderator ID: {ctx.author.id}")
               await modlogs_channel.send(embed=log_embed)
     except Exception as e:
          print(f"Error sending to modlogs: {e}")

@bot.command()
async def automodwords(ctx):
     """List all blacklisted words in automod."""
     # Check if the author has appropriate permissions
     if not ctx.author.guild_permissions.manage_messages:
          embed = discord.Embed(
               title="❌ Permission Denied",
               description="You don't have permission to view the automod blacklist.",
               color=discord.Color.red()
          )
          await ctx.send(embed=embed)
          return

     # Check if DMs are enabled
     try:
          if not blacklisted_words:
               embed = discord.Embed(
                    title="📋 Automod Blacklist",
                    description="The blacklist is currently empty.",
                    color=discord.Color.blue()
               )
               await ctx.author.send(embed=embed)
          else:
               # Create embed to send via DM
               embed = discord.Embed(
                    title="📋 Automod Blacklist",
                    description=f"There are currently {len(blacklisted_words)} words in the blacklist:",
                    color=discord.Color.blue()
               )

               # Add words to embed
               word_list = "\n".join([f"• `{word}`" for word in sorted(blacklisted_words)])

               # Split the list if it's too long
               if len(word_list) <= 1024:
                    embed.add_field(name="Blacklisted Words", value=word_list, inline=False)
               else:
                    # Split the list into multiple fields (max 1024 chars per field)
                    parts = []
                    current_part = ""
                    for word in sorted(blacklisted_words):
                         word_entry = f"• `{word}`\n"
                         if len(current_part) + len(word_entry) <= 1024:
                              current_part += word_entry
                         else:
                              parts.append(current_part)
                              current_part = word_entry
                    if current_part:
                         parts.append(current_part)

                    for i, part in enumerate(parts):
                         embed.add_field(name=f"Blacklisted Words (Part {i+1})", value=part, inline=False)

               await ctx.author.send(embed=embed)

          # Send confirmation in channel
          await ctx.send("✅ I've sent you a DM with the list of blacklisted words.")
     except Exception as e:
          # If DM fails, inform the user
          await ctx.send(f"❌ I couldn't send you a DM. Please enable DMs from server members and try again.")
          print(f"Error sending DM: {e}")

          return

     # Calculate the duration in seconds
     seconds = int(time_value) * time_units[time_unit]

     # Convert seconds to datetime.timedelta for timeout
     import datetime
     timeout_duration = datetime.timedelta(seconds=seconds)

     # Check if timeout is within Discord's limits (max 28 days)
     max_timeout = datetime.timedelta(days=28)
     if timeout_duration > max_timeout:
          await ctx.send("❌ Timeout duration too long. Maximum duration is 28 days.")
          return

     # Apply timeout to the member
     try:
          await member.timeout(timeout_duration, reason=reason or "No reason provided.")

          # Format the time for display
          readable_time = f"{time_value} "
          if time_unit == 's': readable_time += "second(s)"
          elif time_unit == 'm': readable_time += "minute(s)"
          elif time_unit == 'h': readable_time += "hour(s)"
          elif time_unit == 'd': readable_time += "day(s)"

          # Send confirmation message
          embed = discord.Embed(
               title="🔇 Member Muted",
               description=f"{member.mention} has been timed out (muted).",
               color=discord.Color.red()
          )
          embed.add_field(name="Duration", value=readable_time, inline=False)
          embed.add_field(name="Reason", value=reason or "No reason provided.", inline=False)
          embed.add_field(name="Muted by", value=ctx.author.mention, inline=False)

          await ctx.send(embed=embed)

          # Send DM to the muted user
          try:
               dm_embed = discord.Embed(
                    title="You have been muted",
                    description=f"You have been muted in **{ctx.guild.name}**.",
                    color=discord.Color.red()
               )
               dm_embed.add_field(name="Duration", value=readable_time, inline=False)
               dm_embed.add_field(name="Reason", value=reason or "No reason provided.", inline=False)
               dm_embed.add_field(name="Muted by", value=ctx.author.name, inline=False)
               await member.send(embed=dm_embed)
          except Exception as e:
               print(f"Could not send DM to {member.name}: {e}")

          # Send to modlogs
          await send_modlog(ctx, "Mute", member, reason, readable_time, discord.Color.red())

     except Exception as e:
          await ctx.send(f"❌ Error muting member: {e}")

@bot.command()
async def unmute(ctx, member: discord.Member = None, *, reason="Manual unmute"):
     """Removes timeout from a member"""
     # Check if no member was specified
     if member is None:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a member to unmute.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!unmute @user [reason]`", inline=False)
          embed.add_field(name="Example", value="`!unmute @username Time served`", inline=False)
          await ctx.send(embed=embed)
          return

     # Check if the author has appropriate permissions
     if not ctx.author.guild_permissions.moderate_members:
          await ctx.send("❌ You do not have permission to use this command.")
          return

     # Check if the member is timed out
     if member.timed_out_until is None or member.timed_out_until < datetime.datetime.now().replace(tzinfo=datetime.timezone.utc):
          await ctx.send(f"❌ {member.mention} is not currently timed out.")
          return

     # Remove the timeout
     try:
          await member.timeout(None, reason=reason)  # Setting timeout to None removes it

          # Send confirmation message
          embed = discord.Embed(
               title="🔊 Member Unmuted",
               description=f"{member.mention} has been unmuted (timeout removed).",
               color=discord.Color.green()
          )
          embed.add_field(name="Reason", value=reason, inline=False)
          embed.add_field(name="Unmuted by", value=ctx.author.mention, inline=False)

          await ctx.send(embed=embed)

          # Send to modlogs
          await send_modlog(ctx, "Unmute", member, reason, None, discord.Color.green())

     except Exception as e:
          await ctx.send(f"❌ Error unmuting member: {e}")

@bot.command()
async def warnings(ctx, member: discord.Member = None):
     """Show warnings for a user."""
     # If no member is specified, default to the command author
     if member is None:
          member = ctx.author

     member_id = str(member.id)

     # Check if the user has any warnings
     if member_id not in warns or not warns[member_id]:
          embed = discord.Embed(
               title="Warnings",
               description=f"{member.mention} has no warnings.",
               color=discord.Color.green()
          )
          await ctx.send(embed=embed)
          return

     # Create an embed to display the warnings
     embed = discord.Embed(
          title=f"Warnings for {member.name}",
          description=f"{member.mention} has {len(warns[member_id])} warnings.",
          color=discord.Color.orange()
     )

     # Add each warning to the embed
     for i, warning in enumerate(warns[member_id], 1):
          embed.add_field(
               name=f"Warning #{i}",
               value=f"**Reason:** {warning['reason']}\n**Warned by:** {warning['moderator']}",
               inline=False
          )

     await ctx.send(embed=embed)


@bot.command()
async def stats(ctx):
     """Show ticket stats for all staff members, including those with no activity."""
     # Check if user has admin permission
     if not ctx.author.guild_permissions.administrator:
          await ctx.send("❌ You don't have permission to use this command.")
          return

     # Reload the stats from the JSON file to ensure we have the latest data
     global ticket_stats
     ticket_stats = load_json(ticket_stats_file)

     # Debug - print ticket stats for verification
     print(f"Loaded ticket stats: {ticket_stats}")

     # Create member map for easy lookup and to fetch missing users
     member_map = {}
     for member in ctx.guild.members:
          member_map[str(member.id)] = member

     # Try to fetch additional users that aren't in the member cache
     for user_id in ticket_stats.keys():
          if user_id not in member_map and user_id != "level_notification_channel":
               try:
                    # Attempt to fetch the user from Discord API
                    user = await bot.fetch_user(int(user_id))
                    if user:
                         member_map[user_id] = user
               except Exception as e:
                    print(f"Could not fetch user {user_id}: {e}")

     # Prepare data for all users first
     all_users_data = []

     # First add users who have stats in the ticket_stats file
     for user_id, stats in ticket_stats.items():
          # Skip non-user entries like level_notification_channel
          if not user_id.isdigit():
               continue
               
          # Format user ID as a mention
          mention = f"<@{user_id}>"

          # Get display name if possible
          if user_id in member_map:
               user = member_map[user_id]
               display_name = user.display_name if hasattr(user, 'display_name') else user.name
          else:
               display_name = f"User-{user_id}"

          all_users_data.append({
               "id": user_id,
               "display_name": display_name,
               "mention": mention,
               "participated": stats.get('tickets_participated', 0),
               "claimed": stats.get('tickets_claimed', 0),
               "closed": stats.get('tickets_closed', 0)
          })

     # Then add staff members who don't have stats
     shown_members = set(user_id for user_id in ticket_stats.keys() if user_id.isdigit())
     
     for member_id, member in member_map.items():
          if member_id not in shown_members and has_staff_role(member):
               all_users_data.append({
                    "id": member_id,
                    "display_name": member.display_name,
                    "mention": f"<@{member_id}>",
                    "participated": 0,
                    "claimed": 0,
                    "closed": 0
               })

     # Now create and send embeds with 24 fields max each
     if not all_users_data:
          await ctx.send("No ticket statistics to display.")
          return

     # Create embeds with 24 fields each (leaving room for title/description)
     embeds = []
     current_embed = discord.Embed(
          title="📊 Ticket Statistics for ALL Members",
          description="This shows how many tickets each member has participated in, claimed, or closed.",
          color=discord.Color.blue()
     )
     embeds.append(current_embed)
     
     field_count = 0
     
     for user_data in all_users_data:
          # If we've hit 24 fields, create a new embed
          if field_count >= 24:
               current_embed = discord.Embed(
                    title="📊 Ticket Statistics (Continued)",
                    color=discord.Color.blue()
               )
               embeds.append(current_embed)
               field_count = 0
          
          # Add field to current embed
          current_embed.add_field(
               name=f"👤 {user_data['display_name']}",
               value=(f"{user_data['mention']}\n"
                      f"🎟 **Participated:** {user_data['participated']}\n"
                      f"✅ **Claimed:** {user_data['claimed']}\n"
                      f"🔒 **Closed:** {user_data['closed']}"),
               inline=True
          )
          field_count += 1
     
     # Add footer to the last embed
     embeds[-1].set_footer(text=f"Showing stats for {len(all_users_data)} members")
     
     # Send all embeds
     for embed in embeds:
          await ctx.send(embed=embed)

# Warning select menu for clearing specific warnings
class WarningSelect(discord.ui.Select):
     def __init__(self, member, warnings_list):
          self.member = member
          self.warnings_list = warnings_list

          # Create options for each warning
          options = []
          for i, warning in enumerate(warnings_list, 1):
               reason = warning['reason']
               # Truncate reason if it's too long
               if len(reason) > 50:
                    reason = reason[:47] + "..."

               options.append(discord.SelectOption(
                    label=f"Warning #{i}",
                    description=reason,
                    value=str(i-1)  # Store index as value
               ))

          super().__init__(
               placeholder="Select a warning to clear",
               min_values=1,
               max_values=1,
               options=options
          )

     async def callback(self, interaction: discord.Interaction):
          # Check if user has permission
          if not interaction.user.guild_permissions.manage_messages:
               await interaction.response.send_message("❌ You don't have permission to clear warnings.", ephemeral=True)
               return

          selected_index = int(self.values[0])
          warning = self.warnings_list[selected_index]

          # Remove the selected warning
          member_id = str(self.member.id)
          warns[member_id].pop(selected_index)

          # If no more warnings, remove the user from the warns dict
          if not warns[member_id]:
               del warns[member_id]

          # Save the updated warns
          save_json(warns, warns_file)

          # Send confirmation
          embed = discord.Embed(
               title="Warning Cleared",
               description=f"Removed warning from {self.member.mention}",
               color=discord.Color.green()
          )
          embed.add_field(name="Cleared Warning", value=f"**Reason:*\
          * {warning['reason']}", inline=False)
          embed.add_field(name="Cleared by", value=interaction.user.mention, inline=False)

          await interaction.response.send_message(embed=embed)

          # Disable the select menu
          self.disabled = True
          await interaction.message.edit(view=self.view)

          # Send to modlogs
          try:
               modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
               if modlogs_channel:
                    modlog_embed = discord.Embed(
                         title="🗑️ Warning Removed",
                         description=f"Removed a warning from {self.member.mention}",
                         color=discord.Color.green(),
                         timestamp=datetime.datetime.now()
                    )
                    modlog_embed.add_field(name="Cleared Warning", value=f"**Reason:** {warning['reason']}", inline=False)
                    modlog_embed.add_field(name="Warned by", value=warning['moderator'], inline=False)
                    modlog_embed.add_field(name="Cleared by", value=interaction.user.mention, inline=False)
                    modlog_embed.set_footer(text=f"User ID: {self.member.id}")
                    modlog_embed.set_thumbnail(url=self.member.display_avatar.url)
                    await modlogs_channel.send(embed=modlog_embed)
          except Exception as e:
               print(f"Error sending to modlogs: {e}")

class ClearWarningsView(discord.ui.View):
     def __init__(self, member, warnings_list):
          super().__init__(timeout=60)
          self.add_item(WarningSelect(member, warnings_list))

     @discord.ui.button(label="Clear All Warnings", style=discord.ButtonStyle.danger)
     async def clear_all(self, button: discord.ui.Button, interaction: discord.Interaction):
          # Check permissions
          if not interaction.user.guild_permissions.manage_messages:
               await interaction.response.send_message("❌ You don't have permission to clear warnings.", ephemeral=True)
               return

          # Clear all warnings for the member
          member_id = str(self.children[0].member.id)
          if member_id in warns:
               # Store member info before clearing warnings
               member = self.children[0].member
               
               # Clear the warnings
               del warns[member_id]
               save_json(warns, warns_file)

               # Disable all components
               for child in self.children:
                    child.disabled = True

               # Send confirmation
               embed = discord.Embed(
                    title="All Warnings Cleared",
                    description=f"All warnings have been cleared for {member.mention}",
                    color=discord.Color.green()
               )
               embed.add_field(name="Cleared by", value=interaction.user.mention, inline=False)

               await interaction.response.send_message(embed=embed)
               await interaction.message.edit(view=self)

               # Send to modlogs
               try:
                    modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                    if modlogs_channel:
                         modlog_embed = discord.Embed(
                              title="🧹 Warnings Cleared",
                              description=f"All warnings have been cleared for {member.mention}",
                              color=discord.Color.green(),
                              timestamp=datetime.datetime.now()
                         )
                         modlog_embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
                         modlog_embed.set_footer(text=f"User ID: {member.id}")
                         modlog_embed.set_thumbnail(url=member.display_avatar.url)
                         await modlogs_channel.send(embed=modlog_embed)
               except Exception as e:
                    print(f"Error sending to modlogs: {e}")
          else:
               await interaction.response.send_message(f"⚠️ This user doesn't have any warnings to clear.", ephemeral=True)

@bot.command()
async def purge(ctx, amount: int = None, member: discord.Member = None):
     """Purge messages from the channel, optionally filtering by user."""
     # Check if the author has manage_messages permission
     if not ctx.author.guild_permissions.manage_messages:
          embed = discord.Embed(
               title="❌ Permission Denied",
               description="You don't have permission to purge messages.",
               color=discord.Color.red()
          )
          embed.add_field(name="Required Permission", value="Manage Messages", inline=False)
          await ctx.send(embed=embed)
          return

     # Check if amount is provided
     if amount is None:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify the number of messages to purge.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!purge [amount] [@user]`", inline=False)
          embed.add_field(name="Examples", value="`!purge 10` - Purge 10 messages\n`!purge 20 @username` - Purge up to 20 messages from a specific user", inline=False)
          await ctx.send(embed=embed)
          return

     # Delete the command message first
     await ctx.message.delete()

     # Define a check function if member is specified
     def check_user(message):
          return member is None or message.author.id == member.id

     # Purge the messages
     try:
          # Delete messages with the check
          deleted = await ctx.channel.purge(limit=amount, check=check_user)

          # Create a success embed
          embed = discord.Embed(
               title="🧹 Messages Purged",
               description=f"Successfully deleted {len(deleted)} messages.",
               color=discord.Color.green()
          )

          if member:
               embed.description = f"Successfully deleted {len(deleted)} messages from {member.mention}."

          # Send a temporary confirmation message that auto-deletes after 5 seconds
          conf_msg = await ctx.send(embed=embed)
          await conf_msg.delete(delay=5)

     except discord.Forbidden:
          await ctx.send("I don't have permission to delete messages here.", delete_after=5)
     except discord.HTTPException as e:
          await ctx.send(f"Error: {e}\nCannot delete messages older than 14 days.", delete_after=5)

@bot.command()
async def clearwarns(ctx, member: discord.Member = None):
     """Clear warnings for a user using a dropdown menu."""
     # Check if no member was specified
     if member is None:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a member to clear warnings for.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!clearwarns @user`", inline=False)
          embed.add_field(name="Example", value="`!clearwarns @username`", inline=False)
          await ctx.send(embed=embed)
          return

     # Check if the author has permission
     if not ctx.author.guild_permissions.manage_messages:
          await ctx.send("❌ You do not have permission to use this command.")
          return

     member_id = str(member.id)

     # Check if the user has any warnings
     if member_id not in warns or not warns[member_id]:
          embed = discord.Embed(
               title="No Warnings",
               description=f"{member.mention} has no warnings to clear.",
               color=discord.Color.green()
          )
          await ctx.send(embed=embed)
          return

     # Create an embed to display the warnings
     embed = discord.Embed(
          title=f"Clear Warnings for {member.name}",
          description=f"Select a warning to clear or use the button to clear all warnings.\n\n{member.mention} has {len(warns[member_id])} warnings.",
          color=discord.Color.orange()
     )

     # Add each warning to the embed
     for i, warning in enumerate(warns[member_id], 1):
          embed.add_field(
               name=f"Warning #{i}",
               value=f"**Reason:** {warning['reason']}\n**Warned by:** {warning['moderator']}",
               inline=False
          )

     # Create the view with the dropdown menu
     view = ClearWarningsView(member, warns[member_id])

     await ctx.send(embed=embed, view=view)

WHITELISTED_ROLES = ["Moderator", "Co-Owner", "Owner","Admin"]

@bot.command()
async def repeat(ctx, title: str = None, *, message: str = None):  
     """Repeats the message in an embed, including images. Only whitelisted roles can use it."""
     if not any(role.name in WHITELISTED_ROLES for role in ctx.author.roles):
          await ctx.send(":x: You are not allowed to use this command!")
          return
     
     # If no message and no attachments are provided
     if message is None and not ctx.message.attachments:
          await ctx.send(":x: Please provide a message or attach an image! Example: `!repeat Hello`")
          return
     
     try:
          # Create the embed
          embed = discord.Embed(
               title=title or "",  
               description=message or "No message provided.",  
               color=discord.Color.blue()
          )
          embed.set_footer(
               text=f"Requested by {ctx.author.name}",
               icon_url=ctx.author.avatar.url if ctx.author.avatar else None
          )
          
          # Process attachments (find the first valid image for the embed)
          image_files = []  # To store files for non-embed images
          embed_image_set = False
          
          for attachment in ctx.message.attachments:
               if attachment.url.lower().endswith(('png', 'jpg', 'jpeg', 'gif', 'webp')):
                    # Set the first image as the embed's image
                    if not embed_image_set:
                         embed.set_image(url=attachment.url)
                         embed_image_set = True
                    else:
                         # Download additional images to send separately
                         async with aiohttp.ClientSession() as session:
                              async with session.get(attachment.url) as resp:
                                   if resp.status == 200:
                                        file_data = await resp.read()
                                        file = discord.File(io.BytesIO(file_data), filename=attachment.filename)
                                        image_files.append(file)
          
          # Send the embed with the first image
          await ctx.send(embed=embed)
          
          # Send any additional images as separate messages
          for file in image_files:
               await ctx.send(file=file)
               
          print("Embed and images sent successfully!")
     except Exception as e:
          print(f"Error creating or sending embed: {e}")
          await ctx.send(f":x: Something went wrong while creating the embed: {str(e)}")
# Helper function to convert slash command interactions to command context
async def get_application_context(bot, interaction):
     """Convert an interaction to a command context for proper slash command handling"""
     ctx = await bot.get_context(interaction.message) if interaction.message else None
     if ctx is None:
          ctx = type('obj', (object,), {
               'author': interaction.user,
               'guild': interaction.guild,
               'channel': interaction.channel,
               'bot': bot,
               'send': lambda *args, **kwargs: interaction.response.send_message(*args, **kwargs) 
                    if not interaction.response.is_done() 
                    else interaction.followup.send(*args, **kwargs),
               'voice_client': interaction.guild.voice_client if interaction.guild else None,
               'message': interaction.message,
               'interaction': interaction
          })
     return ctx

# Music system functions
class Song:
     """Class to store song information"""
     def __init__(self, title, url, thumbnail, duration, requester, source_url=None):
          self.title = title
          self.url = url  # Audio stream URL
          self.thumbnail = thumbnail
          self.duration = duration
          self.requester = requester
          self.source_url = source_url or url  # Original URL (YouTube, Spotify)

class MusicQueue:
     """Class to manage music queue for each server"""
     def __init__(self):
          self.queue = []
          self.current = None
          self.loop = False
          self.volume = 0.5

     def add(self, song):
          self.queue.append(song)
          return len(self.queue)
     
     def clear(self):
          self.queue = []
          
     def next(self):
          if not self.queue:
               return None
          
          if self.loop and self.current:
               # If loop mode, add current song back to the queue
               self.queue.append(self.current)
               
          # Get the next song
          self.current = self.queue.pop(0)
          return self.current
     
     def is_empty(self):
          return len(self.queue) == 0

# Initialize a queue dictionary for servers
music_queues = {}

def get_queue(guild_id):
     """Get or create a music queue for a server"""
     if guild_id not in music_queues:
          music_queues[guild_id] = MusicQueue()
     return music_queues[guild_id]

async def get_song_info(query, requester):
     """Extract song information from YouTube URL or search query"""
     try:
          ydl_opts = {
               "format": "bestaudio/best",
               "default_search": "ytsearch" if not query.startswith("http") else None,
               "quiet": True,
               "no_warnings": True,
               "noplaylist": True,
               "extract_flat": False,
               "socket_timeout": 60,
               "nocheckcertificate": True,
               "ignoreerrors": False,  # Changed to False to catch errors
               "logtostderr": False,
               "geo_bypass": True,
               "geo_bypass_country": "US",
               "age_limit": 25,  # Bypass age restrictions
               "extractor_args": {
                    'youtube': {
                         'skip': ['hls', 'dash'],
                         'player_client': ['android', 'web'],
                    }
               }
          }
          
          with yt_dlp.YoutubeDL(ydl_opts) as ydl:
               # Extract info
               try:
                    info = ydl.extract_info(query, download=False)
                    
                    # Handle case where info might be None
                    if not info:
                         print(f"Could not extract info for query: {query}")
                         return None
                         
                    # Handle YouTube search results
                    if 'entries' in info:
                         if not info['entries']:
                              return None
                         info = info['entries'][0]
                         
                    # Create song object
                    song = Song(
                         title=info.get('title', 'Unknown'),
                         url=info.get('url'),
                         thumbnail=info.get('thumbnail', None),
                         duration=info.get('duration', 0),
                         requester=requester,
                         source_url=info.get('webpage_url', query)
                    )
                    
                    return song
               except yt_dlp.utils.DownloadError as e:
                    if "age" in str(e).lower():
                         print(f"Age-restricted content detected: {e}")
                    else:
                         print(f"Download error: {e}")
                    return None
               
     except Exception as e:
          print(f"Error getting song info: {e}")
          return None

async def play_next_song(ctx):
     """Play the next song in the queue"""
     guild_id = ctx.guild.id
     queue = get_queue(guild_id)
     
     # If nothing more to play, stop
     if queue.is_empty():
          # Clear current song
          queue.current = None
          return
     
     # Get next song from queue
     song = queue.next()
     if not song:
          return
          
     # Get voice client
     voice_client = ctx.voice_client
     if not voice_client or not voice_client.is_connected():
          return
     
     # Setup FFmpeg options for better streaming
     ffmpeg_opts = {
          "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10 -rw_timeout 15000000",
          "options": "-vn -bufsize 2048k"
     }
     
     # Create audio source and play
     try:
          audio_source = discord.FFmpegPCMAudio(song.url, **ffmpeg_opts)
          voice_client.play(
               audio_source, 
               after=lambda e: asyncio.run_coroutine_threadsafe(
                    handle_song_end(ctx, e), bot.loop
               )
          )
          voice_client.source = discord.PCMVolumeTransformer(voice_client.source)
          voice_client.source.volume = queue.volume
          
          # Send now playing embed
          await send_now_playing(ctx, song)
     except Exception as e:
          print(f"Error playing song: {e}")
          await ctx.send(f"❌ Error playing song: {e}")
          # Try to play next song
          await handle_song_end(ctx, None)

async def handle_song_end(ctx, error):
     """Handle the end of a song"""
     if error:
          print(f"Error occurred: {error}")
          
     await play_next_song(ctx)

async def send_now_playing(ctx, song):
     """Send a now playing embed message"""
     # Format duration
     minutes, seconds = divmod(song.duration, 60)
     hours, minutes = divmod(minutes, 60)
     
     if hours > 0:
          duration = f"{hours}:{minutes:02d}:{seconds:02d}"
     else:
          duration = f"{minutes}:{seconds:02d}"
     
     # Create embed
     embed = discord.Embed(
          title="🎵 Now Playing",
          description=f"**[{song.title}]({song.source_url})**",
          color=discord.Color.green()
     )
     
     if song.thumbnail:
          embed.set_thumbnail(url=song.thumbnail)
          
     embed.add_field(name="Duration", value=duration, inline=True)
     embed.add_field(name="Requested By", value=song.requester.mention, inline=True)
     
     # Add queue info
     queue = get_queue(ctx.guild.id)
     if queue.queue:
          embed.add_field(
               name="Up Next", 
               value=f"{len(queue.queue)} song(s) in queue", 
               inline=True
          )
     
     # Music control buttons
     view = MusicControlsView(ctx)
     await ctx.send(embed=embed, view=view)

class MusicControlsView(discord.ui.View):
     def __init__(self, ctx):
          super().__init__(timeout=60)
          self.ctx = ctx
          
     @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.primary)
     async def skip_button(self, button: discord.ui.Button, interaction: discord.Interaction):
          """Skip the current song"""
          # Make sure it's in the same channel
          if interaction.channel.id != self.ctx.channel.id:
               return
               
          # Check if user is in voice channel
          if not interaction.user.voice or (self.ctx.voice_client and interaction.user.voice.channel.id != self.ctx.voice_client.channel.id):
               return await interaction.response.send_message("❌ You need to be in the same voice channel!", ephemeral=True)
               
          # Skip song
          if self.ctx.voice_client and self.ctx.voice_client.is_playing():
               await interaction.response.send_message("⏭️ Skipping song...")
               self.ctx.voice_client.stop()
          else:
               await interaction.response.send_message("❌ Nothing is playing right now!", ephemeral=True)
     
     @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
     async def stop_button(self, button: discord.ui.Button, interaction: discord.Interaction):
          """Stop playback and clear queue"""
          # Make sure it's in the same channel
          if interaction.channel.id != self.ctx.channel.id:
               return
               
          # Check if user is in voice channel
          if not interaction.user.voice or (self.ctx.voice_client and interaction.user.voice.channel.id != self.ctx.voice_client.channel.id):
               return await interaction.response.send_message("❌ You need to be in the same voice channel!", ephemeral=True)
               
          # Clear queue and stop playback
          queue = get_queue(self.ctx.guild.id)
          queue.clear()
          
          if self.ctx.voice_client:
               if self.ctx.voice_client.is_playing():
                    self.ctx.voice_client.stop()
               await self.ctx.voice_client.disconnect()
               
          await interaction.response.send_message("⏹️ Music stopped and queue cleared!")
     
     @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.secondary)
     async def queue_button(self, button: discord.ui.Button, interaction: discord.Interaction):
          """Display the current queue"""
          # Make sure it's in the same channel
          if interaction.channel.id != self.ctx.channel.id:
               return
               
          queue = get_queue(self.ctx.guild.id)
          
          if not queue.queue and not queue.current:
               return await interaction.response.send_message("📭 The queue is empty!", ephemeral=True)
               
          # Create queue embed
          embed = discord.Embed(
               title="🎵 Music Queue",
               color=discord.Color.blue()
          )
          
          # Add current song
          if queue.current:
               embed.add_field(
                    name="🎶 Now Playing",
                    value=f"**[{queue.current.title}]({queue.current.source_url})**\nRequested by: {queue.current.requester.mention}",
                    inline=False
               )
          
          # Add queue items (up to 10)
          if queue.queue:
               queue_text = ""
               for i, song in enumerate(queue.queue[:10], 1):
                    queue_text += f"{i}. **{song.title}** - Requested by: {song.requester.mention}\n"
                    
               if len(queue.queue) > 10:
                    queue_text += f"\n*+{len(queue.queue) - 10} more songs in queue*"
                    
               embed.add_field(name="📜 Up Next", value=queue_text, inline=False)
          
          await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command()
async def play(ctx, *, query=None):
     """Play a song from YouTube URL or search query"""
     # Check if command is used in the music channel
     if ctx.channel.id != 1345805980268494899:
          return await ctx.send("❌ Music commands can only be used in <#1345805980268494899>")
          
     # Check if user provided a query
     if not query:
          embed = discord.Embed(
               title="❌ Missing Arguments",
               description="Please provide a YouTube URL or search query.",
               color=discord.Color.red()
          )
          embed.add_field(
               name="Usage",
               value="`!play <YouTube URL or search query>`\n\nExamples:\n`!play https://www.youtube.com/watch?v=dQw4w9WgXcQ`\n`!play lofi hip hop`",
               inline=False
          )
          return await ctx.send(embed=embed)
     
     # Check if user is in a voice channel
     if not ctx.author.voice:
          return await ctx.send("❌ You need to be in a voice channel to use this command!")
     
     # Send processing message
     processing_msg = await ctx.send("🔍 Searching for your song, please wait...")
     
     # Get song info
     try:
          # Handle Spotify links
          if "spotify.com/track/" in query:
               track_id = query.split("/")[-1].split("?")[0]
               
               # Fetch track details from Spotify
               try:
                    track_info = sp.track(track_id)
                    track_name = track_info["name"]
                    artist_name = track_info["artists"][0]["name"]
                    
                    # Update query to search YouTube instead
                    query = f"{track_name} {artist_name} audio"
               except Exception as e:
                    await processing_msg.edit(content=f"❌ Error fetching Spotify track info: {e}")
                    return
          
          # Get song info from YouTube
          song = await get_song_info(query, ctx.author)
          if not song:
               # Provide more helpful message
               if "age" in query.lower() or any(x in query.lower() for x in ["explicit", "nsfw", "18+"]):
                    await processing_msg.edit(content="❌ Could not play this content - it may be age-restricted. Try another song.")
               else:
                    await processing_msg.edit(content="❌ Could not find any matching songs. Please try a different search term or URL.")
               return
          
          # Join voice channel if not already connected
          voice_client = ctx.voice_client
          if not voice_client:
               try:
                    voice_client = await ctx.author.voice.channel.connect()
               except Exception as e:
                    return await processing_msg.edit(content=f"❌ Could not connect to voice channel: {e}")
          
          # Add song to queue
          queue = get_queue(ctx.guild.id)
          position = queue.add(song)
          
          # Update processing message
          if voice_client.is_playing():
               minutes, seconds = divmod(song.duration, 60)
               await processing_msg.edit(
                    content=None,
                    embed=discord.Embed(
                         title="🎵 Added to Queue",
                         description=f"**[{song.title}]({song.source_url})**",
                         color=discord.Color.blue()
                    ).add_field(
                         name="Position", value=f"#{position}", inline=True
                    ).add_field(
                         name="Duration", value=f"{minutes}:{seconds:02d}", inline=True
                    ).add_field(
                         name="Requested By", value=ctx.author.mention, inline=True
                    ).set_thumbnail(url=song.thumbnail)
               )
          else:
               # Start playing if nothing is playing
               await processing_msg.delete()
               await play_next_song(ctx)
               
     except Exception as e:
          await processing_msg.edit(content=f"❌ An error occurred: {e}")
          print(f"Error in play command: {e}")

@bot.command()
async def stop(ctx):
     """Stops playback and clears the queue"""
     # Check if command is used in the music channel
     if ctx.channel.id != 1345805980268494899:
          return await ctx.send("❌ Music commands can only be used in <#1345805980268494899>")
          
     # Check if user is in the same voice channel
     if not ctx.author.voice or (ctx.voice_client and ctx.author.voice.channel.id != ctx.voice_client.channel.id):
          return await ctx.send("❌ You need to be in the same voice channel to stop the music!")
     
     # Check if bot is in a voice channel
     if not ctx.voice_client:
          return await ctx.send("❌ I'm not playing any music right now!")
     
     # Clear queue and stop playback
     queue = get_queue(ctx.guild.id)
     queue.clear()
     
     if ctx.voice_client.is_playing():
          ctx.voice_client.stop()
     
     await ctx.voice_client.disconnect()
     
     embed = discord.Embed(
          title="⏹️ Music Stopped",
          description="Music playback has been stopped and the queue has been cleared.",
          color=discord.Color.red()
     )
     await ctx.send(embed=embed)

@bot.command()
async def skip(ctx):
     """Skip the current song"""
     # Check if command is used in the music channel
     if ctx.channel.id != 1345805980268494899:
          return await ctx.send("❌ Music commands can only be used in <#1345805980268494899>")
          
     # Check if user is in the same voice channel
     if not ctx.author.voice or (ctx.voice_client and ctx.author.voice.channel.id != ctx.voice_client.channel.id):
          return await ctx.send("❌ You need to be in the same voice channel to skip the song!")
     
     # Check if bot is playing music
     if not ctx.voice_client or not ctx.voice_client.is_playing():
          return await ctx.send("❌ I'm not playing any music right now!")
     
     # Skip the song
     ctx.voice_client.stop()
     
     await ctx.send("⏭️ Skipped the current song!")

@bot.command()
async def queue(ctx):
     """Show the current music queue"""
     # Check if command is used in the music channel
     if ctx.channel.id != 1345805980268494899:
          return await ctx.send("❌ Music commands can only be used in <#1345805980268494899>")
          
     queue = get_queue(ctx.guild.id)
     
     # Check if queue is empty
     if not queue.queue and not queue.current:
          embed = discord.Embed(
               title="📭 Queue Empty",
               description="There are no songs in the queue.",
               color=discord.Color.orange()
          )
          return await ctx.send(embed=embed)
     
     # Create queue embed
     embed = discord.Embed(
          title="🎵 Music Queue",
          color=discord.Color.blue()
     )
     
     # Add current song
     if queue.current:
          # Format duration
          minutes, seconds = divmod(queue.current.duration, 60)
          duration = f"{minutes}:{seconds:02d}"
          
          embed.add_field(
               name="🎶 Now Playing",
               value=f"**[{queue.current.title}]({queue.current.source_url})**\nDuration: {duration}\nRequested by: {queue.current.requester.mention}",
               inline=False
          )
     
     # Add queue items
     if queue.queue:
          queue_text = ""
          total_duration = 0
          
          for i, song in enumerate(queue.queue[:10], 1):
               # Format duration
               minutes, seconds = divmod(song.duration, 60)
               duration = f"{minutes}:{seconds:02d}"
               
               queue_text += f"{i}. **[{song.title}]({song.source_url})** ({duration}) - Requested by: {song.requester.mention}\n"
               total_duration += song.duration
               
          if len(queue.queue) > 10:
               queue_text += f"\n*+{len(queue.queue) - 10} more songs in queue*"
               
          # Format total duration
          total_minutes, total_seconds = divmod(total_duration, 60)
          total_hours, total_minutes = divmod(total_minutes, 60)
          
          if total_hours > 0:
               total_duration_str = f"{total_hours}h {total_minutes}m {total_seconds}s"
          else:
               total_duration_str = f"{total_minutes}m {total_seconds}s"
               
          # Add queue info
          embed.add_field(name="📜 Up Next", value=queue_text, inline=False)
          embed.add_field(name="📊 Queue Info", value=f"**{len(queue.queue)}** songs in queue\nTotal Duration: **{total_duration_str}**", inline=False)
     
     await ctx.send(embed=embed)

@bot.command()
async def clear(ctx):
     """Clear the music queue (except current song)"""
     # Check if command is used in the music channel
     if ctx.channel.id != 1345805980268494899:
          return await ctx.send("❌ Music commands can only be used in <#1345805980268494899>")
          
     # Check if user is in the same voice channel
     if not ctx.author.voice or (ctx.voice_client and ctx.author.voice.channel.id != ctx.voice_client.channel.id):
          return await ctx.send("❌ You need to be in the same voice channel to clear the queue!")
     
     queue = get_queue(ctx.guild.id)
     
     # Check if queue is already empty
     if not queue.queue:
          return await ctx.send("📭 The queue is already empty!")
     
     # Clear the queue
     count = len(queue.queue)
     queue.clear()
     
     embed = discord.Embed(
          title="🧹 Queue Cleared",
          description=f"Removed {count} songs from the queue.",
          color=discord.Color.green()
     )
     await ctx.send(embed=embed)

@bot.command()
async def remove(ctx, position: int = None):
     """Remove a song from the queue by position"""
     # Check if command is used in the music channel
     if ctx.channel.id != 1345805980268494899:
          return await ctx.send("❌ Music commands can only be used in <#1345805980268494899>")
          
     # Check if user provided a position
     if position is None:
          return await ctx.send("❌ Please specify a position in the queue to remove.")
     
     # Check if user is in the same voice channel
     if not ctx.author.voice or (ctx.voice_client and ctx.author.voice.channel.id != ctx.voice_client.channel.id):
          return await ctx.send("❌ You need to be in the same voice channel to modify the queue!")
     
     queue = get_queue(ctx.guild.id)
     
     # Check if queue is empty
     if not queue.queue:
          return await ctx.send("📭 The queue is empty!")
     
     # Check if position is valid
     if position < 1 or position > len(queue.queue):
          return await ctx.send(f"❌ Invalid position. Please use a number between 1 and {len(queue.queue)}.")
     
     # Remove song from queue
     song = queue.queue.pop(position - 1)
     
     embed = discord.Embed(
          title="🗑️ Song Removed",
          description=f"Removed **[{song.title}]({song.source_url})** from the queue.",
          color=discord.Color.red()
     )
     embed.set_footer(text=f"Requested by {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
     
     await ctx.send(embed=embed)



# On ready event is already defined above

@bot.command()
async def transcript(ctx, channel: discord.TextChannel = None):
     """Generates a transcript of a specified channel."""
     if channel is None:
          channel = ctx.channel  

     messages = await channel.history(limit=1000).flatten()
     transcript_content = ""

     for message in reversed(messages):
          timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
          transcript_content += f"[{timestamp}] {message.author}: {message.content}\n"

     file_name = f"transcript-{channel.name}-{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
     with open(file_name, "w", encoding="utf-8") as file:
          file.write(transcript_content)

     await ctx.send(file=discord.File(file_name))


@bot.command()
async def claim(ctx):
     """Marks a ticket as claimed by the user."""
     if ctx.channel.id not in ticket_data:
          ticket_data[ctx.channel.id] = {}
     ticket_data[ctx.channel.id]['claimed_by'] = ctx.author
     await ctx.send(f"{ctx.author.mention} has claimed this ticket.")

@bot.command()
async def close(ctx, *, reason: str = "No reason provided"):
     """Closes a ticket and generates a transcript."""
     if ctx.channel.id not in ticket_data:
          await ctx.send("This is not a valid ticket channel.")
          return

     claimed_by = ticket_data[ctx.channel.id].get('claimed_by', 'Not claimed')
     messages = await ctx.channel.history(limit=1000).flatten()
     transcript_content = ""

     for message in reversed(messages):
          timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
          transcript_content += f"[{timestamp}] {message.author}: {message.content}\n"

     file_name = f"transcript-{ctx.channel.name}-{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
     with open(file_name, "w", encoding="utf-8") as file:
          file.write(transcript_content)

     embed = discord.Embed(title="Ticket Closed", color=discord.Color.red())
     embed.add_field(name="Closed by", value=ctx.author.mention, inline=True)
     embed.add_field(name="Claimed by", value=claimed_by.mention if isinstance(claimed_by, discord.Member) else claimed_by, inline=True)
     embed.add_field(name="Reason", value=reason, inline=False)
     embed.set_footer(text=f"Ticket ID: {ctx.channel.id}")



     log_channel = await bot.fetch_channel(1345810536457179136)
     if log_channel is None:
          await ctx.send("Log channel not found. Please check the channel ID.")
          return

     await log_channel.send(embed=embed)
     transcript_file = discord.File(file_name)
     await log_channel.send(file=transcript_file)
     os.remove(file_name)  # Delete the transcript file after sending it

     ROLE_ID = 1345903491914403851  


     @bot.command()
     async def pingrole(ctx):
          """Pings a specific role."""
          role = ctx.guild.get_role(ROLE_ID)  
          if role:
               await ctx.send(f"{role.mention}")  
          else:
               await ctx.send("❌ Role not found!")

bot.remove_command("help")  

# Leveling system functions
async def add_xp(user, xp_amount):
     """Add XP to a user and handle level ups."""
     user_id = str(user.id)
     
     # Initialize user if not in the levels database
     if user_id not in levels:
          levels[user_id] = {
               "xp": 0,
               "level": 1,
               "last_message_time": 0
          }
     
     # Anti-spam: only add XP if it's been at least 60 seconds since their last message
     current_time = datetime.datetime.now().timestamp()
     last_message_time = levels[user_id].get("last_message_time", 0)
     
     if current_time - last_message_time >= 60:
          # Add XP
          levels[user_id]["xp"] += xp_amount
          levels[user_id]["last_message_time"] = current_time
          
          # Check for level up
          current_xp = levels[user_id]["xp"]
          current_level = levels[user_id]["level"]
          
          # XP required formula: 5 * (lvl ^ 2) + 50 * lvl + 100
          xp_required = 5 * (current_level ** 2) + 50 * current_level + 100
          
          # Level up if they have enough XP
          if current_xp >= xp_required:
               new_level = levels[user_id]["level"] + 1
               levels[user_id]["level"] = new_level
               
               # Try to send level up message and assign roles
               try:
                    guild = user.guild
                    if guild:
                         # Send level up message to the configured level notification channel or fallback
                         notification_channel_id = levels.get("level_notification_channel", 0)
                         try:
                              if notification_channel_id and int(notification_channel_id) > 0:
                                   channel = await bot.fetch_channel(int(notification_channel_id))
                              else:
                                   channel = guild.system_channel or guild.text_channels[0]
                         except Exception as e:
                              print(f"Error finding level notification channel: {e}")
                              channel = guild.system_channel or guild.text_channels[0]
                         
                         level_embed = discord.Embed(
                              title="🎉 Level Up!",
                              description=f"{user.mention} has reached level **{new_level}**!",
                              color=discord.Color.gold()
                         )
                         await channel.send(f"{user.mention}", embed=level_embed)
                         
                         # Check if user should get a level role
                         for level_requirement, role_id in LEVEL_ROLES.items():
                              if new_level >= level_requirement:
                                   role = guild.get_role(role_id)
                                   if role and role not in user.roles:
                                        try:
                                             await user.add_roles(role, reason=f"Reached level {level_requirement}")
                                             await channel.send(f"🏆 {user.mention} has earned the **{role.name}** role!")
                                        except Exception as e:
                                             print(f"Error assigning role: {e}")
               except Exception as e:
                    print(f"Error in level up processing: {e}")
          
          # Save the levels data
          save_json(levels, levels_file)

@bot.command()
async def rank(ctx, member: discord.Member = None):
     """Show the rank card for a user."""
     # If no member specified, show for command author
     if member is None:
          member = ctx.author
     
     user_id = str(member.id)
     
     # Check if user has any levels data
     if user_id not in levels:
          await ctx.send(f"{member.mention} hasn't earned any XP yet.")
          return
     
     # Get user data
     xp = levels[user_id]["xp"]
     level = levels[user_id]["level"]
     
     # Calculate XP needed for next level
     next_level_xp = 5 * (level ** 2) + 50 * level + 100
     
     # Create rank embed
     embed = discord.Embed(
          title=f"{member.name}'s Rank",
          color=discord.Color.blue()
     )
     
     embed.add_field(name="Level", value=str(level), inline=True)
     embed.add_field(name="XP", value=f"{xp}/{next_level_xp}", inline=True)
     
     # Calculate progress percentage
     progress = min(100, int((xp / next_level_xp) * 100))
     
     # Create progress bar (20 characters wide)
     progress_bar_length = 20
     filled_length = int(progress_bar_length * progress / 100)
     bar = "█" * filled_length + "░" * (progress_bar_length - filled_length)
     
     embed.add_field(name="Progress", value=f"`{bar}` {progress}%", inline=False)
     embed.set_thumbnail(url=member.display_avatar.url)
     
     await ctx.send(embed=embed)

@bot.command()
async def leaderboard(ctx):
     """Display the top 10 users by XP."""
     if not levels:
          await ctx.send("No one has earned XP yet.")
          return
     
     # Filter out non-user entries (like level_notification_channel)
     user_levels = {user_id: data for user_id, data in levels.items() 
                     if user_id.isdigit() and isinstance(data, dict) and "level" in data and "xp" in data}
     
     if not user_levels:
          await ctx.send("No one has earned XP yet.")
          return
     
     # Sort users by XP
     sorted_users = sorted(user_levels.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)
     
     # Create leaderboard embed
     embed = discord.Embed(
          title="🏆 XP Leaderboard",
          description="Top members by level and XP",
          color=discord.Color.gold()
     )
     
     # Add top 10 users to leaderboard
     for i, (user_id, user_data) in enumerate(sorted_users[:10], 1):
          try:
               user = await bot.fetch_user(int(user_id))
               user_name = user.name if user else f"User {user_id}"
          except:
               user_name = f"User {user_id}"
          
          embed.add_field(
               name=f"{i}. {user_name}",
               value=f"Level: {user_data['level']} | XP: {user_data['xp']}",
               inline=False
          )
     
     await ctx.send(embed=embed)

@bot.command()
async def setlevelchannel(ctx, channel = None):
     """Set the channel where level up notifications will be sent."""
     # Check if user has admin permission
     if not ctx.author.guild_permissions.administrator:
          await ctx.send("❌ You don't have permission to use this command.")
          return
     
     # Check if a channel was specified
     if not channel:
          await ctx.send("❌ Please specify a channel using #channel-name or channel ID. Usage: `!setlevelchannel #channel`")
          return
     
     channel_id = None
     
     # Check if channel is specified as a mention
     if channel.startswith('<#') and channel.endswith('>'):
          channel_id = channel[2:-1]
     # Check if channel is specified as an ID
     elif channel.isdigit():
          channel_id = channel
     
     if not channel_id:
          await ctx.send("❌ Invalid channel format. Please use #channel-name or channel ID.")
          return
          
     # Verify the channel exists
     try:
          channel_obj = await bot.fetch_channel(int(channel_id))
          if not isinstance(channel_obj, discord.TextChannel):
               await ctx.send("❌ The specified channel is not a text channel.")
               return
     except:
          await ctx.send("❌ Could not find that channel. Please check the channel ID or mention.")
          return
     
     # Save the channel ID to the levels data
     levels["level_notification_channel"] = channel_id
     save_json(levels, levels_file)
     
     await ctx.send(f"✅ Level up notifications will now be sent to {channel_obj.mention}.")

@bot.command()
async def addxp(ctx, member: discord.Member = None, amount: int = None):
     """Admin command to add XP to a user."""
     # Check if user has admin permission
     if not ctx.author.guild_permissions.administrator:
          await ctx.send("❌ You don't have permission to use this command.")
          return
     
     # Check for valid arguments
     if member is None or amount is None:
          await ctx.send("❌ Please specify a member and an amount. Usage: `!addxp @user 100`")
          return
     
     # Add XP
     await add_xp(member, amount)
     
     # Confirm
     await ctx.send(f"✅ Added {amount} XP to {member.mention}.")

@bot.command(name="serverinfo")
async def serverinfo(ctx):
     """Display information about the server"""
     guild = ctx.guild
     
     # Get server creation date
     created_at = guild.created_at.strftime("%B %d, %Y")
     
     # Get member counts
     total_members = len(guild.members)
     human_members = len([m for m in guild.members if not m.bot])
     bot_members = total_members - human_members
     
     # Get channel counts
     text_channels = len(guild.text_channels)
     voice_channels = len(guild.voice_channels)
     categories = len(guild.categories)
     
     # Get role count (excluding @everyone)
     roles = len(guild.roles) - 1
     
     # Create embed
     embed = discord.Embed(
          title=f"📊 Server Information: {guild.name}",
          description=f"ID: {guild.id}",
          color=discord.Color.blue()
     )
     
     # Add server icon if it exists
     if guild.icon:
          embed.set_thumbnail(url=guild.icon.url)
     
     # Add basic info
     embed.add_field(name="📆 Created On", value=created_at, inline=True)
     embed.add_field(name="👑 Owner", value=guild.owner.mention, inline=True)
     embed.add_field(name="🌍 Region", value=str(guild.preferred_locale).replace("-", " ").title(), inline=True)
     
     # Add member info
     embed.add_field(name="👥 Members", value=f"Total: {total_members}\nHumans: {human_members}\nBots: {bot_members}", inline=True)
     
     # Add channel info
     embed.add_field(name="📝 Channels", value=f"Text: {text_channels}\nVoice: {voice_channels}\nCategories: {categories}", inline=True)
     
     # Add role info
     embed.add_field(name="🏷️ Roles", value=str(roles), inline=True)
     
     # Add boost info
     embed.add_field(name="🚀 Boost Status", value=f"Level: {guild.premium_tier}\nBoosts: {guild.premium_subscription_count}", inline=True)
     
     # Set footer with timestamp
     embed.set_footer(text=f"Requested by {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
     embed.timestamp = datetime.datetime.now()
     
     await ctx.send(embed=embed)

# Create a command tree for slash commands
slash_commands = app_commands.Group(name="bot", description="Bot commands")
bot.tree.add_command(slash_commands)

@slash_commands.command(name="userinfo", description="Display information about a user")
async def slash_userinfo_func(interaction: discord.Interaction, member: discord.Member = None):
     """Display information about a user"""
     # If no member is specified, use the command author
     if member is None:
          member = interaction.user
     
     # Get dates
     joined_at = member.joined_at.strftime("%B %d, %Y") if member.joined_at else "Unknown"
     created_at = member.created_at.strftime("%B %d, %Y")
     
     # Get status
     status = str(member.status).title() if hasattr(member, 'status') else "Unknown"
     
     # Calculate account age with timezone handling
     now = datetime.datetime.now(datetime.timezone.utc)
     # Ensure both datetimes have timezone info for comparison
     created_at_aware = member.created_at.replace(tzinfo=datetime.timezone.utc) if member.created_at.tzinfo is None else member.created_at
     account_age = (now - created_at_aware).days
     
     # Get roles (excluding @everyone)
     roles = [role.mention for role in member.roles if role.name != "@everyone"]
     roles_str = ", ".join(roles) if roles else "None"
     
     # Create embed
     embed = discord.Embed(
          title=f"User Information: {member.name}",
          description=f"ID: {member.id}",
          color=member.color if member.color != discord.Color.default() else discord.Color.blue()
     )
     
     # Add user avatar
     embed.set_thumbnail(url=member.display_avatar.url)
     
     # Add basic info
     embed.add_field(name="📝 Display Name", value=member.display_name, inline=True)
     embed.add_field(name="🤖 Bot", value="Yes" if member.bot else "No", inline=True)
     embed.add_field(name="📊 Status", value=status, inline=True)
     
     # Add date info
     embed.add_field(name="🗓️ Account Created", value=f"{created_at}\n({account_age} days ago)", inline=True)
     embed.add_field(name="📥 Joined Server", value=joined_at, inline=True)
     
     # Add role info (with character limit check)
     if len(roles_str) > 1024:
          roles_str = f"{len(roles)} roles (too many to display)"
     embed.add_field(name=f"🏷️ Roles [{len(roles)}]", value=roles_str, inline=False)
     
     # Set footer with timestamp
     embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
     embed.timestamp = datetime.datetime.now()
     
     await interaction.response.send_message(embed=embed)

@slash_commands.command(name="serverinfo", description="Display information about the server")
async def slash_serverinfo_func(interaction: discord.Interaction):
     """Display information about the server"""
     guild = interaction.guild
     
     # Get server creation date
     created_at = guild.created_at.strftime("%B %d, %Y")
     
     # Get member counts
     total_members = len(guild.members)
     human_members = len([m for m in guild.members if not m.bot])
     bot_members = total_members - human_members
     
     # Get channel counts
     text_channels = len(guild.text_channels)
     voice_channels = len(guild.voice_channels)
     categories = len(guild.categories)
     
     # Get role count (excluding @everyone)
     roles = len(guild.roles) - 1
     
     # Create embed
     embed = discord.Embed(
          title=f"📊 Server Information: {guild.name}",
          description=f"ID: {guild.id}",
          color=discord.Color.blue()
     )
     
     # Add server icon if it exists
     if guild.icon:
          embed.set_thumbnail(url=guild.icon.url)
     
     # Add basic info
     embed.add_field(name="📆 Created On", value=created_at, inline=True)
     embed.add_field(name="👑 Owner", value=guild.owner.mention, inline=True)
     embed.add_field(name="🌍 Region", value=str(guild.preferred_locale).replace("-", " ").title(), inline=True)
     
     # Add member info
     embed.add_field(name="👥 Members", value=f"Total: {total_members}\nHumans: {human_members}\nBots: {bot_members}", inline=True)
     
     # Add channel info
     embed.add_field(name="📝 Channels", value=f"Text: {text_channels}\nVoice: {voice_channels}\nCategories: {categories}", inline=True)
     
     # Add role info
     embed.add_field(name="🏷️ Roles", value=str(roles), inline=True)
     
     # Add boost info
     embed.add_field(name="🚀 Boost Status", value=f"Level: {guild.premium_tier}\nBoosts: {guild.premium_subscription_count}", inline=True)
     
     # Set footer with timestamp
     embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
     embed.timestamp = datetime.datetime.now()
     
     await interaction.response.send_message(embed=embed)

# Mod commands group
mod_commands = app_commands.Group(name="mod", description="Moderation commands")
bot.tree.add_command(mod_commands)

@mod_commands.command(name="warn", description="Warn a user for violating rules")
async def slash_warn_func(interaction: discord.Interaction, 
                    member: discord.Member,
                    reason: str = None):
     """Warn a user for violating rules"""
     # Check if the author has 'manage_messages' permission
     if interaction.user.guild_permissions.manage_messages:
          # Initialize the user's warnings if they don't have any
          member_id = str(member.id)  # Convert to string for JSON compatibility
          if member_id not in warns:
               warns[member_id] = []

          # Add the warning, the reason, and who issued it
          warns[member_id].append({
               'reason': reason or "No reason provided.",
               'moderator': interaction.user.mention,  # Store who issued the warning
               'timestamp': datetime.datetime.now().isoformat()  # Add timestamp
          })

          # Save the warns to the file
          save_json(warns, warns_file)

          # Send a confirmation message
          embed = discord.Embed(
               title="⚠️ Warning",
               description=f"{member.mention} has been warned.",
               color=discord.Color.orange()
          )
          embed.add_field(name="Reason", value=reason or "No reason provided.", inline=False)
          embed.add_field(name="Issued by", value=interaction.user.mention, inline=False)
          embed.add_field(name="Total Warnings", value=len(warns[member_id]), inline=False)

          await interaction.response.send_message(embed=embed)

          # Send to modlogs
          modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
          if modlogs_channel:
              embed = discord.Embed(
                  title="📜 Warning",
                  description=f"{member.mention} has been warned.",
                  color=discord.Color.orange(),
                  timestamp=datetime.datetime.now()
              )
              embed.add_field(name="Reason", value=reason or "No reason provided.", inline=False)
              embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
              embed.set_footer(text=f"User ID: {member.id}")
              embed.set_thumbnail(url=member.display_avatar.url)
              await modlogs_channel.send(embed=embed)
     else:
          await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)

# Level commands group
level_commands = app_commands.Group(name="level", description="Leveling system commands")
bot.tree.add_command(level_commands)

@level_commands.command(name="rank", description="Show the rank card for a user")
async def slash_rank_func(interaction: discord.Interaction, 
                    member: discord.Member = None):
     """Show the rank card for a user"""
     # If no member specified, show for command author
     if member is None:
          member = interaction.user
     
     user_id = str(member.id)
     
     # Check if user has any levels data
     if user_id not in levels:
          await interaction.response.send_message(f"{member.mention} hasn't earned any XP yet.")
          return
     
     # Get user data
     xp = levels[user_id]["xp"]
     level = levels[user_id]["level"]
     
     # Calculate XP needed for next level
     next_level_xp = 5 * (level ** 2) + 50 * level + 100
     
     # Create rank embed
     embed = discord.Embed(
          title=f"{member.name}'s Rank",
          color=discord.Color.blue()
     )
     
     embed.add_field(name="Level", value=str(level), inline=True)
     embed.add_field(name="XP", value=f"{xp}/{next_level_xp}", inline=True)
     
     # Calculate progress percentage
     progress = min(100, int((xp / next_level_xp) * 100))
     
     # Create progress bar (20 characters wide)
     progress_bar_length = 20
     filled_length = int(progress_bar_length * progress / 100)
     bar = "█" * filled_length + "░" * (progress_bar_length - filled_length)
     
     embed.add_field(name="Progress", value=f"`{bar}` {progress}%", inline=False)
     embed.set_thumbnail(url=member.display_avatar.url)
     
     await interaction.response.send_message(embed=embed)
     
@slash_commands.command(name="help", description="Show all available commands")
async def slash_help_func(interaction: discord.Interaction):
     """Show all available commands"""
     # Check if user is staff for staff commands
     is_staff = has_staff_role(interaction.user)
     is_admin = interaction.user.guild_permissions.administrator

     # General commands embed
     general_embed = discord.Embed(
          title="Bot Commands - General",
          description="Here are the general commands everyone can use:",
          color=discord.Color.blue()
     )
     
     general_embed.add_field(name="/music play <song/URL>", value="Plays a song from YouTube or Spotify URL.", inline=True)
     general_embed.add_field(name="/music skip", value="Skips the current song.", inline=True)
     general_embed.add_field(name="/music stop", value="Stops music playback.", inline=True)
     general_embed.add_field(name="/music queue", value="Shows the music queue.", inline=True)
     general_embed.add_field(name="/level rank [@user]", value="Shows your or another user's level.", inline=True)
     general_embed.add_field(name="/level leaderboard", value="Shows the XP leaderboard.", inline=True)
     general_embed.add_field(name="/bot serverinfo", value="Displays server information.", inline=True)
     general_embed.add_field(name="/bot userinfo [@user]", value="Shows detailed user information.", inline=True)
     general_embed.add_field(name="/bot help", value="Shows this help menu.", inline=True)
     
     # Send general commands
     await interaction.response.send_message(embed=general_embed)

     # Staff commands embed
     if is_staff:
          staff_embed = discord.Embed(
               title="Bot Commands - Staff",
               description="Commands for staff members:",
               color=discord.Color.green()
          )
          
          staff_embed.add_field(name="/mod warn @user <reason>", value="Warns a user for violating rules.", inline=True)
          staff_embed.add_field(name="/mod warnings [@user]", value="Shows warnings for a user.", inline=True)
          staff_embed.add_field(name="/mod clearwarns @user", value="Clears warnings for a user.", inline=True)
          staff_embed.add_field(name="/mod mute @user <duration> <reason>", value="Mutes a user for specified time.", inline=True)
          staff_embed.add_field(name="/mod unmute @user [reason]", value="Unmutes a user.", inline=True)
          staff_embed.add_field(name="/mod ban @user <reason>", value="Bans a user from the server.", inline=True)
          staff_embed.add_field(name="/mod purge [amount] [@user]", value="Deletes messages in bulk.", inline=True)
          
          # Send staff commands as a followup message
          followup = await interaction.followup.send(embed=staff_embed)

     # Admin commands embed
     if is_admin:
          admin_embed = discord.Embed(
               title="Bot Commands - Admin",
               description="Commands for administrators:",
               color=discord.Color.red()
          )
          
          admin_embed.add_field(name="/admin addrole @user @role", value="Adds a role to a user.", inline=True)
          admin_embed.add_field(name="/admin removerole @user @role", value="Removes a role from a user.", inline=True)
          admin_embed.add_field(name="/admin roleinfo @role", value="Shows role information.", inline=True)
          admin_embed.add_field(name="/admin automod [feature] [on/off]", value="Configure automod settings.", inline=True)
          
          admin_embed.set_footer(text="Use the commands as needed!")
          
          # Send admin commands as a followup message
          followup = await interaction.followup.send(embed=admin_embed)

@bot.command(name="poll")
async def poll(ctx, title: str, *options):
     """Create a poll with reactions
     Example: !poll "Favorite Color?" "Red" "Blue" "Green"
     """
     # Check if there are any options
     if len(options) == 0:
          return await ctx.send("❌ You need to provide at least one option!")
     
     # Check if there are too many options (Discord only has 20 reaction emojis)
     if len(options) > 10:
          return await ctx.send("❌ You can only have up to 10 options!")
     
     # Create the poll embed
     embed = discord.Embed(
          title=f"📊 Poll: {title}",
          description="React with the corresponding emoji to vote!",
          color=discord.Color.blue()
     )
     
     # Add options to the embed
     number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
     
     for i, option in enumerate(options):
          embed.add_field(name=f"{number_emojis[i]} Option {i+1}", value=option, inline=False)
     
     # Add footer with author info
     embed.set_footer(text=f"Poll created by {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
     embed.timestamp = datetime.datetime.now()
     
     # Send the poll
     poll_message = await ctx.send(embed=embed)
     
     # Add reaction options
     for i in range(len(options)):
          await poll_message.add_reaction(number_emojis[i])

@bot.command()
async def help(ctx):
     # Check if user is staff for staff commands
     is_staff = has_staff_role(ctx.author)
     is_admin = ctx.author.guild_permissions.administrator

     # General commands embed
     general_embed = discord.Embed(
          title="Bot Commands - General",
          description="Here are the general commands everyone can use:",
          color=discord.Color.blue()
     )
     
     general_embed.add_field(name="!play <song/URL>", value="Plays a song from YouTube or Spotify URL.", inline=True)
     general_embed.add_field(name="!skip", value="Skips the current song.", inline=True)
     general_embed.add_field(name="!stop", value="Stops music playback.", inline=True)
     general_embed.add_field(name="!queue", value="Shows the music queue.", inline=True)
     general_embed.add_field(name="!clear", value="Clears the music queue.", inline=True)
     general_embed.add_field(name="!remove <position>", value="Removes a song from the queue.", inline=True)
     general_embed.add_field(name="!ticket", value="Creates a support ticket.", inline=True)
     general_embed.add_field(name="!rank [@user]", value="Shows your or another user's level.", inline=True)
     general_embed.add_field(name="!leaderboard", value="Shows the XP leaderboard.", inline=True)
     general_embed.add_field(name="!serverinfo", value="Displays server information.", inline=True)
     general_embed.add_field(name="!userinfo [@user]", value="Shows detailed user information.", inline=True)
     general_embed.add_field(name="!poll [title] [options]", value="Creates a reaction poll.", inline=True)
     general_embed.add_field(name="!roleinfo [@role]", value="Shows detailed role information.", inline=True)
     general_embed.add_field(name="!help", value="Shows this help menu.", inline=True)
     general_embed.add_field(name="!slashcommands", value="Lists all available slash commands.", inline=True)
     
     # Send general commands
     await ctx.send(embed=general_embed)

     # Staff commands embed
     if is_staff:
          staff_embed = discord.Embed(
               title="Bot Commands - Staff",
               description="Commands for staff members:",
               color=discord.Color.green()
          )
          
          staff_embed.add_field(name="!warn @user <reason>", value="Warns a user for violating rules.", inline=True)
          staff_embed.add_field(name="!warnings [@user]", value="Shows warnings for a user.", inline=True)
          staff_embed.add_field(name="!clearwarns @user", value="Clears warnings for a user.", inline=True)
          staff_embed.add_field(name="!mute @user <duration> <reason>", value="Mutes a user for specified time.", inline=True)
          staff_embed.add_field(name="!unmute @user [reason]", value="Unmutes a user.", inline=True)
          staff_embed.add_field(name="!ban @user <reason>", value="Bans a user from the server.", inline=True)
          staff_embed.add_field(name="!unban <user_id> <reason>", value="Unbans a user from the server.", inline=True)
          staff_embed.add_field(name="!simpleclose", value="Closes the current ticket.", inline=True)
          staff_embed.add_field(name="!purge [amount] [@user]", value="Deletes messages in bulk.", inline=True)
          staff_embed.add_field(name="!transcript [#channel]", value="Generates channel transcript.", inline=True)
          staff_embed.add_field(name="!stats", value="Shows ticket handling stats.", inline=True)
          
          # Send staff commands
          await ctx.send(embed=staff_embed)

     # Admin commands embed
     if is_admin:
          admin_embed = discord.Embed(
               title="Bot Commands - Admin",
               description="Commands for administrators:",
               color=discord.Color.red()
          )
          
          admin_embed.add_field(name="!addblacklist <word>", value="Adds a word to automod filter.", inline=True)
          admin_embed.add_field(name="!bulkaddwords <word1, word2, ...>", value="Adds multiple words to automod filter at once.", inline=True)
          admin_embed.add_field(name="!removeblacklist <word>", value="Removes a word from automod filter.", inline=True)
          admin_embed.add_field(name="!automodwords", value="Lists all filtered words (DM only).", inline=True)
          admin_embed.add_field(name="!automod [feature] [on/off]", value="Configure automod settings.", inline=True)
          admin_embed.add_field(name="!repeat [title] [message]", value="Makes bot repeat a message.", inline=True)
          admin_embed.add_field(name="!setlevelchannel <#channel>", value="Sets channel for level up notifications.", inline=True)
          admin_embed.add_field(name="!addxp <@user> <amount>", value="Adds XP to a user.", inline=True)
          admin_embed.add_field(name="!resync", value="Force resync all slash commands.", inline=True)
          
          admin_embed.set_footer(text="Use the commands as needed!")
          
          # Send admin commands
          await ctx.send(embed=admin_embed)

@bot.command(name="slashcommands")
async def list_slash_commands(ctx):
     """List all available slash commands"""
     try:
          # Fetch global application commands
          commands = await bot.http.get_global_commands(bot.user.id)
          
          # Create embed
          embed = discord.Embed(
               title="🔍 Available Slash Commands",
               description="Here are all the slash commands you can use:",
               color=discord.Color.blue()
          )
          
          # Group commands by category
          general_commands = []
          mod_commands = []
          music_commands = []
          util_commands = []
          other_commands = []
          
          # Sort commands into categories based on name
          for cmd in commands:
               name = cmd['name']
               desc = cmd.get('description', 'No description')
               cmd_text = f"**/{name}** - {desc}"
               
               # Categorize by command name
               if name in ['play', 'skip', 'stop', 'queue', 'clear', 'remove']:
                    music_commands.append(cmd_text)
               elif name in ['warn', 'mute', 'ban', 'purge', 'unmute', 'clearwarns']:
                    mod_commands.append(cmd_text)
               elif name in ['help', 'rank', 'leaderboard', 'serverinfo', 'userinfo']:
                    general_commands.append(cmd_text)
               elif name in ['poll', 'announce', 'stats', 'transcript']:
                    util_commands.append(cmd_text)
               else:
                    other_commands.append(cmd_text)
          
          # Add fields to embed for each category
          if general_commands:
               embed.add_field(name="General Commands", value="\n".join(general_commands), inline=False)
          
          if music_commands:
               embed.add_field(name="Music Commands", value="\n".join(music_commands), inline=False)
          
          if mod_commands:
               embed.add_field(name="Moderation Commands", value="\n".join(mod_commands), inline=False)
          
          if util_commands:
               embed.add_field(name="Utility Commands", value="\n".join(util_commands), inline=False)
          
          if other_commands:
               embed.add_field(name="Other Commands", value="\n".join(other_commands), inline=False)
          
          embed.set_footer(text=f"Total commands: {len(commands)} | Use /help for more details")
          
          # Send embed
          await ctx.send(embed=embed)
          
     except Exception as e:
          embed = discord.Embed(
               title="❌ Error",
               description=f"Error fetching slash commands: {e}",
               color=discord.Color.red()
          )
          embed.add_field(
               name="Try This", 
               value="Ask an admin to run the `!resync` command to refresh all slash commands.",
               inline=False
          )
          await ctx.send(embed=embed)

@bot.command(name="ban")
async def ban_command(ctx, user = None, *, reason="No reason provided"):
     """Bans a user from the server"""
     # Check if no user was specified
     if user is None:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a user to ban.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!ban <@user/user_id> [reason]`", inline=False)
          embed.add_field(name="Example", value="`!ban @username Breaking server rules` or `!ban 123456789012345678 Breaking server rules`", inline=False)
          await ctx.send(embed=embed)
          return

     # Check if the author has appropriate permissions
     if not ctx.author.guild_permissions.ban_members:
          await ctx.send("❌ You do not have permission to ban members.")
          return
          
     # Convert user input to Member object first to check if it's a staff or admin
     member = None
     
     # Check if it's a mention or a user ID
     if isinstance(user, str):
          if user.isdigit():
               # It's a user ID
               try:
                    member = await ctx.guild.fetch_member(int(user))
               except discord.NotFound:
                    # If member not found, we'll continue with ID ban
                    pass
          elif user.startswith('<@') and user.endswith('>'):
               # Extract ID from mention
               user_id = int(user.replace('<@', '').replace('>', '').replace('!', ''))
               try:
                    member = await ctx.guild.fetch_member(user_id)
               except Exception:
                    pass
          else:
               # Try to find by name
               member = discord.utils.get(ctx.guild.members, name=user)
     else:
          # It's already a member object
          member = user
          
     # Check if the target user is a staff member or admin
     if member is not None:
          if has_staff_role(member) or member.guild_permissions.administrator:
               await ctx.send("❌ You cannot ban a staff member or admin.")
               return
          
          # Also prevent self-ban
          if member.id == ctx.author.id:
               await ctx.send("❌ You cannot ban yourself.")
               return
          
     # Delete the command message
     try:
          await ctx.message.delete()
     except Exception as e:
          print(f"Error deleting ban command message: {e}")
     
     # Convert user input to Member object or get user ID
     member = None
     user_id = None
     
     # Check if it's a mention or a user ID
     if isinstance(user, str):
          if user.isdigit():
               # It's a user ID
               user_id = int(user)
          elif user.startswith('<@') and user.endswith('>'):
               # Extract ID from mention
               user_id = int(user.replace('<@', '').replace('>', '').replace('!', ''))
          else:
               # Try to find by name if it's not a mention or ID
               member = discord.utils.get(ctx.guild.members, name=user)
               if member is None:
                    await ctx.send("❌ User not found. Please use a valid @mention or ID.")
                    return
     else:
          # It's already a member object (from command parser)
          member = user
     
     # If we only have an ID, try to fetch the member
     if member is None and user_id is not None:
          try:
               member = await ctx.guild.fetch_member(user_id)
          except discord.NotFound:
               # If member not found, we'll ban by ID
               pass
          except Exception as e:
               await ctx.send(f"❌ Error finding user: {e}")
               return
     
     try:
          # Ban the member or the ID
          if member is not None:
               # Send DM to the banned user if possible
               try:
                    dm_embed = discord.Embed(
                         title="You have been banned",
                         description=f"You have been banned from **{ctx.guild.name}**.",
                         color=discord.Color.red()
                    )
                    dm_embed.add_field(name="Reason", value=reason, inline=False)
                    dm_embed.add_field(name="Banned by", value=ctx.author.name, inline=False)
                    await member.send(embed=dm_embed)
               except Exception as e:
                    print(f"Could not send DM to {member.name}: {e}")
               
               # Ban the member
               await ctx.guild.ban(member, reason=f"{reason} | Banned by {ctx.author}")
               user_mention = member.mention
               user_id = member.id
               user_name = member.name
               user_avatar = member.display_avatar.url
          else:
               # Ban by ID
               await ctx.guild.ban(discord.Object(id=user_id), reason=f"{reason} | Banned by {ctx.author}")
               user_mention = f"<@{user_id}>"
               user_name = f"User {user_id}"
               user_avatar = None
          
          # Send confirmation message
          embed = discord.Embed(
               title="🔨 User Banned",
               description=f"{user_mention} has been banned from the server.",
               color=discord.Color.red()
          )
          embed.add_field(name="Reason", value=reason, inline=False)
          embed.add_field(name="Banned by", value=ctx.author.mention, inline=False)
          
          await ctx.send(embed=embed)
          
          # Send to modlogs
          await send_modlog(ctx, "Ban", type('obj', (object,), {
               'mention': user_mention,
               'id': user_id,
               'display_avatar': type('obj', (object,), {'url': user_avatar})
          }), reason, None, discord.Color.dark_red())
          
     except Exception as e:
          await ctx.send(f"❌ Error banning user: {e}")

@bot.command(name="unban")
async def unban_command(ctx, user_id=None, *, reason="No reason provided"):
     """Unbans a user from the server"""
     # Check if no user ID was specified
     if user_id is None:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a user ID to unban.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!unban <user_id> [reason]`", inline=False)
          embed.add_field(name="Example", value="`!unban 123456789012345678 Appealed ban`", inline=False)
          await ctx.send(embed=embed)
          return

     # Check if the author has appropriate permissions
     if not ctx.author.guild_permissions.ban_members:
          await ctx.send("❌ You do not have permission to unban members.")
          return
     
     # Check if the user ID is valid
     if not user_id.isdigit():
          await ctx.send("❌ Invalid user ID. Please provide a valid user ID.")
          return
     
     try:
          # Convert to integer
          user_id = int(user_id)
          
          # Fetch the ban entry
          banned_users = [ban_entry async for ban_entry in ctx.guild.bans()]
          user = None
          
          # Find the user in the ban list
          for ban_entry in banned_users:
               if ban_entry.user.id == user_id:
                    user = ban_entry.user
                    break
          
          if user is None:
               await ctx.send(f"❌ User with ID {user_id} was not found in the ban list.")
               return
          
          # Unban the user
          await ctx.guild.unban(user, reason=f"{reason} | Unbanned by {ctx.author}")
          
          # Send confirmation message
          embed = discord.Embed(
               title="✅ User Unbanned",
               description=f"{user.mention} has been unbanned from the server.",
               color=discord.Color.green()
          )
          embed.add_field(name="Reason", value=reason, inline=False)
          embed.add_field(name="Unbanned by", value=ctx.author.mention, inline=False)
          
          await ctx.send(embed=embed)
          
          # Send to modlogs
          await send_modlog(ctx, "Unban", user, reason, None, discord.Color.green())
          
     except discord.NotFound:
          await ctx.send(f"❌ User with ID {user_id} was not found.")
     except discord.HTTPException as e:
          await ctx.send(f"❌ Error unbanning user: {e}")
     except Exception as e:
          await ctx.send(f"❌ An error occurred: {e}")
     
     # Delete the command message
     try:
          await ctx.message.delete()
     except Exception as e:
          print(f"Error deleting ban command message: {e}")
     
     # Convert user input to Member object or get user ID
     member = None
     user_id = None
     
     # Check if it's a mention or a user ID
     if isinstance(user, str):
          if user.isdigit():
               # It's a user ID
               user_id = int(user)
          elif user.startswith('<@') and user.endswith('>'):
               # Extract ID from mention
               user_id = int(user.replace('<@', '').replace('>', '').replace('!', ''))
          else:
               # Try to find by name if it's not a mention or ID
               member = discord.utils.get(ctx.guild.members, name=user)
               if member is None:
                    await ctx.send("❌ User not found. Please use a valid @mention or ID.")
                    return
     else:
          # It's already a member object (from command parser)
          member = user
     
     # If we only have an ID, try to fetch the member
     if member is None and user_id is not None:
          try:
               member = await ctx.guild.fetch_member(user_id)
          except discord.NotFound:
               # If member not found, we'll ban by ID
               pass
          except Exception as e:
               await ctx.send(f"❌ Error finding user: {e}")
               return
     
     try:
          # Ban the member or the ID
          if member is not None:
               # Send DM to the banned user if possible
               try:
                    dm_embed = discord.Embed(
                         title="You have been banned",
                         description=f"You have been banned from **{ctx.guild.name}**.",
                         color=discord.Color.red()
                    )
                    dm_embed.add_field(name="Reason", value=reason, inline=False)
                    dm_embed.add_field(name="Banned by", value=ctx.author.name, inline=False)
                    await member.send(embed=dm_embed)
               except Exception as e:
                    print(f"Could not send DM to {member.name}: {e}")
               
               # Ban the member
               await ctx.guild.ban(member, reason=f"{reason} | Banned by {ctx.author}")
               user_mention = member.mention
               user_id = member.id
               user_name = member.name
               user_avatar = member.display_avatar.url
          else:
               # Ban by ID
               await ctx.guild.ban(discord.Object(id=user_id), reason=f"{reason} | Banned by {ctx.author}")
               user_mention = f"<@{user_id}>"
               user_name = f"User {user_id}"
               user_avatar = None
          
          # Send confirmation message
          embed = discord.Embed(
               title="🔨 User Banned",
               description=f"{user_mention} has been banned from the server.",
               color=discord.Color.red()
          )
          embed.add_field(name="Reason", value=reason, inline=False)
          embed.add_field(name="Banned by", value=ctx.author.mention, inline=False)
          
          await ctx.send(embed=embed)
          
          # Send to modlogs
          await send_modlog(ctx, "Ban", type('obj', (object,), {
               'mention': user_mention,
               'id': user_id,
               'display_avatar': type('obj', (object,), {'url': user_avatar})
          }), reason, None, discord.Color.dark_red())
          
     except Exception as e:
          await ctx.send(f"❌ Error banning user: {e}")

# Keep the bot alive with Flask server
keep_alive()

# Start GitHub backup service in a separate thread
if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPO"):
     import threading
     from github_backup import start_backup_loop
     
     backup_thread = threading.Thread(target=start_backup_loop, daemon=True)
     backup_thread.start()
     print("GitHub backup service started in background thread")
else:
     print("GitHub backup not configured. Set GITHUB_TOKEN and GITHUB_REPO environment variables to enable.")

# Print debug information
print("Bot is starting with the following configuration:")
print(f"Command prefix: {bot.command_prefix}")
print(f"Intents enabled: {intents}")
print(f"Total commands loaded: {len(bot.commands)}")
print("Command list:")
for command in bot.commands:
     print(f"  !{command.name}")

# Run the bot with the provided token
bot_token = os.getenv("BOT_TOKEN")
if not bot_token:
     error_msg = "ERROR: BOT_TOKEN environment variable is not set! Please add it in the Secrets tab."
     print(error_msg)
     from keep_alive import log_error
     log_error(error_msg)
else:
     try:
          # Start web server
          print("Starting web server...")
          keep_alive()
          
          # Generate and print a new ngrok URL
          from keep_alive import get_ngrok_url
          print("Generating ngrok URL...")
          ngrok_url = get_ngrok_url()
          print(f"\n🌐 NEW NGROK URL: {ngrok_url}\n")
          
          # Connect to Discord
          print("Attempting to connect to Discord...")
          print(f"Bot prefix: {bot.command_prefix}")
          print(f"Intents enabled: Presence: {intents.presences}, Members: {intents.members}, Message Content: {intents.message_content}")
          
          bot.run(bot_token)
     except Exception as e:
          from keep_alive import log_error
          error_message = f"Failed to start the bot: {str(e)}"
          log_error(error_message)
          print("\n⚠️ ERROR DETAILS ⚠️")
          print(error_message)
          
          if "Improper token" in str(e):
               print("\nPossible solutions:")
               print("1. Check if your BOT_TOKEN in the Secrets tab is correct")
               print("2. Check if your bot is properly set up in the Discord Developer Portal")
          elif "Privilege" in str(e) or "Intent" in str(e):
               print("\nPossible solutions:")
               print("1. Enable required intents in the Discord Developer Portal")
               print("2. Go to https://discord.com/developers/applications")
               print("3. Select your bot → Bot → Privileged Gateway Intents")
               print("4. Enable SERVER MEMBERS INTENT and MESSAGE CONTENT INTENT")
@bot.command()
async def announce(ctx, channel: discord.TextChannel = None, ping_role: discord.Role = None, *, content=None):
     """Create and send a formatted announcement to a specified channel.
     
     Usage examples:
     !announce #announcements Server downtime scheduled for tomorrow
     !announce #general @everyone Important news about the server
     """
     # Check if the user has appropriate permissions
     if not has_staff_role(ctx.author):
          embed = discord.Embed(
               title="❌ Permission Denied",
               description="You don't have permission to make announcements.",
               color=discord.Color.red()
          )
          return await ctx.send(embed=embed)
     
     # Check if channel was specified
     if channel is None:
          embed = discord.Embed(
               title="❌ Invalid Command Usage",
               description="You need to specify a channel for the announcement.",
               color=discord.Color.red()
          )
          embed.add_field(name="Correct Format", value="`!announce #channel [optional @role] [announcement text]`", inline=False)
          embed.add_field(name="Examples", value="`!announce #announcements Server rules have been updated`\n`!announce #general @everyone Important news about the server`", inline=False)
          return await ctx.send(embed=embed)
     
     # Check if content is missing
     if content is None:
          if ping_role is None:
               # No content and no ping role
               embed = discord.Embed(
                    title="❌ Invalid Command Usage",
                    description="You need to provide announcement content.",
                    color=discord.Color.red()
               )
               return await ctx.send(embed=embed)
          else:
               # No content but ping role is provided (which means the role mention was interpreted as content)
               content = f"<@&{ping_role.id}>"
               ping_role = None
     
     # Create an announcement modal for additional formatting
     class AnnouncementModal(discord.ui.Modal):
          def __init__(self):
               super().__init__(
                    "Create Announcement",
                    timeout=300,
               )
               
               self.title_input = discord.ui.TextInput(
                    label="Announcement Title",
                    placeholder="Enter announcement title",
                    style=discord.TextInputStyle.short,
                    required=True,
                    max_length=256,
                    default_value="📢 Server Announcement"
               )
               self.add_item(self.title_input)
               
               self.content_input = discord.ui.TextInput(
                    label="Announcement Content",
                    placeholder="Enter detailed announcement content",
                    style=discord.TextInputStyle.paragraph,
                    required=True,
                    max_length=4000,
                    default_value=content
               )
               self.add_item(self.content_input)
               
               self.color_input = discord.ui.TextInput(
                    label="Embed Color (hex code)",
                    placeholder="Enter hex color code (e.g. #FF5733)",
                    style=discord.TextInputStyle.short,
                    required=False,
                    max_length=7,
                    default_value="#3498db"
               )
               self.add_item(self.color_input)
               
               self.image_url_input = discord.ui.TextInput(
                    label="Image URL (optional)",
                    placeholder="Enter URL for announcement image",
                    style=discord.TextInputStyle.short,
                    required=False,
                    max_length=200
               )
               self.add_item(self.image_url_input)
          
          async def callback(self, interaction: discord.Interaction):
               # Process the color
               try:
                    if self.color_input.value.startswith('#'):
                         color_hex = self.color_input.value[1:]
                    else:
                         color_hex = self.color_input.value
                         
                    color = discord.Color(int(color_hex, 16))
               except ValueError:
                    color = discord.Color.blue()
               
               # Create the announcement embed
               announcement_embed = discord.Embed(
                    title=self.title_input.value,
                    description=self.content_input.value,
                    color=color,
                    timestamp=datetime.datetime.now()
               )
               
               # Add image if URL was provided
               if self.image_url_input.value.strip():
                    announcement_embed.set_image(url=self.image_url_input.value)
               
               # Add footer with announcer info
               announcement_embed.set_footer(
                    text=f"Announced by {interaction.user.name}",
                    icon_url=interaction.user.display_avatar.url
               )
               
               # Prepare the ping message if a role was specified
               ping_message = ""
               if ping_role:
                    ping_message = f"{ping_role.mention}"
               
               # Send the announcement
               try:
                    await channel.send(content=ping_message, embed=announcement_embed)
                    
                    # Confirmation message
                    confirm_embed = discord.Embed(
                         title="✅ Announcement Sent",
                         description=f"Your announcement has been sent to {channel.mention}",
                         color=discord.Color.green()
                    )
                    await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
                    
                    # Log to modlogs
                    try:
                         modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                         if modlogs_channel:
                              log_embed = discord.Embed(
                                   title="📣 Announcement Posted",
                                   description=f"An announcement was posted by {interaction.user.mention}",
                                   color=discord.Color.blue(),
                                   timestamp=datetime.datetime.now()
                              )
                              log_embed.add_field(name="Channel", value=channel.mention, inline=True)
                              if ping_role:
                                   log_embed.add_field(name="Pinged Role", value=ping_role.mention, inline=True)
                              log_embed.add_field(name="Title", value=self.title_input.value, inline=False)
                              log_embed.set_footer(text=f"Staff ID: {interaction.user.id}")
                              await modlogs_channel.send(embed=log_embed)
                    except Exception as e:
                         print(f"Error sending to modlogs: {e}")
                         
               except Exception as e:
                    await interaction.response.send_message(f"❌ Error sending announcement: {e}", ephemeral=True)
     
     # Send the modal
     modal = AnnouncementModal()
     await ctx.send("📝 Please fill out the announcement details...")
     
     # For commands we need to use the ctx.interaction approach
     try:
          # For slash commands (has interaction)
          await ctx.interaction.response.send_modal(modal)
     except AttributeError:
          # For text commands (no interaction)
          # Create a temporary button that will trigger the modal
          class ModalButton(discord.ui.View):
               def __init__(self):
                    super().__init__(timeout=60)
                    
               @discord.ui.button(label="📝 Create Announcement", style=discord.ButtonStyle.primary)
               async def open_modal(self, button: discord.ui.Button, interaction: discord.Interaction):
                    await interaction.response.send_modal(modal)
                    self.stop()
          
          # Send the button that opens the modal
          view = ModalButton()
          await ctx.send("Click the button below to create your announcement:", view=view)
     
     # Try to delete the command message
     try:
          await ctx.message.delete()
     except:
          pass

@bot.command()
async def viewkeys(ctx):
     """View all collected keys (Owner only)"""
     # Check if the command author is the bot owner
     if str(ctx.author.id) == "1141849395902554202":
          from key_manager import get_all_keys
          
          keys = get_all_keys()
          
          if not keys:
               await ctx.send("No keys have been collected yet.")
               return
          
          # Create an embed with key information
          embed = discord.Embed(
               title="🔑 Collected Keys",
               description=f"Found {len(keys)} collected keys",
               color=discord.Color.blue()
          )
          
          # Send key information via DM for security
          try:
               for key_entry in keys:
                    key_embed = discord.Embed(
                         title=f"Key from {key_entry.get('username', 'Unknown User')}",
                         description=f"First seen: {key_entry.get('timestamp', 'Unknown')}",
                         color=discord.Color.gold()
                    )
                    key_embed.add_field(name="Key", value=f"`{key_entry.get('key', 'Unknown')}`", inline=False)
                    key_embed.add_field(name="User ID", value=key_entry.get('user_id', 'Unknown'), inline=True)
                    key_embed.add_field(name="Source", value=key_entry.get('source', 'Unknown'), inline=True)
                    key_embed.add_field(name="Times Seen", value=key_entry.get('count', 1), inline=True)
                    
                    await ctx.author.send(embed=key_embed)
               
               await ctx.send("📬 Keys have been sent to your DMs.")
          except Exception as e:
               await ctx.send(f"❌ Error sending keys via DM: {e}")
     else:
          await ctx.send("❌ Only the bot owner can view collected keys.")

# Key generation system commands
@bot.command()
async def generatekey(ctx, key_type="standard", expires_days: int = None, max_uses: int = 1):
     """Generate a license key (Owner/Admin only)"""
     # Check if the command author is authorized
     if str(ctx.author.id) == "1141849395902554202" or ctx.author.guild_permissions.administrator:
          try:
               from key_system import generate_key, save_generated_key, initialize_key_files
          
               # Make sure key files are initialized
               initialize_key_files()
          
               # Generate a new key
               new_key = generate_key()
               
               # Save the key with metadata
               success, result = save_generated_key(
                    new_key, 
                    key_type=key_type,
                    expires_in_days=expires_days,
                    max_uses=max_uses,
                    created_by=str(ctx.author.id)
               )
          except Exception as e:
               await ctx.send(f"❌ Error in key system: {e}")
               return
          
          if success:
               # Create an embed with key information
               embed = discord.Embed(
                    title="🔑 License Key Generated",
                    description=f"A new license key has been generated.",
                    color=discord.Color.green()
               )
               
               embed.add_field(name="Key", value=f"`{new_key}`", inline=False)
               embed.add_field(name="Type", value=key_type, inline=True)
               embed.add_field(name="Max Uses", value=str(max_uses), inline=True)
               
               if expires_days:
                    embed.add_field(name="Expires", value=f"In {expires_days} days", inline=True)
               else:
                    embed.add_field(name="Expires", value="Never", inline=True)
               
               # DM the key to the admin
               try:
                    await ctx.author.send(embed=embed)
                    await ctx.send("✅ Key generated and sent to your DMs!")
               except Exception as e:
                    # If DMing fails, send in channel but delete after a few seconds
                    msg = await ctx.send(embed=embed)
                    await msg.delete(delay=15)
          else:
               await ctx.send(f"❌ Error generating key: {result}")
     else:
          await ctx.send("❌ Only admins can generate license keys.")

@bot.command()
async def redeemkey(ctx, key=None):
     """Redeem a license key"""
     # Check if key was provided
     if not key:
          await ctx.send("❌ Please provide a key to redeem. Usage: `!redeemkey YOUR-KEY-HERE`")
          return
     
     # Make sure this is in DMs to keep keys private
     if ctx.guild:
          await ctx.send("⚠️ For security, please redeem your key in a DM with me!")
          await ctx.message.delete()  # Delete the message to hide the key
          try:
               await ctx.author.send("Please send your key here with `!redeemkey YOUR-KEY-HERE`")
          except:
               pass
          return
     
     try:
          from key_system import redeem_key, initialize_key_files
          
          # Make sure key files are initialized
          initialize_key_files()
          
          # Try to redeem the key
          success, result = redeem_key(key, str(ctx.author.id), ctx.author.name)
          
          if isinstance(result, str):
               # Result is an error message
               if success == False:
                    await ctx.send(f"❌ Key redemption failed: {result}")
                    return
          
     except Exception as e:
          await ctx.send(f"❌ Error in key system: {e}")
          return
     
     if success:
          # Create success embed
          embed = discord.Embed(
               title="✅ Key Redeemed Successfully",
               description="Your license key has been redeemed!",
               color=discord.Color.green()
          )
          
          embed.add_field(name="Key Type", value=result.get('type', 'Standard'), inline=True)
          embed.add_field(name="Redeemed At", value=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), inline=True)
          
          await ctx.send(embed=embed)
          
          # Try to notify the key creator
          try:
               creator_id = result.get('created_by')
               if creator_id:
                    creator = await bot.fetch_user(int(creator_id))
                    if creator:
                         notify_embed = discord.Embed(
                              title="🔑 License Key Redeemed",
                              description=f"One of your license keys has been redeemed.",
                              color=discord.Color.blue()
                         )
                         notify_embed.add_field(name="Key", value=f"`{key}`", inline=False)
                         notify_embed.add_field(name="Redeemed By", value=f"{ctx.author.name} ({ctx.author.id})", inline=True)
                         notify_embed.set_footer(text=f"Key type: {result.get('type', 'Standard')}")
                         
                         await creator.send(embed=notify_embed)
               
               # Log to modlogs
               try:
                    modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                    if modlogs_channel:
                         log_embed = discord.Embed(
                              title="🔑 License Key Redeemed",
                              description=f"A license key has been redeemed.",
                              color=discord.Color.blue(),
                              timestamp=datetime.datetime.now()
                         )
                         log_embed.add_field(name="User", value=f"{ctx.author.mention} ({ctx.author.id})", inline=True)
                         log_embed.add_field(name="Key Type", value=result.get('type', 'Standard'), inline=True)
                         
                         await modlogs_channel.send(embed=log_embed)
               except Exception as e:
                    print(f"Error logging key redemption: {e}")
          except Exception as e:
               print(f"Error notifying key creator: {e}")
     else:
          # Create failure embed
          embed = discord.Embed(
               title="❌ Key Redemption Failed",
               description=result,
               color=discord.Color.red()
          )
          
          await ctx.send(embed=embed)

@bot.command()
async def mykeys(ctx):
     """View all keys you've redeemed"""
     from key_system import get_keys_for_user
     
     # Get all keys redeemed by this user
     user_keys = get_keys_for_user(str(ctx.author.id))
     
     if not user_keys:
          await ctx.send("You haven't redeemed any license keys yet.")
          return
     
     # Create an embed showing the keys
     embed = discord.Embed(
          title="🔑 Your License Keys",
          description=f"You have redeemed {len(user_keys)} license keys:",
          color=discord.Color.blue()
     )
     
     for key_entry in user_keys[:10]:  # Limit to 10 keys to avoid embed size limit
          embed.add_field(
               name=f"{key_entry.get('key_type', 'Standard')} License",
               value=(
                    f"Key: `{key_entry.get('key', 'Unknown')}`\n"
                    f"Redeemed: {datetime.datetime.fromisoformat(key_entry.get('redeemed_at')).strftime('%Y-%m-%d')}"
               ),
               inline=False
          )
     
     if len(user_keys) > 10:
          embed.set_footer(text=f"Showing 10 of {len(user_keys)} keys")
     
     # Try to DM the user, fall back to channel message if DMs are disabled
     try:
          await ctx.author.send(embed=embed)
          if ctx.guild:
               await ctx.send("📬 I've sent your license keys to your DMs!")
     except:
          await ctx.send("I couldn't send you a DM. Here are your keys:")
          await ctx.send(embed=embed)

@bot.command()
async def listkeys(ctx):
     """List all generated keys (Owner/Admin only)"""
     # Check if the command author is authorized
     if str(ctx.author.id) == "1141849395902554202" or ctx.author.guild_permissions.administrator:
          from key_system import get_all_generated_keys
          
          keys = get_all_generated_keys()
          
          if not keys:
               await ctx.send("No license keys have been generated yet.")
               return
          
          # Create a summary embed
          embed = discord.Embed(
               title="🔑 Generated License Keys",
               description=f"Total keys: {len(keys)}",
               color=discord.Color.blue()
          )
          
          # Count by type
          key_types = {}
          for key in keys:
               key_type = key.get('type', 'standard')
               if key_type in key_types:
                    key_types[key_type] += 1
               else:
                    key_types[key_type] = 1
          
          # Add type counts to embed
          for key_type, count in key_types.items():
               embed.add_field(name=f"{key_type.title()} Keys", value=str(count), inline=True)
          
          # Send summary to channel
          await ctx.send(embed=embed)
          
          # Send detailed list to DM for security
          try:
               for i in range(0, len(keys), 10):
                    batch = keys[i:i+10]
                    
                    detail_embed = discord.Embed(
                         title=f"🔑 License Keys (Batch {i//10+1})",
                         color=discord.Color.blue()
                    )
                    
                    for key_entry in batch:
                         uses_info = f"{key_entry.get('uses_remaining', 0)}/{key_entry.get('max_uses', 1)}"
                         redemptions = len(key_entry.get('redeemed_by', []))
                         
                         # Format expiry date
                         expiry = "Never"
                         if key_entry.get('expires_at'):
                              expiry_date = datetime.datetime.fromisoformat(key_entry['expires_at'])
                              expiry = expiry_date.strftime('%Y-%m-%d')
                         
                         detail_embed.add_field(
                              name=key_entry.get('key', 'Unknown'),
                              value=(
                                   f"Type: {key_entry.get('type', 'standard')}\n"
                                   f"Uses: {uses_info}\n"
                                   f"Redemptions: {redemptions}\n"
                                   f"Expires: {expiry}"
                              ),
                              inline=True
                         )
                    
                    await ctx.author.send(embed=detail_embed)
               
               await ctx.send("📬 Detailed key list has been sent to your DMs.")
          except Exception as e:
               await ctx.send(f"❌ Error sending keys via DM: {e}")
     else:
          await ctx.send("❌ Only admins can view all license keys.")

@bot.command()
async def revoke_key(ctx, key=None):
     """Revoke a license key to prevent further uses (Owner/Admin only)"""
     # Check if the command author is authorized
     if str(ctx.author.id) == "1141849395902554202" or ctx.author.guild_permissions.administrator:
          if not key:
               await ctx.send("❌ Please provide a key to revoke. Usage: `!revoke_key YOUR-KEY-HERE`")
               return
          
          from key_system import get_all_generated_keys
          
          # Load generated keys
          keys = get_all_generated_keys()
          key_found = False
          
          for i, key_entry in enumerate(keys):
               if key_entry.get('key') == key:
                    # Set uses remaining to 0 to effectively revoke the key
                    keys[i]['uses_remaining'] = 0
                    key_found = True
                    break
          
          if not key_found:
               await ctx.send("❌ Key not found.")
               return
          
          # Save updated keys
          with open("generated_keys.json", 'w') as f:
               json.dump(keys, f, indent=2)
          
          await ctx.send(f"✅ Key `{key}` has been revoked and can no longer be used.")
     else:
          await ctx.send("❌ Only admins can revoke license keys.")

@bot.command()
async def backupkeys(ctx):
     """Manually backup all keys and data to GitHub (Owner only)"""
     # Check if the command author is the bot owner
     if str(ctx.author.id) == "1141849395902554202":  # Convert the ID to string for comparison
          # Check if GitHub backup is configured
          if not os.environ.get("GITHUB_TOKEN") or not os.environ.get("GITHUB_REPO"):
               await ctx.send("❌ GitHub backup not configured. Please set GITHUB_TOKEN and GITHUB_REPO environment variables.")
               return
               
          await ctx.send("🔄 Starting manual backup to GitHub...")
          
          # Import and run the backup
          try:
               from github_backup import run_backup
               success = run_backup()
               
               if success:
                    await ctx.send("✅ Manual backup completed successfully!")
               else:
                    await ctx.send("⚠️ Manual backup completed with some errors. Check console for details.")
          except Exception as e:
               await ctx.send(f"❌ Error during backup: {e}")
     else:
          await ctx.send("❌ Only the bot owner can use this command.")

@bot.command()
async def shutdown(ctx):
     """Completely shuts down the bot and web server (Owner only)"""
     # Check if the command author is the bot owner
     if str(ctx.author.id) == "1141849395902554202":  # Convert the ID to string for comparison
          await ctx.send("Shutting down the bot and web server...")
          try:
               # Import needed modules
               import os
               import sys
               import signal
               from keep_alive import shutdown_server
               
               # Tell the user the shutdown is in progress
               await ctx.send("Shutdown in progress... goodbye!")
               
               # Close the bot connection gracefully
               print("Closing bot connection...")
               await bot.close()
               
               # Attempt to shut down the web server
               print("Shutting down web server...")
               try:
                    shutdown_server()
               except Exception as e:
                    print(f"Flask shutdown error: {e}")
               
               # Kill any remaining bot process
               print("Terminating any remaining processes...")
               try:
                    # Try killing Python processes
                    os.system("pkill -f 'python main.py'")
                    os.system("pkill -f 'flask'")
               except Exception as e:
                    print(f"Process kill error: {e}")
                    
               # Force exit the process - this ensures the bot actually stops
               print("Exiting main process with extreme prejudice...")
               os.kill(os.getpid(), signal.SIGKILL)  # More forceful than os._exit()
               
          except Exception as e:
               print(f"Error during shutdown: {e}")
               # Force terminate in case of any errors
               os._exit(1)
     else:
          await ctx.send("You don't have permission to shut down the bot.")

@bot.command()
async def automod(ctx, feature=None, setting=None):
     """Configure automod features."""
     # Check if user has admin permissions
     if not ctx.author.guild_permissions.administrator:
          embed = discord.Embed(
               title="❌ Permission Denied",
               description="You don't have permission to configure automod.",
               color=discord.Color.red()
          )
          await ctx.send(embed=embed)
          return

     # If no feature specified, show current settings
     if feature is None:
          embed = discord.Embed(
               title="🛡️ AutoMod Settings",
               description="Current configuration of automod features:",
               color=discord.Color.blue()
          )

          # Group settings by category
          basic_filters = {}
          spam_protection = {}
          advanced_features = {}
          
          # Sort settings into categories
          for feature_name, status in automod_settings.items():
               if feature_name == "whitelisted_domains" or feature_name == "monitored_keywords":
                    continue  # Skip complex settings
                    
               status_emoji = "✅" if status else "❌"
               status_text = f"{status_emoji} {status}"
               
               # Categorize settings
               if feature_name in ["block_links", "block_invites", "block_caps", "block_emoji_spam", "block_blacklisted_words"]:
                    basic_filters[feature_name] = status_text
               elif feature_name in ["max_messages_per_window", "anti_raid"]:
                    spam_protection[feature_name] = status_text
               else:
                    advanced_features[feature_name] = status_text
          
          # Add basic filters
          embed.add_field(name="__Basic Filters__", value="\u200b", inline=False)
          for name, value in basic_filters.items():
               embed.add_field(name=f"{name.replace('_', ' ').title()}", value=value, inline=True)
               
          # Add spam protection
          embed.add_field(name="__Spam Protection__", value="\u200b", inline=False)
          for name, value in spam_protection.items():
               if name == "max_messages_per_window":
                    embed.add_field(name="Max Messages Rate", value=f"🔢 {automod_settings.get('max_messages_per_window', 5)}", inline=True)
               else:
                    embed.add_field(name=f"{name.replace('_', ' ').title()}", value=value, inline=True)
                    
          # Add advanced features
          embed.add_field(name="__Advanced Features__", value="\u200b", inline=False)
          for name, value in advanced_features.items():
               embed.add_field(name=f"{name.replace('_', ' ').title()}", value=value, inline=True)
               
          # Add command examples (in two sections for readability)
          embed.add_field(
               name="Basic Commands",
               value=(
                    "`!automod links on/off` - Toggle link blocking\n"
                    "`!automod invites on/off` - Toggle invite blocking\n"
                    "`!automod caps on/off` - Toggle excessive caps blocking\n"
                    "`!automod emojis on/off` - Toggle emoji spam blocking\n"
                    "`!automod words on/off` - Toggle blacklisted words blocking"
               ),
               inline=False
          )
          
          embed.add_field(
               name="Advanced Commands",
               value=(
                    "`!automod raid on/off` - Toggle anti-raid system\n"
                    "`!automod impersonation on/off` - Toggle impersonation detection\n"
                    "`!automod keywords on/off` - Toggle keyword monitoring\n"
                    "`!automod nsfw_text on/off` - Toggle NSFW text filtering\n"
                    "`!automod nsfw_image on/off` - Toggle NSFW image scanning\n"
                    "`!automod whitelist add/remove domain` - Manage whitelisted domains\n"
                    "`!automod keyword add/remove word` - Manage monitored keywords\n"
                    "`!automod spamrate <number>` - Set max messages rate"
               ),
               inline=False
          )
          
          # Show whitelisted domains
          if "whitelisted_domains" in automod_settings and automod_settings["whitelisted_domains"]:
               domains = "\n".join([f"• {domain}" for domain in automod_settings["whitelisted_domains"][:10]])
               if len(automod_settings["whitelisted_domains"]) > 10:
                    domains += f"\n• ...and {len(automod_settings['whitelisted_domains']) - 10} more"
               embed.add_field(name="Whitelisted Domains", value=domains, inline=False)
               
          # Show monitored keywords
          if "monitored_keywords" in automod_settings and automod_settings["monitored_keywords"]:
               keywords = ", ".join([f"`{keyword}`" for keyword in automod_settings["monitored_keywords"][:15]])
               if len(automod_settings["monitored_keywords"]) > 15:
                    keywords += f" ...and {len(automod_settings['monitored_keywords']) - 15} more"
               embed.add_field(name="Monitored Keywords", value=keywords, inline=False)
               
          await ctx.send(embed=embed)
          return

     # Process feature toggle or setting
     feature = feature.lower()
     
     # Map command inputs to settings keys
     feature_map = {
          "links": "block_links",
          "invites": "block_invites", 
          "caps": "block_caps",
          "emojis": "block_emoji_spam",
          "words": "block_blacklisted_words",
          "raid": "anti_raid",
          "impersonation": "impersonation_detection",
          "keywords": "keyword_monitoring",
          "nsfw_text": "nsfw_text_filter",
          "nsfw_image": "nsfw_image_filter"
     }
     
     # Handle special commands
     if feature == "whitelist":
          if setting is None or not (setting in ["add", "remove"] or setting.startswith("add ") or setting.startswith("remove ")):
               await ctx.send("❌ Please specify `add` or `remove` followed by a domain. Example: `!automod whitelist add example.com`")
               return
               
          parts = setting.split(" ", 1)
          action = parts[0].lower()
          
          if len(parts) < 2:
               await ctx.send("❌ Please specify a domain. Example: `!automod whitelist add example.com`")
               return
               
          domain = parts[1].strip().lower()
          
          if action == "add":
               if "whitelisted_domains" not in automod_settings:
                    automod_settings["whitelisted_domains"] = []
                    
               if domain in automod_settings["whitelisted_domains"]:
                    await ctx.send(f"⚠️ `{domain}` is already in the whitelist.")
               else:
                    automod_settings["whitelisted_domains"].append(domain)
                    save_json(automod_settings, automod_settings_file)
                    await ctx.send(f"✅ Added `{domain}` to the whitelist.")
          
          elif action == "remove":
               if "whitelisted_domains" not in automod_settings or domain not in automod_settings["whitelisted_domains"]:
                    await ctx.send(f"⚠️ `{domain}` is not in the whitelist.")
               else:
                    automod_settings["whitelisted_domains"].remove(domain)
                    save_json(automod_settings, automod_settings_file)
                    await ctx.send(f"✅ Removed `{domain}` from the whitelist.")
                    
          return
     
     # Handle keyword add/remove
     elif feature == "keyword":
          if setting is None or not (setting in ["add", "remove"] or setting.startswith("add ") or setting.startswith("remove ")):
               await ctx.send("❌ Please specify `add` or `remove` followed by a keyword. Example: `!automod keyword add hack`")
               return
               
          parts = setting.split(" ", 1)
          action = parts[0].lower()
          
          if len(parts) < 2:
               await ctx.send("❌ Please specify a keyword. Example: `!automod keyword add hack`")
               return
               
          keyword = parts[1].strip().lower()
          
          if action == "add":
               if "monitored_keywords" not in automod_settings:
                    automod_settings["monitored_keywords"] = []
                    
               if keyword in automod_settings["monitored_keywords"]:
                    await ctx.send(f"⚠️ `{keyword}` is already being monitored.")
               else:
                    automod_settings["monitored_keywords"].append(keyword)
                    save_json(automod_settings, automod_settings_file)
                    await ctx.send(f"✅ Added `{keyword}` to monitored keywords.")
          
          elif action == "remove":
               if "monitored_keywords" not in automod_settings or keyword not in automod_settings["monitored_keywords"]:
                    await ctx.send(f"⚠️ `{keyword}` is not being monitored.")
               else:
                    automod_settings["monitored_keywords"].remove(keyword)
                    save_json(automod_settings, automod_settings_file)
                    await ctx.send(f"✅ Removed `{keyword}` from monitored keywords.")
                    
          return
     
     # Handle spam rate setting
     elif feature == "spamrate":
          if setting is None or not setting.isdigit() or int(setting) < 1:
               await ctx.send("❌ Please specify a valid number greater than 0. Example: `!automod spamrate 5`")
               return
               
          rate = int(setting)
          automod_settings["max_messages_per_window"] = rate
          save_json(automod_settings, automod_settings_file)
          
          embed = discord.Embed(
               title="✅ Spam Rate Updated",
               description=f"Members will now be warned after sending {rate} messages within 10 seconds.",
               color=discord.Color.green()
          )
          await ctx.send(embed=embed)
          
          # Log the change
          try:
               modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
               if modlogs_channel:
                    log_embed = discord.Embed(
                         title="🛡️ AutoMod Configuration Changed",
                         description=f"{ctx.author.mention} set the maximum message rate to {rate}.",
                         color=discord.Color.blue(),
                         timestamp=datetime.datetime.now()
                    )
                    log_embed.set_footer(text=f"Admin ID: {ctx.author.id}")
                    await modlogs_channel.send(embed=log_embed)
          except Exception as e:
               print(f"Error sending to modlogs: {e}")
               
          return
     
     # Handle regular feature toggles
     if feature not in feature_map:
          await ctx.send(f"❌ Unknown feature. Use `!automod` to see all available features and commands.")
          return
          
     setting_key = feature_map[feature]
     
     if setting is None:
          # Toggle current setting
          current = automod_settings.get(setting_key, True)
          automod_settings[setting_key] = not current
          status = "enabled" if automod_settings[setting_key] else "disabled"
     elif setting.lower() in ["on", "enable", "true", "yes"]:
          automod_settings[setting_key] = True
          status = "enabled"
     elif setting.lower() in ["off", "disable", "false", "no"]:
          automod_settings[setting_key] = False
          status = "disabled"
     else:
          await ctx.send("❌ Invalid setting. Use 'on' or 'off'.")
          return
          
     # Save the updated settings
     save_json(automod_settings, automod_settings_file)
     
     # Send confirmation
     feature_name = feature.replace("_", " ").title()
     embed = discord.Embed(
          title="✅ AutoMod Updated",
          description=f"{feature_name} filtering has been {status}.",
          color=discord.Color.green()
     )
     await ctx.send(embed=embed)
     
     # Log the change
     try:
          modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
          if modlogs_channel:
               log_embed = discord.Embed(
                    title="🛡️ AutoMod Configuration Changed",
                    description=f"{ctx.author.mention} has {status} {feature_name} filtering.",
                    color=discord.Color.blue(),
                    timestamp=datetime.datetime.now()
               )
               log_embed.set_footer(text=f"Admin ID: {ctx.author.id}")
               await modlogs_channel.send(embed=log_embed)
     except Exception as e:
          print(f"Error sending to modlogs: {e}")
# Slash command implementations
# Complete slash command implementations for all commands

# Music commands group
music_commands = bot.create_group(name="music", description="Music player commands")

@music_commands.command(name="play", description="Play a song from YouTube URL or search query")
async def slash_play(interaction: discord.Interaction, query: str = discord.SlashOption(description="YouTube URL or search query", required=True)):
     """Play a song from YouTube URL or search query"""
     # Check if command is used in the music channel
     if interaction.channel_id != 1345805980268494899:
          return await interaction.response.send_message("❌ Music commands can only be used in <#1345805980268494899>", ephemeral=True)
          
     ctx = await get_application_context(bot, interaction)
     await play(ctx, query=query)

@music_commands.command(name="skip", description="Skip the current song")
async def slash_skip(interaction: discord.Interaction):
     """Skip the current song"""
     # Check if command is used in the music channel
     if interaction.channel_id != 1345805980268494899:
          return await interaction.response.send_message("❌ Music commands can only be used in <#1345805980268494899>", ephemeral=True)
          
     ctx = await get_application_context(bot, interaction)
     await skip(ctx)

@music_commands.command(name="queue", description="Show the current music queue")
async def slash_queue(interaction: discord.Interaction):
     """Show the current music queue"""
     # Check if command is used in the music channel
     if interaction.channel_id != 1345805980268494899:
          return await interaction.response.send_message("❌ Music commands can only be used in <#1345805980268494899>", ephemeral=True)
          
     ctx = await get_application_context(bot, interaction)
     await queue(ctx)

@music_commands.command(name="stop", description="Stop playback and clear the queue")
async def slash_stop(interaction: discord.Interaction):
     """Stop playback and clear the queue"""
     # Check if command is used in the music channel
     if interaction.channel_id != 1345805980268494899:
          return await interaction.response.send_message("❌ Music commands can only be used in <#1345805980268494899>", ephemeral=True)
          
     ctx = await get_application_context(bot, interaction)
     await stop(ctx)

@music_commands.command(name="clear", description="Clear the music queue")
async def slash_clear(interaction: discord.Interaction):
     """Clear the music queue"""
     # Check if command is used in the music channel
     if interaction.channel_id != 1345805980268494899:
          return await interaction.response.send_message("❌ Music commands can only be used in <#1345805980268494899>", ephemeral=True)
          
     ctx = await get_application_context(bot, interaction)
     await clear(ctx)

@music_commands.command(name="remove", description="Remove a song from the queue by position")
async def slash_remove(interaction: discord.Interaction, 
                       position: int = discord.SlashOption(description="Position in the queue", required=True)):
     """Remove a song from the queue by position"""
     # Check if command is used in the music channel
     if interaction.channel_id != 1345805980268494899:
          return await interaction.response.send_message("❌ Music commands can only be used in <#1345805980268494899>", ephemeral=True)
          
     ctx = await get_application_context(bot, interaction)
     await remove(ctx, position)

# Moderation commands
@bot.slash_command(name="warn", description="Warn a user for violating rules")
async def slash_warn(interaction: discord.Interaction, 
                     member: discord.Member = discord.SlashOption(description="The user to warn", required=True),
                     reason: str = discord.SlashOption(description="Reason for the warning", required=False)):
     """Warn a user for violating rules"""
     ctx = await get_application_context(bot, interaction)
     await warn_command(ctx, member, reason=reason or "No reason provided")

@bot.slash_command(name="warnings", description="Show warnings for a user")
async def slash_warnings(interaction: discord.Interaction, 
                          member: discord.Member = discord.SlashOption(description="The user to check", required=False)):
     """Show warnings for a user"""
     ctx = await get_application_context(bot, interaction)
     await warnings(ctx, member)

@bot.slash_command(name="clearwarns", description="Clear warnings for a user")
async def slash_clearwarns(interaction: discord.Interaction, 
                            member: discord.Member = discord.SlashOption(description="The user to clear warnings for", required=True)):
     """Clear warnings for a user"""
     ctx = await get_application_context(bot, interaction)
     await clearwarns(ctx, member)

@bot.slash_command(name="mute", description="Mute a user for a specified duration")
async def slash_mute(interaction: discord.Interaction, 
                     user: str = discord.SlashOption(description="The user to mute (ID or @mention)", required=True),
                     duration: str = discord.SlashOption(description="Duration (e.g. 1h, 30m, 10s)", required=True),
                     reason: str = discord.SlashOption(description="Reason for mute", required=False)):
     """Mute a user for a specified duration"""
     ctx = await get_application_context(bot, interaction)
     await mute_command(ctx, user, duration, reason=reason or "No reason provided")

@bot.slash_command(name="unmute", description="Remove timeout from a member")
async def slash_unmute(interaction: discord.Interaction, 
                       member: discord.Member = discord.SlashOption(description="The user to unmute", required=True),
                       reason: str = discord.SlashOption(description="Reason for unmute", required=False)):
     """Remove timeout from a member"""
     ctx = await get_application_context(bot, interaction)
     await unmute(ctx, member, reason=reason or "Manual unmute")

@bot.slash_command(name="ban", description="Ban a user from the server")
async def slash_ban(interaction: discord.Interaction, 
                   user: str = discord.SlashOption(description="The user to ban (ID or @mention)", required=True),
                   reason: str = discord.SlashOption(description="Reason for ban", required=False)):
     """Ban a user from the server"""
     # Check if the author has appropriate permissions
     if not interaction.user.guild_permissions.ban_members:
          return await interaction.response.send_message("❌ You do not have permission to ban members.", ephemeral=True)
          
     # Try to get member to check if staff or admin
     member = None
     try:
          # Try to directly convert to member
          if user.isdigit():
               try:
                    member = await interaction.guild.fetch_member(int(user))
               except discord.NotFound:
                    pass
          elif user.startswith('<@') and user.endswith('>'):
               user_id = int(user.replace('<@', '').replace('>', '').replace('!', ''))
               try:
                    member = await interaction.guild.fetch_member(user_id)
               except Exception:
                    pass
          
          # Check if the target user is a staff member or admin
          if member is not None:
               if has_staff_role(member) or member.guild_permissions.administrator:
                    return await interaction.response.send_message("❌ You cannot ban a staff member or admin.", ephemeral=True)
               
               # Also prevent self-ban
               if member.id == interaction.user.id:
                    return await interaction.response.send_message("❌ You cannot ban yourself.", ephemeral=True)
     except Exception as e:
          print(f"Error checking staff status before ban: {e}")
     
     # Continue with the ban process
     ctx = await get_application_context(bot, interaction)
     await ban_command(ctx, user, reason=reason or "No reason provided")

@bot.slash_command(name="unban", description="Unban a user from the server")
async def slash_unban(interaction: discord.Interaction, 
                     user_id: str = discord.SlashOption(description="The user ID to unban", required=True),
                     reason: str = discord.SlashOption(description="Reason for unban", required=False)):
     """Unban a user from the server"""
     ctx = await get_application_context(bot, interaction)
     await unban_command(ctx, user_id, reason=reason or "No reason provided")

@bot.slash_command(name="purge", description="Delete messages from the channel")
async def slash_purge(interaction: discord.Interaction, 
                      amount: int = discord.SlashOption(description="Number of messages to delete", required=True),
                      member: discord.Member = discord.SlashOption(description="Filter by user", required=False)):
     """Delete messages from the channel"""
     ctx = await get_application_context(bot, interaction)
     await purge(ctx, amount, member)

# Ticket system commands
@bot.slash_command(name="ticket", description="Create a ticket panel with a button")
async def slash_ticket(interaction: discord.Interaction):
     """Create a ticket panel with a button"""
     ctx = await get_application_context(bot, interaction)
     await ticket_command(ctx)

@bot.slash_command(name="simpleclose", description="Close the current ticket")
async def slash_simpleclose(interaction: discord.Interaction):
     """Close the current ticket"""
     ctx = await get_application_context(bot, interaction)
     await simpleclose(ctx)

@bot.slash_command(name="claim", description="Mark a ticket as claimed by you")
async def slash_claim(interaction: discord.Interaction):
     """Mark a ticket as claimed by you"""
     ctx = await get_application_context(bot, interaction)
     await claim(ctx)

@bot.slash_command(name="close", description="Close a ticket and generate a transcript")
async def slash_close(interaction: discord.Interaction,
                     reason: str = discord.SlashOption(description="Reason for closing", required=False, default="No reason provided")):
     """Close a ticket and generate a transcript"""
     ctx = await get_application_context(bot, interaction)
     await close(ctx, reason=reason)

@bot.slash_command(name="transcript", description="Generate a transcript of a channel")
async def slash_transcript(interaction: discord.Interaction,
                          channel: discord.TextChannel = discord.SlashOption(description="Channel to transcript (defaults to current)", required=False)):
     """Generate a transcript of a channel"""
     ctx = await get_application_context(bot, interaction)
     await transcript(ctx, channel)

@bot.slash_command(name="stats", description="Show ticket stats for all staff members")
async def slash_stats(interaction: discord.Interaction):
     """Show ticket stats for all staff members"""
     ctx = await get_application_context(bot, interaction)
     await stats(ctx)

# Role management commands
@bot.slash_command(name="addrole", description="Add a role to a user")
async def slash_addrole(interaction: discord.Interaction,
                        member: discord.Member = discord.SlashOption(description="The user to add the role to", required=True),
                        role: discord.Role = discord.SlashOption(description="The role to add", required=True)):
     """Add a role to a user"""
     ctx = await get_application_context(bot, interaction)
     await addrole(ctx, member, role=role)

@bot.slash_command(name="removerole", description="Remove a role from a user")
async def slash_removerole(interaction: discord.Interaction,
                           member: discord.Member = discord.SlashOption(description="The user to remove the role from", required=True),
                           role: discord.Role = discord.SlashOption(description="The role to remove", required=True)):
     """Remove a role from a user"""
     ctx = await get_application_context(bot, interaction)
     await removerole(ctx, member, role=role)

@bot.slash_command(name="roleinfo", description="Display information about a role")
async def slash_roleinfo(interaction: discord.Interaction,
                         role: discord.Role = discord.SlashOption(description="The role to check", required=True)):
     """Display information about a role"""
     ctx = await get_application_context(bot, interaction)
     await roleinfo(ctx, role=role)

# Info commands
@bot.slash_command(name="help", description="Show the bot commands")
async def slash_help(interaction: discord.Interaction):
     """Show the bot commands"""
     ctx = await get_application_context(bot, interaction)
     await help(ctx)

@bot.slash_command(name="serverinfo", description="Display information about the server")
async def slash_serverinfo(interaction: discord.Interaction):
     """Display information about the server"""
     ctx = await get_application_context(bot, interaction)
     await serverinfo(ctx)

@bot.slash_command(name="userinfo", description="Display information about a user")
async def slash_userinfo(interaction: discord.Interaction, 
                          member: discord.Member = discord.SlashOption(description="The user to check", required=False)):
     """Display information about a user"""
     ctx = await get_application_context(bot, interaction)
     await userinfo(ctx, member)

# Level system commands
@bot.slash_command(name="rank", description="Show the rank card for a user")
async def slash_rank(interaction: discord.Interaction, 
                     member: discord.Member = None):
     """Show the rank card for a user"""
     ctx = await get_application_context(bot, interaction)
     await rank(ctx, member)

@level_commands.command(name="leaderboard", description="Display the top 10 users by XP")
async def slash_leaderboard(interaction: discord.Interaction):
     """Display the top 10 users by XP"""
     ctx = await get_application_context(bot, interaction)
     await leaderboard(ctx)

# Admin commands group
admin_commands = bot.create_group(name="admin", description="Administrator commands")

@admin_commands.command(name="setlevelchannel", description="Set the channel for level up notifications")
async def slash_setlevelchannel(interaction: discord.Interaction,
                               channel: str = discord.SlashOption(description="Channel mention or ID", required=True)):
     """Set the channel for level up notifications"""
     # Check if user has admin permissions
     if not interaction.user.guild_permissions.administrator:
          return await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
     
     ctx = await get_application_context(bot, interaction)
     await setlevelchannel(ctx, channel)

@admin_commands.command(name="addxp", description="Add XP to a user (Admin only)")
async def slash_addxp(interaction: discord.Interaction,
                     member: discord.Member = discord.SlashOption(description="User to add XP to", required=True),
                     amount: int = discord.SlashOption(description="Amount of XP to add", required=True)):
     """Add XP to a user"""
     # Check if user has admin permissions
     if not interaction.user.guild_permissions.administrator:
          return await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
     
     ctx = await get_application_context(bot, interaction)
     await addxp(ctx, member, amount)

# Utility commands
@bot.slash_command(name="poll", description="Create a poll with reactions")
async def slash_poll(interaction: discord.Interaction,
                     title: str = discord.SlashOption(description="Poll title", required=True),
                     option1: str = discord.SlashOption(description="First option", required=True),
                     option2: str = discord.SlashOption(description="Second option", required=True),
                     option3: str = discord.SlashOption(description="Third option", required=False),
                     option4: str = discord.SlashOption(description="Fourth option", required=False),
                     option5: str = discord.SlashOption(description="Fifth option", required=False)):
     """Create a poll with reactions"""
     ctx = await get_application_context(bot, interaction)
     
     # Gather all non-None options
     options = [opt for opt in [option1, option2, option3, option4, option5] if opt is not None]
     
     # Call the poll command with the gathered options
     await poll(ctx, title, *options)

@bot.slash_command(name="announce", description="Create and send a formatted announcement")
async def slash_announce(interaction: discord.Interaction,
                         channel: discord.TextChannel = discord.SlashOption(description="The channel to send the announcement to", required=True),
                         ping_role: discord.Role = discord.SlashOption(description="Role to ping (optional)", required=False),
                         content: str = discord.SlashOption(description="Initial announcement content", required=True)):
     """Create and send a formatted announcement"""
     ctx = await get_application_context(bot, interaction)
     await announce(ctx, channel, ping_role, content=content)

@bot.slash_command(name="repeat", description="Repeat a message in an embed (Staff only)")
async def slash_repeat(interaction: discord.Interaction,
                      title: str = discord.SlashOption(description="Embed title", required=False),
                      message: str = discord.SlashOption(description="Message content", required=True)):
     """Repeat a message in an embed"""
     ctx = await get_application_context(bot, interaction)
     await repeat(ctx, title, message=message)

@bot.slash_command(name="pingrole", description="Ping a specific role")
async def slash_pingrole(interaction: discord.Interaction):
     """Ping a specific role"""
     ctx = await get_application_context(bot, interaction)
     await pingrole(ctx)

# Voice channel commands
@bot.slash_command(name="join", description="Join your voice channel")
async def slash_join(interaction: discord.Interaction):
     """Join your voice channel"""
     ctx = await get_application_context(bot, interaction)
     await join(ctx)

@bot.slash_command(name="record", description="Record audio in a voice channel")
async def slash_record(interaction: discord.Interaction,
                      duration: int = discord.SlashOption(description="Recording duration in seconds", required=False, default=10)):
     """Record audio in a voice channel"""
     ctx = await get_application_context(bot, interaction)
     await record(ctx, duration)

@bot.slash_command(name="leave", description="Leave the voice channel")
async def slash_leave(interaction: discord.Interaction):
     """Leave the voice channel"""
     ctx = await get_application_context(bot, interaction)
     await leave(ctx)

# Automod commands
@bot.slash_command(name="automod", description="Configure automod features")
async def slash_automod(
     interaction: discord.Interaction,
     feature: str = discord.SlashOption(
          description="Automod feature to configure",
          required=True,
          choices=["links", "invites", "caps", "emojis", "words", "raid", "spamrate", "impersonation", "nsfw_text", "nsfw_image"]
     ),
     setting: str = discord.SlashOption(
          description="Setting to apply",
          required=True,
          choices=["on", "off", "5", "10", "15"]
     )
):
     """Configure automod features"""
     ctx = await get_application_context(bot, interaction)
     await automod(ctx, feature, setting)

@bot.slash_command(name="addblacklist", description="Add a word to the automod blacklist")
async def slash_addblacklist(interaction: discord.Interaction,
                            word: str = discord.SlashOption(description="Word to blacklist", required=True)):
     """Add a word to the automod blacklist"""
     ctx = await get_application_context(bot, interaction)
     await addblacklist(ctx, word=word)

@bot.slash_command(name="removeblacklist", description="Remove a word from the automod blacklist")
async def slash_removeblacklist(interaction: discord.Interaction,
                               word: str = discord.SlashOption(description="Word to remove from blacklist", required=True)):
     """Remove a word from the automod blacklist"""
     ctx = await get_application_context(bot, interaction)
     await removeblacklist(ctx, word=word)

@bot.slash_command(name="bulkaddwords", description="Add multiple words to the automod blacklist")
async def slash_bulkaddwords(interaction: discord.Interaction,
                            words: str = discord.SlashOption(description="Words to add, separated by commas", required=True)):
     """Add multiple words to the automod blacklist"""
     ctx = await get_application_context(bot, interaction)
     await bulkaddwords(ctx, words=words)

@bot.slash_command(name="automodwords", description="List all blacklisted words in automod (DM only)")
async def slash_automodwords(interaction: discord.Interaction):
     """List all blacklisted words in automod"""
     ctx = await get_application_context(bot, interaction)
     await automodwords(ctx)

# Admin/Management commands
@bot.slash_command(name="backupkeys", description="Backup all keys and data to GitHub (Owner only)")
async def slash_backupkeys(interaction: discord.Interaction):
     """Backup all keys and data to GitHub"""
     ctx = await get_application_context(bot, interaction)
     await backupkeys(ctx)

@bot.slash_command(name="shutdown", description="Shut down the bot (Owner only)")
async def slash_shutdown(interaction: discord.Interaction):
     """Shut down the bot and web server"""
     ctx = await get_application_context(bot, interaction)
     await shutdown(ctx)

@bot.slash_command(name="resync", description="Manually resync slash commands (Owner only)")
async def slash_resync(interaction: discord.Interaction):
     """Manually resync slash commands"""
     # Check if the user has admin permissions
     if str(interaction.user.id) == "1141849395902554202" or interaction.user.guild_permissions.administrator:
          await interaction.response.send_message("🔄 Resyncing slash commands... This may take a moment.")
          try:
               # For nextcord, use application_commands to sync directly
               await interaction.followup.send("Clearing existing commands from this server...")
               await bot.sync_application_commands(guild_id=interaction.guild.id)
               
               # Sync commands to the current guild for immediate effect
               await interaction.followup.send("Syncing commands to this server...")
               await bot.tree.sync(guild=discord.Object(id=interaction.guild.id))
               
               # Sync globally as well
               await interaction.followup.send("Syncing commands globally...")
               await bot.tree.sync()
               
               # Get command list for display
               commands = await bot.fetch_application_commands(guild_id=interaction.guild.id)
               
               # Success embed
               embed = discord.Embed(
                    title="✅ Slash Commands Resynced",
                    description=f"Successfully synced {len(commands)} slash commands to this server.",
                    color=discord.Color.green()
               )
               
               embed.add_field(
                    name="Note", 
                    value="Global commands may take up to an hour to appear in all servers. Commands in this server should be available immediately.",
                    inline=False
               )
               
               # List synced commands
               command_list = "\n".join([f"/{cmd.name}" for cmd in commands[:20]])
               if len(commands) > 20:
                    command_list += f"\n...and {len(commands) - 20} more"
                    
               if command_list:
                    embed.add_field(name="Synced Commands", value=command_list, inline=False)
               
               await interaction.followup.send(embed=embed)
          except Exception as e:
               await interaction.followup.send(f"❌ Error syncing commands: {e}")
               print(f"Command sync error: {e}")
     else:
          await interaction.response.send_message("❌ Only the bot owner or administrators can use this command.", ephemeral=True)


class AudioRecorder(discord.VoiceClient):
    def __init__(self, client, channel):
        super().__init__(client, channel)
        self.audio_data = []

    def recv_audio(self, data):
        pcm_data = np.frombuffer(data, dtype=np.int16)
        self.audio_data.append(pcm_data)

    async def record(self, duration=10):
        await asyncio.sleep(duration)
        self.stop_recording()

    def stop_recording(self):
        audio_array = np.concatenate(self.audio_data, axis=0)
        with wave.open("recorded_audio.wav", "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(audio_array.tobytes())

@bot.command()
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        vc = await channel.connect(cls=AudioRecorder)
        await ctx.send(f"Joined {channel.name} and ready to record!")
    else:
        await ctx.send("You need to be in a voice channel!")

@bot.command()
async def record(ctx, duration: int = 10):
    vc = ctx.guild.voice_client
    if isinstance(vc, AudioRecorder):
        await ctx.send(f"Recording for {duration} seconds...")
        await vc.record(duration)
        await ctx.send("Recording finished! Audio saved as `recorded_audio.wav`.")

@bot.command()
async def leave(ctx):
    vc = ctx.guild.voice_client
    if vc:
        await vc.disconnect()
        await ctx.send("Left the voice channel.")
@bot.command()
async def resync(ctx):
     """Manually resync slash commands (Owner only)"""
     # Check if the command author is the bot owner or has admin permissions
     if str(ctx.author.id) == "1141849395902554202" or ctx.author.guild_permissions.administrator:
          status_msg = await ctx.send("🔄 Resyncing slash commands... This may take a moment.")
          try:
               # First clear existing commands to ensure a clean slate
               await status_msg.edit(content="🔄 Clearing existing commands...")
               try:
                    await bot.http.bulk_upsert_guild_commands(bot.user.id, ctx.guild.id, [])
                    await status_msg.edit(content="✅ Successfully cleared existing commands!")
               except Exception as e:
                    await status_msg.edit(content=f"⚠️ Could not clear existing commands: {e}")
               
               # Get all commands defined in the bot
               await status_msg.edit(content="🔄 Collecting command definitions...")
               command_count = len(bot.application_commands)
               await status_msg.edit(content=f"Found {command_count} slash commands to sync")
               
               # Sync commands to the server
               await status_msg.edit(content="🔄 Syncing commands to this server...")
               try:
                    # Try direct HTTP API approach for more reliable syncing
                    for test_guild_id in TEST_GUILD_IDS:
                         if int(ctx.guild.id) == int(test_guild_id):
                              commands = await bot.sync_commands(guild_id=ctx.guild.id, force=True)
                              await status_msg.edit(content=f"✅ Synced {len(commands)} commands to this server!")
               except Exception as e:
                    await status_msg.edit(content=f"⚠️ Error during guild sync: {e}")
                    
               # Then sync globally as well
               await status_msg.edit(content="🔄 Syncing commands globally (this may take up to an hour to take effect)...")
               try:
                    global_cmds = await bot.sync_commands()
                    await status_msg.edit(content=f"✅ Global sync initiated with {len(global_cmds)} commands")
               except Exception as e:
                    await status_msg.edit(content=f"⚠️ Error during global sync: {e}")
               
               # Success embed
               embed = discord.Embed(
                    title="✅ Slash Commands Resynced",
                    description=f"Successfully synced slash commands to Discord.",
                    color=discord.Color.green()
               )
               
               embed.add_field(
                    name="Note", 
                    value="Global commands may take up to an hour to appear in all servers. Commands in this server should be available immediately.",
                    inline=False
               )
               
               # List all application commands
               all_commands = []
               for cmd in bot.application_commands:
                    all_commands.append(f"/{cmd.name}")
               
               if all_commands:
                    # List synced commands
                    command_list = "\n".join(all_commands[:20])
                    if len(all_commands) > 20:
                         command_list += f"\n...and {len(all_commands) - 20} more"
                    embed.add_field(name="Synced Commands", value=command_list, inline=False)
               
               await ctx.send(embed=embed)
          except Exception as e:
               await ctx.send(f"❌ Error syncing commands: {e}")
               print(f"Command sync error: {e}")
     else:
          await ctx.send("❌ Only the bot owner or administrators can use this command.")

@bot.command()
async def testkeyystem(ctx):
    """Test if the key system is working (Admin only)"""
    # Check if the command author is authorized
    if str(ctx.author.id) == "1141849395902554202" or ctx.author.guild_permissions.administrator:
        try:
            from key_system import test_key_system
            
            # Send status message
            status_msg = await ctx.send("🔄 Testing key system...")
            
            # Run the test
            test_result = test_key_system()
            
            # Create report embed
            embed = discord.Embed(
                title="🔑 Key System Test Results",
                description="Results of key system diagnostic test",
                color=discord.Color.blue()
            )
            
            if test_result.get("status") == "success":
                embed.add_field(name="Status", value="✅ Working", inline=False)
                embed.add_field(name="Test Key", value=f"`{test_result.get('test_key')}`", inline=True)
                embed.add_field(name="Key Count", value=str(test_result.get('key_count')), inline=True)
                embed.color = discord.Color.green()
            else:
                embed.add_field(name="Status", value="❌ Error", inline=False)
                embed.add_field(name="Error", value=test_result.get('error', 'Unknown error'), inline=False)
                embed.color = discord.Color.red()
            
            # Send results
            await status_msg.edit(content=None, embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error testing key system: {e}")
    else:
        await ctx.send("❌ Only admins can test the key system.")

# Key system slash commands
@bot.slash_command(name="generatekey", description="Generate a license key (Admin only)")
async def slash_generatekey(interaction: discord.Interaction,
                           key_type: str = discord.SlashOption(
                               description="Type of key to generate",
                               required=False,
                               default="standard",
                               choices=["standard", "premium", "vip", "one-time"]),
                           expires_days: int = discord.SlashOption(
                               description="Days until expiration (0=never)",
                               required=False,
                               default=0),
                           max_uses: int = discord.SlashOption(
                               description="Maximum number of uses",
                               required=False,
                               default=1)):
    """Generate a license key (Admin only)"""
    # Check if user is authorized
    if str(interaction.user.id) == "1141849395902554202" or interaction.user.guild_permissions.administrator:
        try:
            from key_system import generate_key, save_generated_key, initialize_key_files
            
            # Make sure key files are initialized
            initialize_key_files()
            
            # Send processing message
            await interaction.response.defer(ephemeral=True)
            
            # Generate a new key
            new_key = generate_key()
            
            # If expires_days is 0, set it to None (never expires)
            exp_days = None if expires_days == 0 else expires_days
            
            # Save the key with metadata
            success, result = save_generated_key(
                new_key, 
                key_type=key_type,
                expires_in_days=exp_days,
                max_uses=max_uses,
                created_by=str(interaction.user.id)
            )
            
            if success:
                # Create an embed with key information
                embed = discord.Embed(
                    title="🔑 License Key Generated",
                    description=f"A new license key has been generated.",
                    color=discord.Color.green()
                )
                
                embed.add_field(name="Key", value=f"`{new_key}`", inline=False)
                embed.add_field(name="Type", value=key_type, inline=True)
                embed.add_field(name="Max Uses", value=str(max_uses), inline=True)
                
                if exp_days:
                    embed.add_field(name="Expires", value=f"In {exp_days} days", inline=True)
                else:
                    embed.add_field(name="Expires", value="Never", inline=True)
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Error generating key: {result}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error in key system: {e}", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Only admins can generate license keys.", ephemeral=True)

@bot.slash_command(name="redeemkey", description="Redeem a license key")
async def slash_redeemkey(interaction: discord.Interaction,
                         key: str = discord.SlashOption(
                             description="License key to redeem",
                             required=True)):
    """Redeem a license key"""
    # Make sure this is in DMs to keep keys private
    if interaction.guild:
        await interaction.response.send_message("⚠️ For security, please redeem your key in a DM with me!", ephemeral=True)
        try:
            await interaction.user.send("Please use `/redeemkey` in our DM to redeem your key securely.")
        except:
            await interaction.followup.send("I couldn't send you a DM. Please enable DMs from server members and try again.", ephemeral=True)
        return
    
    try:
        from key_system import redeem_key, initialize_key_files
        
        # Make sure key files are initialized
        initialize_key_files()
        
        # Send processing message
        await interaction.response.defer(ephemeral=False)
        
        # Try to redeem the key
        success, result = redeem_key(key, str(interaction.user.id), interaction.user.name)
        
        if success:
            # Create success embed
            embed = discord.Embed(
                title="✅ Key Redeemed Successfully",
                description="Your license key has been redeemed!",
                color=discord.Color.green()
            )
            
            embed.add_field(name="Key Type", value=result.get('type', 'Standard'), inline=True)
            embed.add_field(name="Redeemed At", value=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            
            await interaction.followup.send(embed=embed)
            
            # Try to notify the key creator
            try:
                creator_id = result.get('created_by')
                if creator_id:
                    creator = await bot.fetch_user(int(creator_id))
                    if creator:
                        notify_embed = discord.Embed(
                            title="🔑 License Key Redeemed",
                            description=f"One of your license keys has been redeemed.",
                            color=discord.Color.blue()
                        )
                        notify_embed.add_field(name="Key", value=f"`{key}`", inline=False)
                        notify_embed.add_field(name="Redeemed By", value=f"{interaction.user.name} ({interaction.user.id})", inline=True)
                        notify_embed.set_footer(text=f"Key type: {result.get('type', 'Standard')}")
                        
                        await creator.send(embed=notify_embed)
                
                # Log to modlogs
                try:
                    modlogs_channel = await bot.fetch_channel(MODLOGS_CHANNEL_ID)
                    if modlogs_channel:
                        log_embed = discord.Embed(
                            title="🔑 License Key Redeemed",
                            description=f"A license key has been redeemed.",
                            color=discord.Color.blue(),
                            timestamp=datetime.datetime.now()
                        )
                        log_embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user.id})", inline=True)
                        log_embed.add_field(name="Key Type", value=result.get('type', 'Standard'), inline=True)
                        
                        await modlogs_channel.send(embed=log_embed)
                except Exception as e:
                    print(f"Error logging key redemption: {e}")
            except Exception as e:
                print(f"Error notifying key creator: {e}")
        else:
            # Create failure embed
            embed = discord.Embed(
                title="❌ Key Redemption Failed",
                description=result,
                color=discord.Color.red()
            )
            
            await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Error in key system: {e}")

@bot.slash_command(name="mykeys", description="View all keys you've redeemed")
async def slash_mykeys(interaction: discord.Interaction):
    """View all keys you've redeemed"""
    from key_system import get_keys_for_user
    
    # Send processing message
    await interaction.response.defer(ephemeral=True)
    
    # Get all keys redeemed by this user
    user_keys = get_keys_for_user(str(interaction.user.id))
    
    if not user_keys:
        await interaction.followup.send("You haven't redeemed any license keys yet.", ephemeral=True)
        return
    
    # Create an embed showing the keys
    embed = discord.Embed(
        title="🔑 Your License Keys",
        description=f"You have redeemed {len(user_keys)} license keys:",
        color=discord.Color.blue()
    )
    
    for key_entry in user_keys[:10]:  # Limit to 10 keys to avoid embed size limit
        embed.add_field(
            name=f"{key_entry.get('key_type', 'Standard')} License",
            value=(
                f"Key: `{key_entry.get('key', 'Unknown')}`\n"
                f"Redeemed: {datetime.datetime.fromisoformat(key_entry.get('redeemed_at')).strftime('%Y-%m-%d')}"
            ),
            inline=False
        )
    
    if len(user_keys) > 10:
        embed.set_footer(text=f"Showing 10 of {len(user_keys)} keys")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.slash_command(name="listkeys", description="List all generated keys (Admin only)")
async def slash_listkeys(interaction: discord.Interaction):
    """List all generated keys (Admin only)"""
    # Check if the user is authorized
    if str(interaction.user.id) == "1141849395902554202" or interaction.user.guild_permissions.administrator:
        from key_system import get_all_generated_keys
        
        # Send processing message
        await interaction.response.defer(ephemeral=True)
        
        keys = get_all_generated_keys()
        
        if not keys:
            await interaction.followup.send("No license keys have been generated yet.", ephemeral=True)
            return
        
        # Create a summary embed
        embed = discord.Embed(
            title="🔑 Generated License Keys",
            description=f"Total keys: {len(keys)}",
            color=discord.Color.blue()
        )
        
        # Count by type
        key_types = {}
        for key in keys:
            key_type = key.get('type', 'standard')
            if key_type in key_types:
                key_types[key_type] += 1
            else:
                key_types[key_type] = 1
        
        # Add type counts to embed
        for key_type, count in key_types.items():
            embed.add_field(name=f"{key_type.title()} Keys", value=str(count), inline=True)
        
        # Send summary
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        # Send detailed list to DM for security
        try:
            for i in range(0, len(keys), 10):
                batch = keys[i:i+10]
                
                detail_embed = discord.Embed(
                    title=f"🔑 License Keys (Batch {i//10+1})",
                    color=discord.Color.blue()
                )
                
                for key_entry in batch:
                    uses_info = f"{key_entry.get('uses_remaining', 0)}/{key_entry.get('max_uses', 1)}"
                    redemptions = len(key_entry.get('redeemed_by', []))
                    
                    # Format expiry date
                    expiry = "Never"
                    if key_entry.get('expires_at'):
                        expiry_date = datetime.datetime.fromisoformat(key_entry['expires_at'])
                        expiry = expiry_date.strftime('%Y-%m-%d')
                    
                    detail_embed.add_field(
                        name=key_entry.get('key', 'Unknown'),
                        value=(
                            f"Type: {key_entry.get('type', 'standard')}\n"
                            f"Uses: {uses_info}\n"
                            f"Redemptions: {redemptions}\n"
                            f"Expires: {expiry}"
                        ),
                        inline=True
                    )
                
                await interaction.user.send(embed=detail_embed)
            
            await interaction.followup.send("📬 Detailed key list has been sent to your DMs.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error sending keys via DM: {e}", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Only admins can view all license keys.", ephemeral=True)

@bot.slash_command(name="revokekey", description="Revoke a license key (Admin only)")
async def slash_revokekey(interaction: discord.Interaction,
                          key: str = discord.SlashOption(
                              description="License key to revoke",
                              required=True)):
    """Revoke a license key (Admin only)"""
    # Check if the user is authorized
    if str(interaction.user.id) == "1141849395902554202" or interaction.user.guild_permissions.administrator:
        from key_system import get_all_generated_keys
        
        # Send processing message
        await interaction.response.defer(ephemeral=True)
        
        # Load generated keys
        keys = get_all_generated_keys()
        key_found = False
        
        for i, key_entry in enumerate(keys):
            if key_entry.get('key') == key:
                # Set uses remaining to 0 to effectively revoke the key
                keys[i]['uses_remaining'] = 0
                key_found = True
                break
        
        if not key_found:
            await interaction.followup.send("❌ Key not found.", ephemeral=True)
            return
        
        # Save updated keys
        with open("generated_keys.json", 'w') as f:
            json.dump(keys, f, indent=2)
        
        await interaction.followup.send(f"✅ Key `{key}` has been revoked and can no longer be used.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Only admins can revoke license keys.", ephemeral=True)

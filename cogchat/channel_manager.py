import json
import os

async def register_channel(cog, ctx):
    guild_id = str(ctx.guild.id)
    channel_id = str(ctx.channel.id)

    if not os.path.exists(cog.config_dir):
        os.makedirs(cog.config_dir)

    guild_dir = os.path.join(cog.config_dir, guild_id)
    if not os.path.exists(guild_dir):
        os.makedirs(guild_dir)

    channel_config_path = os.path.join(guild_dir, f"{channel_id}.json")
    if not os.path.exists(channel_config_path):
        channel_config = {
            "character": "Assistant",
            "temperature": None,
            "max_tokens": None,
            "chat_history": []
        }
        with open(channel_config_path, 'w') as config_file:
            json.dump(channel_config, config_file, indent=4)
        await ctx.send(f"Channel {ctx.channel.name} in guild {ctx.guild.name} registered with default settings.")
    else:
        await ctx.send(f"Channel {ctx.channel.name} in guild {ctx.guild.name} is already registered.")
        
async def start_listening(cog, ctx):
    cog.listening_channels.add(ctx.channel.id)
    await ctx.send(f"Listening to channel {ctx.channel.name}.")
    
async def stop_listening(cog, ctx):
    if ctx.channel.id in cog.listening_channels:
        cog.listening_channels.remove(ctx.channel.id)
        await ctx.send(f"Stopped listening to channel {ctx.channel.name}.")
    else:
        await ctx.send(f"Channel {ctx.channel.name} is not being listened to.")
        
async def remove_channel(cog, ctx):
    guild_id = str(ctx.guild.id)
    channel_id = str(ctx.channel.id)
    if ctx.channel.id in cog.listening_channels:
        await ctx.send(f"Unable to remove listening channel. Stop the channel with `[p]cogchat stop`")
    else:
        if os.path.exists(os.path.join(cog.config_dir, guild_id, f"{channel_id}.json")):
            os.remove(os.path.join(cog.config_dir, guild_id, f"{channel_id}.json"))
        await ctx.send(f"Channel config removed")

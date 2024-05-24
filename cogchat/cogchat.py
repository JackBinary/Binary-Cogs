import os
import json
import textwrap
import re
import sseclient  # pip install sseclient-py
import requests

from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config

from .config_manager import update_channel_config
from .character_manager import create_character, delete_character, show_persona, update_persona
from .message_handler import handle_message
from .channel_manager import register_channel, start_listening, stop_listening, remove_channel

class CogChat(commands.Cog):
    """
    Chat with an LLM in Discord!
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=133041100356059137,
            force_registration=True,
        )
        self.llm_server_url = "http://127.0.0.1:5000/v1/chat/completions"
        self.config_dir = "config"
        self.listening_channels = set()  # set to track which channels are being listened to
        self.persona_creation_state = {} # Temporary state to track persona creation
        
        
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.command(name="cogchat")
    async def cogchat(self, ctx, *, text: str):
        """Base command for CogChat."""
        command_array = text.split(" ")

        try:
            match command_array[0]:
                case "register":
                    await register_channel(self, ctx)
                case "remove":
                    await remove_channel(self, ctx)
                case "start":
                    await start_listening(self, ctx)
                case "stop":
                    await stop_listening(self, ctx)
                case "configure":
                    channel_id = str(ctx.channel.id)
                    guild_id = str(ctx.guild.id)
                    try:
                        match command_array[1]:
                            case "character":
                                await update_channel_config(channel_id, guild_id, "character", command_array[2], self.config_dir)
                                await ctx.send(f"Character updated to {command_array[2]}.")
                            case "temperature":
                                await update_channel_config(channel_id, guild_id, "temperature", float(command_array[2]), self.config_dir)
                                await ctx.send(f"Temperature updated to {command_array[2]}.")
                            case "max_tokens":
                                await update_channel_config(channel_id, guild_id, "max_tokens", int(command_array[2]), self.config_dir)
                                await ctx.send(f"Max Tokens updated to {command_array[2]}.")
                    except IndexError: # too few arguments
                        await ctx.send("Usage: `[p]cogchat configure [character|temperature|max_tokens] <value>`")
                case "character":
                    try:
                        match command_array[1]:
                            case "create":
                                await create_character(command_array[2], self.config_dir)
                                await ctx.send(f"{command_array[2]} Created! Add a persona with `[p]cogchat character persona <character> new`")
                            case "delete":
                                await delete_character(command_array[2], self.config_dir)
                                await ctx.send(f"Character {command_array[2]} deleted.")
                            case "persona":
                                try:
                                    match command_array[3]:
                                        case "show":
                                            persona = await show_persona(command_array[2], self.config_dir)
                                            await ctx.send(f"Persona for {command_array[2]}: {persona}")
                                        case "new":
                                            self.persona_creation_state[ctx.author.id] = command_array[2]
                                            await ctx.send(f"Please describe {command_array[2]}.")
                                except IndexError: # too few arguments
                                    await ctx.send("Usage: `[p]cogchat character persona <character> [new|show]`")
                    except IndexError: # too few arguments
                        await ctx.send("Usage: `[p]cogchat character [create|delete|persona] <character>`")
        except IndexError: # too few arguments
            await ctx.send("Usage: `[p]cogchat [register|remove|start|stop|configure|character]`")


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.content.startswith(await self.bot.get_valid_prefixes(message.guild)):
            return
        if message.author.id in self.persona_creation_state:
            character_name = self.persona_creation_state.pop(message.author.id)
            await update_persona(character_name, message.content, self.config_dir)
            await message.channel.send(f"Persona for {character_name} updated.")
            
        await handle_message(self, message)

def setup(bot: Red):
    bot.add_cog(CogChat(bot))

import os
import json
import requests
import sseclient  # pip install sseclient-py

from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config

RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]


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
        self.listening_channels = {}  # Dictionary to track which channels are being listened to
    
    
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.command(name="cogchat")
    async def cogchat(self, ctx, *, text: str):
        """Base command for CogChat."""
        
        guild_id = str(ctx.guild.id)
        channel_id = str(ctx.channel.id)
        
        command_array = text.split(" ")
        
        match command_array[0]:
            case "register":
                if not os.path.exists(self.config_dir):
                    os.makedirs(self.config_dir)
                    
                guild_dir = os.path.join(self.config_dir, guild_id)
                if not os.path.exists(guild_dir):
                    os.makedirs(guild_dir)
                    
                channel_config_path = os.path.join(guild_dir, f"{channel_id}.json")
                if not os.path.exists(channel_config_path):
                    channel_config = {
                        "character": "Assistant",
                        "temperature": None,
                        "top_p": None,
                        "max_tokens": None,
                        "seed": None,
                        "chat_history": []
                    }
                    with open(channel_config_path, 'w') as config_file:
                        json.dump(channel_config, config_file, indent=4)
                    await ctx.send(f"Channel {ctx.channel.name} in guild {ctx.guild.name} registered with default settings.")
                else:
                    await ctx.send(f"Channel {ctx.channel.name} in guild {ctx.guild.name} is already registered.")

            case "start":
                self.listening_channels[ctx.channel.id] = True
            case "stop":
                if ctx.channel.id in self.listening_channels:
                    self.listening_channels.pop(ctx.channel.id)
            case "configure":
                try:
                    match command_array[1]:
                        case "character":
                            pass
                        case "temperature":
                            pass
                        case "top_p":
                            pass
                        case "max_tokens":
                            pass
                        case "seed":
                            pass
                except IndexError: # too few arguments
                    await ctx.send("Usage ...") # fill in usage information
            case "character":
                try:
                    match command_array[1]:
                        case "create":
                            pass
                        case "delete":
                            pass
                        case "persona":
                            match command_array[2]:
                                case "show":
                                    pass
                                case "new":
                                    pass
                            
                except IndexError: # too few arguments
                    await ctx.send("Usage ...") # fill in usage information
            
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if message.channel.id in self.listening_channels:
            guild_id = str(message.guild.id)
            channel_id = str(message.channel.id)
            channel_config_path = os.path.join(self.config_dir, guild_id, f"{channel_id}.json")
            if not os.path.exists(channel_config_path):
                await message.channel.send("Configuration for this channel is missing.")
                return
            
            with open(channel_config_path, 'r') as config_file:
                channel_config = json.load(config_file)
            
            channel_config['chat_history'].append(
                {
                    "role": "user",
                    "content": f"{message.author.nick if message.author.nick else message.author.name}: {message.content}"
                }
            )
            data = {
                "mode": "chat",
                "character": channel_config["character"],
                "messages": channel_config["chat_history"]
            }
            
            # Send the request to the LLM server
            stream_response = requests.post(
                self.llm_server_url,
                headers={"Content-Type": "application/json"},
                json=data,
                verify=False,
                stream=True
            )
            client = sseclient.SSEClient(stream_response)
            assistant_message = ''
            message_store = []
            for event in client.events():
                payload = json.loads(event.data)
                chunk = payload['choices'][0]['message']['content']
                assistant_message += chunk

                while "\n" in assistant_message:
                    line, assistant_message = assistant_message.split("\n", 1)
                    line = line.strip()
                    if line:
                        await message.channel.send(line)
                        message_store.append(line)
            
            # Send any remaining text that didn't end with a newline
            if assistant_message.strip():
                await message.channel.send(assistant_message.strip())
                message_store.append(assistant_message.strip())
            
            channel_config['chat_history'].append(
                {
                    "role": "assistant",
                    "content": "\n".join(message_store)
                }
            )
            with open(channel_config_path, 'w') as config_file:
                json.dump(channel_config, config_file, indent=4)
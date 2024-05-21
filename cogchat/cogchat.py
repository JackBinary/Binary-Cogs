import os
import re
import json
import requests
import sseclient  # pip install sseclient-py
import textwrap

from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config


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
        self.llm_server_url = "http://127.0.0.1:5000/v1/completions"
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

        prefixes = await self.bot.get_valid_prefixes(message.guild)
        if any(message.content.startswith(prefix) for prefix in prefixes):
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
            
            channel_config['chat_history'].append(f"{message.author.nick if message.author.nick else message.author.name}: {message.content}")
            with open(os.path.join(self.config_dir, "characters", f"{channel_config['character']}.json"), 'r') as config_file:
                character = json.load(config_file)


            rendered_history = "\n".join(channel_config['chat_history'])

            prompt = textwrap.dedent(f"""
                You are in a chat room with multiple participants.
                Below is a transcript of recent messages in the conversation.
                Write the next one to three messages that you would send in this
                conversation, from the point of view of the participant named
                {character['Name']}.

                {character['Persona']}

                All responses you write must be from the point of view of
                {character['Name']}.

                ### Transcript:
                {rendered_history}
                {character['Name']}:
            """)


            data = {
                "prompt": prompt,
                "stream": True,
                "max_tokens": channel_config["max_tokens"] if channel_config["max_tokens"] is not None else 200,
                "stop":[
                    ":"
                ]
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
            # Regex pattern to match sentence-ending punctuation or newline
            pattern = r'([.!?])|\n'

            for event in client.events():
                payload = json.loads(event.data)
                print(payload)
                chunk = payload['choices'][0]['text']
                assistant_message += chunk

                # Split the message using the regex pattern
                parts = re.split(pattern, assistant_message)

                # Process each part
                i = 0
                while i < len(parts) - 1:
                    part = parts[i]
                    if part and part.strip():
                        part = part.strip()
                        # Check if the next part is a punctuation mark
                        if i + 1 < len(parts) and parts[i + 1] in ['.', '!', '?']:
                            part += parts[i + 1]  # Append the punctuation mark
                            i += 1  # Skip the punctuation mark in the next iteration
                        await message.channel.send(part)
                        message_store.append(part)
                    i += 1

                # Keep the last part (which may be an incomplete message) in assistant_message
                assistant_message = parts[-1]

            # Send any remaining text that didn't end with a punctuation or newline
            if assistant_message.strip():
                await message.channel.send(assistant_message.strip())
                message_store.append(assistant_message.strip())

            assistant_message = "\n".join(message_store)
            
            channel_config['chat_history'].append(f"{channel_config['character']}: {assistant_message}")
            with open(channel_config_path, 'w') as config_file:
                json.dump(channel_config, config_file, indent=4)

from typing import Literal

import discord
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
        
    @commands.guild_only()
    @commands.command(name="cogchat")
    async def cogchat(self, ctx, *, text: str):
        """Base command for CogChat."""
        command_array = text.split(" ")
        
        match command_array[0]:
            case "register":
                # create an entry in storage for the current guild (if not already existing) and channel.
                pass
            case "start":
                # begin listening for new messages to pass to LLM
                pass
            case "stop":
                # stop listening for new messages to pass to LLM
                pass
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
                except Exception: # too few arguments
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
                            
                except Exception: # too few arguments
                    await ctx.send("Usage ...") # fill in usage information
            
        

        

import discord
import os
from redbot.core import commands
from redbot.core.utils.chat_formatting import pagify
import asyncio
from typing import Optional

LIBRARY_DIR = os.path.join("data", "jukebox_library")

class Jukebox(commands.Cog):
    """A local jukebox for uploading and playing MP3s."""

    def __init__(self, bot):
        self.bot = bot
        os.makedirs(LIBRARY_DIR, exist_ok=True)
        self.current_vc = {}

    @commands.group()
    async def jukebox(self, ctx: commands.Context):
        """Base command for the Jukebox system."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @jukebox.command(name="add")
    async def add(self, ctx: commands.Context, name: str):
        """Upload an MP3 file to the jukebox with a given name."""
        if not ctx.message.attachments:
            await ctx.send("Attach an MP3 file to this message.")
            return

        attachment = ctx.message.attachments[0]
        if not attachment.filename.lower().endswith(".mp3"):
            await ctx.send("Only MP3 files are supported.")
            return

        dest_path = os.path.join(LIBRARY_DIR, f"{name}.mp3")
        await attachment.save(dest_path)
        await ctx.send(f"Added `{name}` to the jukebox.")

    @jukebox.command(name="play")
    async def play(self, ctx: commands.Context, name: Optional[str]):
        """Play a song by name, or list all songs if no name is given."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Join a voice channel first.")
            return

        vc = ctx.author.voice.channel

        if name:
            song_path = os.path.join(LIBRARY_DIR, f"{name}.mp3")
            if not os.path.isfile(song_path):
                await ctx.send("Song not found.")
                return

            voice = ctx.voice_client or await vc.connect()
            if voice.is_playing():
                voice.stop()

            voice.play(discord.FFmpegPCMAudio(song_path), after=lambda e: print(f"Done: {e}"))
            await ctx.send(f"Now playing `{name}`.")
            self.current_vc[ctx.guild.id] = voice
        else:
            songs = [f[:-4] for f in os.listdir(LIBRARY_DIR) if f.endswith(".mp3")]
            if not songs:
                await ctx.send("The jukebox is empty.")
                return

            pages = list(pagify("\n".join(f"`{song}`" for song in songs), delims=["\n"], page_length=10))
            current = 0
            message = await ctx.send(f"**Songs in Jukebox**\n{pages[current]}")

            await message.add_reaction("⬅️")
            await message.add_reaction("➡️")

            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) in ["⬅️", "➡️"] and reaction.message.id == message.id

            while True:
                try:
                    reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
                    await message.remove_reaction(reaction, user)

                    if str(reaction.emoji) == "⬅️" and current > 0:
                        current -= 1
                    elif str(reaction.emoji) == "➡️" and current < len(pages) - 1:
                        current += 1

                    await message.edit(content=f"**Songs in Jukebox**\n{pages[current]}")
                except asyncio.TimeoutError:
                    break

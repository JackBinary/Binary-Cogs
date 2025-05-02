import discord
import asyncio
import re
from pathlib import Path
from typing import Optional

from redbot.core import commands

def sanitize_filename(name: str) -> str:
    """Replace illegal characters in filenames with underscores."""
    return re.sub(r'[\\/*?:"<>|]', '_', name)

def chunk_list(data, size):
    """Yield successive chunks from a list."""
    for i in range(0, len(data), size):
        yield data[i:i + size]

class Jukebox(commands.Cog):
    """A local jukebox for uploading and playing MP3s."""

    def __init__(self, bot):
        self.bot = bot
        self.data_path = Path(__file__).parent / "data"
        self.library_path = self.data_path / "jukebox_library"
        self.library_path.mkdir(parents=True, exist_ok=True)
        self.current_vc = {}

    @commands.group(invoke_without_command=True)
    async def jukebox(self, ctx: commands.Context):
        """Base command for the Jukebox system."""
        await ctx.send_help()

    @jukebox.command(name="add")
    async def add(self, ctx: commands.Context, *, name: str):
        """Upload an MP3 file to the jukebox with a given name."""
        if not ctx.message.attachments:
            await ctx.send("Attach an MP3 file to this message.")
            return

        attachment = ctx.message.attachments[0]
        if not attachment.filename.lower().endswith(".mp3"):
            await ctx.send("Only MP3 files are supported.")
            return

        safe_name = sanitize_filename(name.strip())
        dest_path = self.library_path / f"{safe_name}.mp3"

        await attachment.save(dest_path)
        await ctx.send(f"Added `{safe_name}` to the jukebox.")

    @jukebox.command(name="play")
    async def play(self, ctx: commands.Context, name: Optional[str]):
        """Play a song by name, or list all songs if no name is given."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Join a voice channel first.")
            return

        voice_channel = ctx.author.voice.channel

        if name:
            safe_name = sanitize_filename(name.strip())
            song_path = self.library_path / f"{safe_name}.mp3"
            if not song_path.is_file():
                await ctx.send("Song not found.")
                return

            voice = ctx.voice_client or await voice_channel.connect()
            if voice.is_playing():
                voice.stop()

            voice.play(discord.FFmpegPCMAudio(str(song_path)), after=lambda e: print(f"Done: {e}"))
            await ctx.send(f"Now playing `{safe_name}`.")
            self.current_vc[ctx.guild.id] = voice

        else:
            songs = sorted(f.stem for f in self.library_path.glob("*.mp3"))
            if not songs:
                await ctx.send("The jukebox is empty.")
                return

            pages = list(chunk_list(songs, 10))
            current = 0

            def format_page(index):
                lines = "\n".join(f"`{title}`" for title in pages[index])
                return f"**Songs in Jukebox** (Page {index + 1}/{len(pages)})\n{lines}"

            message = await ctx.send(format_page(current))
            await message.add_reaction("⬅️")
            await message.add_reaction("➡️")

            def check(reaction, user):
                return (
                    user == ctx.author
                    and str(reaction.emoji) in ["⬅️", "➡️"]
                    and reaction.message.id == message.id
                )

            while True:
                try:
                    reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
                    try:
                        await message.remove_reaction(reaction, user)
                    except discord.Forbidden:
                        pass  # Ignore if bot can't remove reaction

                    if str(reaction.emoji) == "⬅️" and current > 0:
                        current -= 1
                    elif str(reaction.emoji) == "➡️" and current < len(pages) - 1:
                        current += 1

                    await message.edit(content=format_page(current))
                except asyncio.TimeoutError:
                    break

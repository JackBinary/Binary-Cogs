import discord
import asyncio
import re
from pathlib import Path
from typing import Optional

from redbot.core import commands, Config

DEFAULT_VOLUME = 1.0

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

        self.config = Config.get_conf(self, identifier=0xF00DCAFE, force_registration=True)
        self.config.register_guild(volume=DEFAULT_VOLUME)

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
    async def play(self, ctx: commands.Context, *, name: Optional[str] = None):
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

            volume = await self.config.guild(ctx.guild).volume()
            ffmpeg_options = f'-filter:a "volume={volume}"'

            voice.play(
                discord.FFmpegPCMAudio(str(song_path), options=ffmpeg_options),
                after=lambda e: print(f"Done: {e}")
            )
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
                        pass

                    if str(reaction.emoji) == "⬅️" and current > 0:
                        current -= 1
                    elif str(reaction.emoji) == "➡️" and current < len(pages) - 1:
                        current += 1

                    await message.edit(content=format_page(current))
                except asyncio.TimeoutError:
                    break

    @jukebox.command(name="remove")
    async def remove(self, ctx: commands.Context, *, name: str):
        """Remove a song from the jukebox."""
        safe_name = sanitize_filename(name.strip())
        song_path = self.library_path / f"{safe_name}.mp3"

        if not song_path.is_file():
            await ctx.send(f"Song `{safe_name}` not found in the jukebox.")
            return

        try:
            song_path.unlink()
            await ctx.send(f"Removed `{safe_name}` from the jukebox.")
        except Exception as e:
            await ctx.send(f"Failed to remove `{safe_name}`: {e}")

    @jukebox.command(name="volume")
    async def volume(self, ctx: commands.Context, value: Optional[float] = None):
        """Get or set the volume (0.0 to 2.0)."""
        if value is None:
            vol = await self.config.guild(ctx.guild).volume()
            await ctx.send(f"🔊 Current volume: `{vol:.2f}`")
            return

        if not (0.0 <= value <= 2.0):
            await ctx.send("Please choose a volume between 0.0 and 2.0.")
            return

        await self.config.guild(ctx.guild).volume.set(value)
        await ctx.send(f"✅ Volume set to `{value:.2f}`")

    @jukebox.command(name="stop")
    async def stop(self, ctx: commands.Context):
        """Stop the current track (but stay in voice)."""
        voice = ctx.voice_client
        if voice is None or not voice.is_connected():
            await ctx.send("I'm not in a voice channel.")
            return

        if voice.is_playing():
            voice.stop()
            await ctx.send("⏹️ Stopped playback.")
        else:
            await ctx.send("I'm not playing anything right now.")

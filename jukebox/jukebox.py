import discord
import asyncio
import re
from pathlib import Path
from typing import Optional

from redbot.core import commands, Config

DEFAULT_VOLUME = 1.0

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', name)

def chunk_list(data, size):
    for i in range(0, len(data), size):
        yield data[i:i + size]

class Jukebox(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_path = Path(__file__).parent / "data"
        self.library_path = self.data_path / "jukebox_library"
        self.library_path.mkdir(parents=True, exist_ok=True)

        self.config = Config.get_conf(self, identifier=0xF00DCAFE, force_registration=True)
        self.config.register_guild(volume=DEFAULT_VOLUME)

        self.queue = {}       # guild_id: asyncio.Queue[str]
        self.players = {}     # guild_id: asyncio.Task

    @commands.group(invoke_without_command=True)
    async def jukebox(self, ctx: commands.Context):
        await ctx.send_help()

    @jukebox.command(name="add")
    async def add(self, ctx: commands.Context, *, name: str):
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
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Join a voice channel first.")
            return

        if name is None:
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
            return

        safe_name = sanitize_filename(name.strip())
        song_path = self.library_path / f"{safe_name}.mp3"
        if not song_path.is_file():
            await ctx.send("Song not found.")
            return

        guild_id = ctx.guild.id
        if guild_id not in self.queue:
            self.queue[guild_id] = asyncio.Queue()

        await self.queue[guild_id].put(str(song_path))
        await ctx.send(f"🎶 Queued `{safe_name}`")

        if guild_id not in self.players:
            self.players[guild_id] = self.bot.loop.create_task(self._playback_loop(ctx))

    async def _playback_loop(self, ctx: commands.Context):
        guild = ctx.guild
        guild_id = guild.id
        channel = ctx.author.voice.channel
    
        voice = ctx.voice_client or await channel.connect()
    
        while True:
            try:
                # Disconnect if the voice channel is empty (only the bot left)
                if len(voice.channel.members) <= 1:
                    await ctx.send("Voice channel is empty. Disconnecting.")
                    await voice.disconnect()
                    break
    
                song_path = await self.queue[guild_id].get()
                if song_path is None:
                    continue  # Just skip if a null token was inserted (stop doesn't kill the loop)
    
                volume = await self.config.guild(guild).volume()
                source = discord.FFmpegPCMAudio(song_path)
                transformed = discord.PCMVolumeTransformer(source, volume=volume)
    
                playback_done = asyncio.Event()
    
                def after_playing(error):
                    if error:
                        print(f"Playback error: {error}")
                    self.bot.loop.call_soon_threadsafe(playback_done.set)
    
                voice.play(transformed, after=after_playing)
                await ctx.send(f"🎵 Now playing: `{Path(song_path).stem}`")
    
                await playback_done.wait()
    
            except Exception as e:
                await ctx.send(f"⚠️ Playback error: {e}")
                continue

    @jukebox.command(name="volume")
    async def volume(self, ctx: commands.Context, value: Optional[float] = None):
        if value is None:
            vol = await self.config.guild(ctx.guild).volume()
            await ctx.send(f"🔊 Current volume: `{vol:.2f}`")
            return

        if not (0.0 <= value <= 2.0):
            await ctx.send("Please choose a volume between 0.0 and 2.0.")
            return

        await self.config.guild(ctx.guild).volume.set(value)
        vc = ctx.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = value

        await ctx.send(f"✅ Volume set to `{value:.2f}`")

    @jukebox.command(name="remove")
    async def remove(self, ctx: commands.Context, *, name: str):
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

    @jukebox.command(name="stop")
    async def stop(self, ctx: commands.Context):
        voice = ctx.voice_client
        guild_id = ctx.guild.id
    
        if voice is None or not voice.is_connected():
            await ctx.send("I'm not in a voice channel.")
            return
    
        if voice.is_playing():
            voice.stop()
    
        if guild_id in self.queue:
            while not self.queue[guild_id].empty():
                try:
                    self.queue[guild_id].get_nowait()
                    self.queue[guild_id].task_done()
                except asyncio.QueueEmpty:
                    break
            await ctx.send("⏹️ Stopped playback and cleared the queue.")

    @jukebox.command(name="skip")
    async def skip(self, ctx: commands.Context):
        """Skip the currently playing track."""
        voice = ctx.voice_client
    
        if voice is None or not voice.is_connected():
            await ctx.send("I'm not in a voice channel.")
            return
    
        if not voice.is_playing():
            await ctx.send("No track is currently playing.")
            return
    
        voice.stop()
        await ctx.send("⏭️ Skipped the current track.")

    @jukebox.command(name="queue")
    async def queue(self, ctx: commands.Context):
        """Display the current jukebox queue."""
        guild_id = ctx.guild.id
    
        if guild_id not in self.queue or self.queue[guild_id].empty():
            await ctx.send("📭 The queue is currently empty.")
            return
    
        # Extract queued items non-destructively
        queue_list = list(self.queue[guild_id]._queue)
        pages = list(chunk_list(queue_list, 10))
        current = 0
    
        def format_page(index):
            entries = pages[index]
            lines = "\n".join(f"`{Path(track).stem}`" for track in entries)
            return f"🎶 **Queued Songs** (Page {index + 1}/{len(pages)})\n{lines}"
    
        message = await ctx.send(format_page(current))
        if len(pages) > 1:
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

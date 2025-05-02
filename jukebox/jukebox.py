import discord
import asyncio
import json
import os
import random
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

from redbot.core import commands, Config
# import edge_tts
from gtts import gTTS

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
        self.config.register_guild(tts_voice="en-US-AriaNeural")
        self.config.register_guild(volume=DEFAULT_VOLUME)

        self.queue = {}       # guild_id: asyncio.Queue[str]
        self.players = {}     # guild_id: asyncio.Task
        self.current_track = {}  # guild_id: str
        self.playlist_path = self.data_path / "playlists"
        self.playlist_path.mkdir(parents=True, exist_ok=True)


    @commands.group(invoke_without_command=True)
    async def jukebox(self, ctx: commands.Context):
        await ctx.send_help()

    @jukebox.command(name="add")
    async def add(self, ctx: commands.Context, *, name: str):
        """Upload an MP3 file to the bot to add to the library."""
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
        """Add a track from the library to the current queue."""
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
        self.queue.setdefault(guild_id, []).append(str(song_path))
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
                # Disconnect if bot is alone
                if len(voice.channel.members) <= 1:
                    await ctx.send("Voice channel is empty. Disconnecting.")
                    await voice.disconnect()
                    break
    
                # Nothing to play? Wait.
                if not self.queue.get(guild_id):
                    await asyncio.sleep(1)
                    continue
    
                # Extra safeguard
                if not self.queue[guild_id]:
                    continue
    
                entry = self.queue[guild_id].pop(0)
    
                # Handle dict entries for TTS, resume, volume, etc.
                is_tts = isinstance(entry, dict) and entry.get("tts", False)
                volume_override = entry.get("volume") if isinstance(entry, dict) else None
    
                if isinstance(entry, dict) and "path" in entry:
                    song_path = entry["path"]
                    seek_time = entry.get("seek", 0)
    
                    ffmpeg_opts = {}
                    if seek_time:
                        ffmpeg_opts["before_options"] = f"-ss {seek_time}"
                    ffmpeg_opts["options"] = "-vn"
    
                    source = discord.FFmpegPCMAudio(song_path, **ffmpeg_opts)
                else:
                    song_path = entry
                    source = discord.FFmpegPCMAudio(song_path)
    
                self.current_track[guild_id] = song_path
    
                # Volume override (e.g. full volume for TTS) or guild volume
                volume = volume_override or await self.config.guild(guild).volume()
                transformed = discord.PCMVolumeTransformer(source, volume=volume)
                transformed._start_time = time.time()
    
                playback_done = asyncio.Event()
    
                def after_playing(error):
                    if error:
                        print(f"Playback error: {error}")
                    self.bot.loop.call_soon_threadsafe(playback_done.set)
    
                voice.play(transformed, after=after_playing)
    
                if not is_tts:
                    await ctx.send(f"🎵 Now playing: `{Path(song_path).stem}`")
    
                await playback_done.wait()
    
                # 🔒 Stop may have cleared the queue during this time
                if not self.queue.get(guild_id):
                    self.current_track[guild_id] = None
                    continue
    
                # Reset track after successful play
                self.current_track[guild_id] = None
    
            except Exception as e:
                # Optional debug: uncomment during dev
                # await ctx.send(f"⚠️ Playback error: {e}")
                continue
    

    @jukebox.command(name="volume")
    async def volume(self, ctx: commands.Context, value: Optional[float] = None):
        """Change the playback volume."""
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
        """remove a file from the library."""
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
        """Stop playback and clear the queue without skipping to the next song."""
        voice = ctx.voice_client
        guild_id = ctx.guild.id
    
        if voice is None or not voice.is_connected():
            await ctx.send("I'm not in a voice channel.")
            return
    
        # Clear queue and track
        self.queue[guild_id] = []
        self.current_track[guild_id] = None
    
        if voice.is_playing():
            voice.stop()
    
        await ctx.send("🛑 Playback stopped and queue cleared.")
    
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
        """Display the currently playing track and the rest of the queue."""
        guild_id = ctx.guild.id
    
        now_playing = None
        if guild_id in self.current_track and self.current_track[guild_id]:
            now_playing = Path(self.current_track[guild_id]).stem
    
        queue_entries = self.queue.get(guild_id, [])
    
        if not now_playing and not queue_entries:
            await ctx.send("📭 Nothing is currently playing and the queue is empty.")
            return
    
        pages = list(chunk_list(queue_entries, 10))
        current = 0
    
        def format_page(index):
            lines = []
            if now_playing:
                lines.append(f"▶️ **Now Playing:** `{now_playing}`")
            if queue_entries:
                lines.append("🎶 **Up Next:**")
                lines.extend(f"`{Path(track).stem}`" for track in pages[index])
            return f"**Jukebox Queue** (Page {index + 1}/{len(pages)})\n" + "\n".join(lines)
    
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

    @jukebox.command(name="shuffle")
    async def shuffle(self, ctx: commands.Context):
        """Shuffle and queue all tracks from the jukebox library."""
        guild_id = ctx.guild.id
        songs = list(self.library_path.glob("*.mp3"))
    
        if not songs:
            await ctx.send("📭 The jukebox library is empty.")
            return
    
        random.shuffle(songs)
    
        self.queue[guild_id] = [str(song) for song in songs]
        
        await ctx.send(f"🔀 Queued `{len(songs)}` songs in random order.")
        
        if guild_id not in self.players:
            self.players[guild_id] = self.bot.loop.create_task(self._playback_loop(ctx))
    
    def _get_playlist_file(self, name: str) -> Path:
        safe_name = sanitize_filename(name.strip().lower())
        return self.playlist_path / f"{safe_name}.json"
    
    def _load_playlist(self, name: str) -> list[str]:
        path = self._get_playlist_file(name)
        if not path.is_file():
            return []
        with open(path, "r") as f:
            return json.load(f)
    
    def _save_playlist(self, name: str, songs: list[str]):
        path = self._get_playlist_file(name)
        with open(path, "w") as f:
            json.dump(songs, f)

    @jukebox.group(name="playlist",invoke_without_command=True)
    async def playlist(self, ctx: commands.Context):
        """Manage playlists."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @playlist.command(name="create")
    async def playlist_create(self, ctx: commands.Context, name: str):
        """Create a new playlist."""
        path = self._get_playlist_file(name)
        if path.exists():
            await ctx.send(f"❌ Playlist `{name}` already exists.")
            return
        self._save_playlist(name, [])
        await ctx.send(f"✅ Created new playlist `{name}`.")

    @playlist.command(name="add")
    async def playlist_add(self, ctx: commands.Context, name: str, *, song_name: str):
        """Add a new track to a playlist from the library."""
        song_path = self.library_path / f"{sanitize_filename(song_name)}.mp3"
        if not song_path.exists():
            await ctx.send(f"❌ Song `{song_name}` not found in the jukebox library.")
            return
    
        playlist = self._load_playlist(name)
        playlist.append(str(song_path))
        self._save_playlist(name, playlist)
        await ctx.send(f"✅ Added `{song_name}` to playlist `{name}`.")

    @playlist.command(name="play")
    async def playlist_play(self, ctx: commands.Context, name: str):
        """Stop current playback and start playing a playlist."""
        playlist_data = self._load_playlist(name)
        if not playlist_data:
            await ctx.send(f"❌ Playlist `{name}` is empty or does not exist.")
            return
    
        guild_id = ctx.guild.id
        voice = ctx.voice_client
    
        # Stop playback if necessary
        if voice and voice.is_connected():
            if voice.is_playing():
                voice.stop()
    
        # Clear queue and track
        self.queue[guild_id] = []
        self.current_track[guild_id] = None
    
        # Add songs to queue
        for song_path in playlist_data:
            if Path(song_path).is_file():
                self.queue[guild_id].append(song_path)
    
        await ctx.send(f"▶️ Playing playlist `{name}` with `{len(playlist_data)}` tracks.")
    
        # Start the playback loop if not running
        if guild_id not in self.players or self.players[guild_id].done():
            self.players[guild_id] = self.bot.loop.create_task(self._playback_loop(ctx))

    @playlist.command(name="delete")
    async def playlist_delete(self, ctx: commands.Context, name: str):
        """Delete a playlist."""
        path = self._get_playlist_file(name)
        if not path.exists():
            await ctx.send(f"❌ Playlist `{name}` does not exist.")
            return
    
        try:
            path.unlink()
            await ctx.send(f"🗑️ Deleted playlist `{name}`.")
        except Exception as e:
            await ctx.send(f"⚠️ Failed to delete playlist `{name}`: {e}")

    @playlist.command(name="remove")
    async def playlist_remove(self, ctx: commands.Context, name: str, *, track_name: str):
        """Remove a track from a playlist."""
        playlist = self._load_playlist(name)
        if not playlist:
            await ctx.send(f"❌ Playlist `{name}` is empty or does not exist.")
            return
    
        # Match by sanitized stem
        sanitized = sanitize_filename(track_name.strip().lower())
        for i, path in enumerate(playlist):
            if Path(path).stem.lower() == sanitized:
                removed = playlist.pop(i)
                self._save_playlist(name, playlist)
                await ctx.send(f"❎ Removed `{Path(removed).stem}` from playlist `{name}`.")
                return
    
        await ctx.send(f"❌ Track `{track_name}` not found in playlist `{name}`.")
        
    @jukebox.command(name="say")
    async def say(self, ctx: commands.Context, *, text: str):
        """Speak a TTS message, then resume the current track from the same position."""
        voice = ctx.voice_client
        if not voice or not voice.is_connected():
            await ctx.send("I'm not in a voice channel.")
            return
    
        guild_id = ctx.guild.id
        current_track = self.current_track.get(guild_id)
        queue = self.queue.setdefault(guild_id, [])
    
        # Estimate playback time
        current_pos = 0
        if voice.is_playing() and hasattr(voice.source, "_start_time"):
            current_pos = time.time() - voice.source._start_time
    
        if voice.is_playing():
            voice.stop()
    
        # Generate TTS clip
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            gTTS(text).save(f.name)
            tts_path = f.name
    
        # Insert TTS at front of queue, marked with `tts=True` and volume override
        queue.insert(0, {
            "path": tts_path,
            "tts": True,
            "volume": 1.0  # Force full volume
        })
    
        # Resume music afterward, if interrupted
        if current_track:
            queue.insert(1, {
                "path": current_track,
                "seek": int(current_pos)
            })
            self.current_track[guild_id] = None
    
        if guild_id not in self.players or self.players[guild_id].done():
            self.players[guild_id] = self.bot.loop.create_task(self._playback_loop(ctx))
    
        try:
            await ctx.message.add_reaction("🗣️")
        except discord.HTTPException:
            pass

        
#    @jukebox.command(name="ttsvoice")
#    async def ttsvoice(self, ctx: commands.Context, *, voice: Optional[str] = None):
#        """Set or display the current TTS voice (e.g. en-US-AriaNeural)."""
#        if voice is None:
#            current = await self.config.guild(ctx.guild).tts_voice()
#            if current:
#                await ctx.send(f"🗣️ Current TTS voice: `{current}`")
#            else:
#                await ctx.send("⚠️ No TTS voice set. Default will be used.")
#            return
#    
#        # Optional: validate known voice list here
#        await self.config.guild(ctx.guild).tts_voice.set(voice)
#        await ctx.send(f"✅ TTS voice set to `{voice}`")

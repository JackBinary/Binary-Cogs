"""Main module for the InteractiveShell cog."""

import asyncio
from datetime import datetime

from redbot.core import commands
from redbot.core.bot import Red

# Attempt to import optional SSH handler
try:
    from . import ssh_handler
    HAS_PARAMIKO = True
except (ImportError, ModuleNotFoundError):
    HAS_PARAMIKO = False


class InteractiveShell(commands.Cog):
    """A cog for an interactive shell session."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.sessions = {}
        if HAS_PARAMIKO:
            self.ssh_clients = {}
        self.log_file = "shell_session_log.txt"

    def log_attempt(self, user, session_type):
        """Log an attempt to start a shell or SSH session."""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(
                    f"{datetime.utcnow().isoformat()} - {user} "
                    f"(ID: {user.id}) attempted to start a {session_type} session.\n"
                )
        except OSError:
            # Suppressed log failure, common in readonly containers
            pass

    @commands.command()
    @commands.is_owner()
    async def start_shell(self, ctx):
        """Start an interactive shell session."""
        self.log_attempt(ctx.author, "shell")
    
        if ctx.author.id in self.sessions:
            await ctx.send("You already have an active shell session.")
            return
    
        proc = await asyncio.create_subprocess_shell(
            "/bin/bash",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    
        self.sessions[ctx.author.id] = proc
        await ctx.send("Started interactive shell session. Type 'exit' to end the session.")
    
        async def reader(stream, label: str):
            try:
                while True:
                    chunk = await stream.read(200)
                    if not chunk:
                        break
                    text = chunk.decode(errors="replace")
                    # Prefix stderr so you know which is which
                    prefix = "" if label == "stdout" else "[stderr]\n"
                    await ctx.send(f"```\n{prefix}{text}\n```")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                await ctx.send(f"{label} reader error: {e}")
    
        # Run both readers concurrently until the process exits
        stdout_task = asyncio.create_task(reader(proc.stdout, "stdout"))
        stderr_task = asyncio.create_task(reader(proc.stderr, "stderr"))
    
        try:
            await proc.wait()  # Wait until the shell ends
        finally:
            stdout_task.cancel()
            stderr_task.cancel()
            if ctx.author.id in self.sessions:
                del self.sessions[ctx.author.id]
            await ctx.send("Shell session has ended.")


    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle incoming messages for active shell sessions."""
        if message.author.id not in self.sessions:
            return

        proc = self.sessions[message.author.id]
        if message.content.strip().lower() == "exit":
            proc.terminate()
            await message.channel.send("Ending shell session.")
            del self.sessions[message.author.id]
            return

        proc.stdin.write(f"{message.content}\n".encode())
        await proc.stdin.drain()

    @commands.command()
    @commands.is_owner()
    async def end_shell(self, ctx):
        """End the interactive shell session."""
        if ctx.author.id not in self.sessions:
            await ctx.send("You do not have an active shell session.")
            return

        proc = self.sessions[ctx.author.id]
        proc.terminate()
        await ctx.send("Ending shell session.")
        del self.sessions[ctx.author.id]


# Patch in SSH commands if available
if HAS_PARAMIKO:
    ssh_handler.add_ssh_commands(InteractiveShell)  # pylint: disable=import-outside-toplevel


def setup(bot):
    """Redbot entry point."""
    bot.add_cog(InteractiveShell(bot))

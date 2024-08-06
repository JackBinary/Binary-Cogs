import asyncio
import subprocess
import discord
from redbot.core import commands
from redbot.core.bot import Red
from datetime import datetime

class InteractiveShell(commands.Cog):
    """A cog for an interactive shell session."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.sessions = {}
        self.log_file = "shell_session_log.txt"

    def log_attempt(self, user):
        """Log an attempt to start a shell session."""
        with open(self.log_file, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()} - {user} (ID: {user.id}) attempted to start a shell session.\n")

    @commands.command()
    @commands.is_owner()
    async def start_shell(self, ctx):
        """Start an interactive shell session."""
        self.log_attempt(ctx.author)
        
        if ctx.author.id in self.sessions:
            await ctx.send("You already have an active shell session.")
            return

        # Start the shell process
        proc = await asyncio.create_subprocess_shell(
            '/bin/bash',
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        self.sessions[ctx.author.id] = proc
        await ctx.send("Started interactive shell session. Type 'exit' to end the session.")

        while True:
            try:
                # Read the output from the shell
                output = await proc.stdout.read(100)
                if output:
                    await ctx.send(f"```\n{output.decode()}\n```")

                # Check if the process has terminated
                if proc.returncode is not None:
                    await ctx.send("Shell session has ended.")
                    del self.sessions[ctx.author.id]
                    break
            except Exception as e:
                await ctx.send(f"An error occurred: {e}")
                break

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.id not in self.sessions:
            return

        proc = self.sessions[message.author.id]
        if message.content.strip().lower() == 'exit':
            proc.terminate()
            await message.channel.send("Ending shell session.")
            del self.sessions[message.author.id]
            return

        # Send the command to the shell process
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

def setup(bot):
    bot.add_cog(InteractiveShell(bot))

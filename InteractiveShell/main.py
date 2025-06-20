"""Main module for the InteractiveShell cog."""

import asyncio
import io
from datetime import datetime

import discord
from redbot.core import commands
from redbot.core.bot import Red

# Attempt to import paramiko
try:
    import paramiko
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
        except Exception:
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

        while True:
            try:
                output = await proc.stdout.read(100)
                if output:
                    await ctx.send(f"```\n{output.decode()}\n```")

                if proc.returncode is not None:
                    await ctx.send("Shell session has ended.")
                    del self.sessions[ctx.author.id]
                    break
            except Exception as e:
                await ctx.send(f"An error occurred: {e}")
                break

    if HAS_PARAMIKO:
        @commands.command()
        @commands.is_owner()
        async def start_ssh(self, ctx, ip: str, username: str, password: str):
            """Start an SSH session."""
            self.log_attempt(ctx.author, "SSH")

            if ctx.author.id in self.ssh_clients:
                await ctx.send("You already have an active SSH session.")
                return

            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(ip, username=username, password=password)
                self.ssh_clients[ctx.author.id] = client
                await ctx.send(
                    f"Connected to {ip} as {username}. Type 'exit' or use '[p]end_ssh' to end the session."
                )
            except Exception as e:
                await ctx.send(f"Failed to connect: {e}")
                return

            while True:
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel

                try:
                    message = await self.bot.wait_for("message", check=check)
                    if message.content.strip().lower() == "exit":
                        client.close()
                        await ctx.send("Ending SSH session.")
                        del self.ssh_clients[ctx.author.id]
                        break

                    _, stdout, stderr = client.exec_command(message.content)
                    output = stdout.read().decode() + stderr.read().decode()

                    if len(output) > 2000:
                        await ctx.send("Output too long to display, sending as a file.")
                        buffer = io.BytesIO(output.encode())
                        buffer.seek(0)
                        await ctx.send(file=discord.File(fp=buffer, filename="ssh_output.txt"))
                    else:
                        await ctx.send(f"```\n{output}\n```")
                except Exception as e:
                    await ctx.send(f"An error occurred: {e}")
                    break

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

    if HAS_PARAMIKO:
        @commands.command()
        @commands.is_owner()
        async def end_ssh(self, ctx):
            """End the interactive SSH session."""
            if ctx.author.id not in self.ssh_clients:
                await ctx.send("You do not have an active SSH session.")
                return

            client = self.ssh_clients[ctx.author.id]
            client.close()
            await ctx.send("Ending SSH session.")
            del self.ssh_clients[ctx.author.id]


def setup(bot):
    """Redbot entry point."""
    bot.add_cog(InteractiveShell(bot))

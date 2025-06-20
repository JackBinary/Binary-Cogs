"""Optional SSH session support for the InteractiveShell cog."""

import asyncio
import io
import discord
import paramiko

DISCORD_CHAR_LIMIT = 2000


def add_ssh_commands(cls):
    """Dynamically attach SSH command methods to the given cog class."""

    async def start_ssh(self, ctx, ip: str, username: str, password: str):
        """Start an SSH session."""
        self.log_attempt(ctx.author, "SSH")

        if ctx.author.id in self.ssh_clients:
            await ctx.send("You already have an active SSH session.")
            return

        client = await _connect_ssh(ctx, ip, username, password)
        if client is None:
            return

        self.ssh_clients[ctx.author.id] = client
        await ctx.send(
            f"Connected to {ip} as {username}. "
            "Type 'exit' or use '[p]end_ssh' to end the session."
        )

        await self.handle_ssh_session(ctx, client)

    async def end_ssh(self, ctx):
        """End the interactive SSH session."""
        if ctx.author.id not in self.ssh_clients:
            await ctx.send("You do not have an active SSH session.")
            return

        client = self.ssh_clients[ctx.author.id]
        client.close()
        await ctx.send("Ending SSH session.")
        del self.ssh_clients[ctx.author.id]

    async def handle_ssh_session(self, ctx, client):
        """Handle interactive SSH command input from a user."""
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        while True:
            try:
                message = await self.bot.wait_for("message", check=check)
                if message.content.strip().lower() == "exit":
                    client.close()
                    await ctx.send("Ending SSH session.")
                    del self.ssh_clients[ctx.author.id]
                    break

                _, stdout, stderr = client.exec_command(message.content)
                output = stdout.read().decode() + stderr.read().decode()

                if len(output) > DISCORD_CHAR_LIMIT:
                    await _send_output_as_file(ctx, output)
                else:
                    await ctx.send(f"```\n{output}\n```")

            except UnicodeDecodeError:
                await ctx.send("Received output could not be decoded (non-UTF-8).")
                continue
            except paramiko.SSHException as e:
                await ctx.send(f"SSH command error: {e}")
                break
            except asyncio.CancelledError:
                await ctx.send("SSH session was cancelled.")
                break
            except Exception as e:  # pylint: disable=broad-exception-caught
                await ctx.send(f"Unexpected error during session: {e}")
                break

    cls.start_ssh = start_ssh
    cls.end_ssh = end_ssh
    cls.handle_ssh_session = handle_ssh_session


async def _connect_ssh(ctx, ip, username, password):
    """Try to connect to an SSH server and return the client object if successful."""
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=username, password=password)
        return client
    except paramiko.AuthenticationException:
        await ctx.send("Authentication failed. Check your username and password.")
    except paramiko.SSHException as e:
        await ctx.send(f"SSH error: {e}")
    except OSError as e:
        await ctx.send(f"Network or hostname error: {e}")
    except Exception as e:  # pylint: disable=broad-exception-caught
        await ctx.send(f"Unexpected error during connection: {e}")
    return None


async def _send_output_as_file(ctx, output):
    """Send long SSH output as a file attachment."""
    buffer = io.BytesIO(output.encode())
    buffer.seek(0)
    await ctx.send(file=discord.File(fp=buffer, filename="ssh_output.txt"))

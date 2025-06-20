"""Setup module for the InteractiveShell cog."""

import json
from pathlib import Path

from redbot.core.bot import Red

from .main import InteractiveShell

with open(Path(__file__).parent / "info.json", encoding="utf-8") as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]

async def setup(bot: Red) -> None:
    """Add the InteractiveShell cog to the bot."""
    await bot.add_cog(InteractiveShell(bot))

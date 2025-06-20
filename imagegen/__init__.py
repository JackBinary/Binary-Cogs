"""Initialize the ImageGen cog and load metadata for Red."""

import json
from pathlib import Path

from redbot.core.bot import Red

from .imagegen import ImageGen

# Load end user data statement from info.json
with open(Path(__file__).parent / "info.json", encoding="utf-8") as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]

async def setup(bot: Red) -> None:
    """Load the ImageGen cog into the bot."""
    await bot.add_cog(ImageGen(bot))

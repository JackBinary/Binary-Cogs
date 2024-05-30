import base64
from io import BytesIO
import uuid
import requests
import discord
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config

class ImageGen(commands.Cog):
    """
    Chat with an LLM in Discord!
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=133041100356059137,
            force_registration=True,
        )
        self.config_dir = ".imagegen"
        self.default_negative = "source_furry, source_pony, cartoon, 3d, realistic, monochrome, text, watermark, censored"
        self.default_positive = "score_9, score_8_up, score_7_up, score_6_up, source_anime"
        self.default_loras = "<lora:Fizintine_Style:0.6> <lora:JdotKdot_PDXL-v1:0.7>"
    
    @commands.command(name="draw")
    async def draw(self, ctx, *, text: str):
        """
        Generate images in discord!
        """
        tokens = [token.strip() for token in text.split(",")]
        positive_prompt = []
        negative_prompt = []
        width, height = 832, 1248  # Default to portrait
        seed = -1 # default to random

        for token in tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                key, value = key.strip(), value.strip()
                if key == "ratio":
                    if value == "portrait":
                        width, height = 832, 1248
                    elif value == "square":
                        width, height = 1024, 1024
                    elif value == "landscape":
                        width, height = 1248, 832
                if key == "seed":
                    seed = int(value)
            elif token.startswith("-"):
                negative_prompt.append(token.lstrip("-").strip())
            else:
                positive_prompt.append(token)
        
        payload = {
            "prompt": self.default_loras + self.default_positive + " " + ", ".join(positive_prompt),
            "negative_prompt": self.default_negative + ", ".join(negative_prompt),
            "seed": seed,
            "steps": 8,
            "width": width,
            "height": height,
            "cfg_scale": 2,
            "sampler_name": "DPM++ 2M SDE",
            "scheduler" : "SGM Uniform",
            "n_iter": 1,
            "batch_size": 1,
        }

        async with ctx.typing():
            response = requests.post(url='http://192.168.1.177:7860/sdapi/v1/txt2img', json=payload).json()
            image = BytesIO(base64.b64decode(response['images'][0]))
            image.seek(0)
        await ctx.send(file=discord.File(fp=image,filename=f"{uuid.uuid4().hex}.png"))
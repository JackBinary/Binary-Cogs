import base64
from io import BytesIO
import json
import uuid
import requests
import discord
import os
import re
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config


class ImageGen(commands.Cog):
    """Cog for generating images using Stable Diffusion WebUI API"""

    def __init__(self, bot):
        self.bot = bot
        # Initialize Config with default settings
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_global = {"api_url": "http://127.0.0.1:7860"}
        self.config.register_global(**default_global)

    @commands.command()
    async def setapiurl(self, ctx, url: str):
        """Sets the API URL for the Stable Diffusion WebUI."""
        await self.config.api_url.set(url)
        await ctx.reply(f"API URL has been set to: {url}", mention_author=True)

    @commands.command()
    async def getapiurl(self, ctx):
        """Gets the current API URL."""
        api_url = await self.config.api_url()
        await ctx.reply(f"The current API URL is: {api_url}", mention_author=True)

    @commands.command(name="draw")
async def draw(self, ctx, *, text: str):
    """
    Generate images in Discord with txt2img followed by img2img for upscaling!
    """
    tokens = [token.strip() for token in text.split(",")]
    positive_prompt = []
    negative_prompt = []
    # Default to portrait (both initial and upscaled resolutions)
    width, height = 832, 1216
    upscale_width, upscale_height = 1080, 1576
    seed = -1  # default to random

    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            key, value = key.strip(), value.strip()
            if key == "aspect":
                if value == "portrait":
                    width, height, upscale_width, upscale_height = 832, 1216, 1080, 1576
                elif value == "square":
                    width, height, upscale_width, upscale_height = 1024, 1024, 1328, 1328
                elif value == "landscape":
                    width, height, upscale_width, upscale_height = 1216, 832, 1576, 1080
            if key == "seed":
                seed = int(value)
            if key == "strength":
                strength = float(value)
        elif token.startswith("-"):
            negative_prompt.append(token.lstrip("-").strip())
        else:
            positive_prompt.append(token)

    positive_prompt = ', '.join(positive_prompt)
    negative_prompt = ', '.join(negative_prompt)

    # First Image (txt2img)
    payload = {
        "prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "steps": 8,
        "width": width,
        "height": height,
        "cfg_scale": 2.5,
        "sampler_index": "Euler a",
        "scheduler": "SGM Uniform"
    }

    api_url = await self.config.api_url()

    # Generate initial txt2img image
    await ctx.reply(f"Generating initial image...", mention_author=True)
    image = await self.generate_image(ctx, payload, api_url, 'sdapi/v1/txt2img')

    # Send the first image to the user as a reply
    message = await ctx.reply(file=File(fp=image, filename=f"{uuid.uuid4().hex}.png"))

    # Prepare the image for img2img upscaling
    image.seek(0)  # Ensure the pointer is at the start of the file
    init_image_base64 = base64.b64encode(image.getvalue()).decode('utf-8')

    # Prepare img2img payload
    img2img_payload = {
        "prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "steps": 8,
        "width": upscale_width,
        "height": upscale_height,
        "cfg_scale": 2.5,
        "sampler_index": "Euler a",
        "scheduler": "SGM Uniform",
        "init_images": [init_image_base64],
    }

    # Generate the upscaled image
    final_image = await self.generate_image(ctx, img2img_payload, api_url, 'sdapi/v1/img2img')

    # Replace the previous image with the upscaled one
    await message.edit(attachments=[File(fp=final_image, filename=f"{uuid.uuid4().hex}.png")])


    async def generate_image(self, ctx, payload, api_url, endpoint):
        """Helper function to send payload to the Stable Diffusion API and return the generated image."""
        try:
            response = requests.post(url=f'{api_url}/{endpoint}', json=payload)
            r = response.json()

            # Decode the image from base64
            img_data = base64.b64decode(r['images'][0])
            img = BytesIO(img_data)
            img.seek(0)

            return img

        except Exception as e:
            await ctx.reply(f"An error occurred: {str(e)}", mention_author=True)
            return None

import base64
from io import BytesIO
import uuid
import requests
import discord
from discord import File
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
        strength = 0.5

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
            "enable_hr" : true,
            "hr_cfg" : 2.5,
            "denoising_strength" : 0.7,
            "hr_scale" : 1.3,
            "hr_second_pass_steps" : 8,
            "hr_upscaler" : "Latent",
            "prompt": positive_prompt,
            "hr_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "hr_negative_prompt": negative_prompt,
            "seed": seed,
            "steps": 8,
            "width": width,
            "height": height,
            "cfg_scale": 2.5,
            "sampler_name": "Euler a",
            "scheduler": "SGM Uniform",
            "batch_size": 1,
            "n_iter": 1
        }

        # Generate initial txt2img image
        message = await ctx.reply(f"...", mention_author=True)
        image = await self.generate_image(ctx, payload, 'sdapi/v1/txt2img')

        # Check if the image is None
        if image is None:
            await message.edit(f"Failed to generate the image. Please check the API and try again.")
            return

        # Attach the first image to the original reply
        await message.edit(attachments=[File(fp=image, filename=f"{uuid.uuid4().hex}.png")])

    async def generate_image(self, ctx, payload, endpoint):
        """Helper function to send payload to the Stable Diffusion API and return the generated image."""
        try:
            # Get the API URL from the config
            api_url = await self.config.api_url()

            # Sending request to the API
            response = requests.post(f"{api_url}/{endpoint}", json=payload)
            response.raise_for_status()

            # Parse response JSON
            response_json = response.json()

            # Check if images are in the response
            if 'images' not in response_json or not response_json['images']:
                await ctx.reply("No images found in the API response.")
                return None

            # Decode the base64-encoded image and return it as a BytesIO object
            image_data = base64.b64decode(response_json['images'][0])
            image = BytesIO(image_data)
            image.seek(0)
            return image

        except Exception as e:
            await ctx.reply(f"An error occurred while generating the image: {str(e)}", mention_author=True)
            return None

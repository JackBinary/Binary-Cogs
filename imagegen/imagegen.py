import base64
from io import BytesIO
import uuid
import requests
import asyncio
from discord import File
from redbot.core import commands
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
        Generate images in Discord with real-time live preview tracking using txt2img.
        """
        tokens = [token.strip() for token in text.split(",")]
        positive_prompt = []
        negative_prompt = []
        # Default to portrait (both initial and upscaled resolutions)
        width, height = 832, 1216
        seed = -1  # default to random
        strength = 0.5

        for token in tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                key, value = key.strip(), value.strip()
                if key == "aspect":
                    if value == "portrait":
                        width, height = 832, 1216
                    elif value == "square":
                        width, height = 1024, 1024
                    elif value == "landscape":
                        width, height = 1216, 832
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

        # High-Resolution settings for the first Image (txt2img)
        payload = {
            "enable_hr": True,
            "hr_cfg": 2.5,
            "denoising_strength": 0.7,
            "hr_scale": 1.3,
            "hr_second_pass_steps": 8,
            "hr_upscaler": "Latent",
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

        # Start image generation in the background
        async with ctx.typing():
            task_id = await self.start_image_generation(ctx, payload, 'sdapi/v1/txt2img')

            # If task_id is None, image generation failed
            if task_id is None:
                await ctx.reply("Failed to start image generation. Please check the API.", mention_author=True)
                return

            # Send an initial message to the user that will be edited later
            message = await ctx.send("Starting image generation...")

            # Start polling the progress endpoint and updating the message with live previews
            await self.track_progress_with_live_preview(ctx, task_id, message)

            # After the progress completes, retrieve the final image
            image = await self.get_generated_image(ctx, payload, 'sdapi/v1/txt2img')

        # Check if the image is None
        if image is None:
            await message.edit(content="Failed to generate the final image. Please check the API and try again.")
            return

        # Send the final image in the same message
        await message.edit(content="", attachments=[File(fp=image, filename=f"{uuid.uuid4().hex}.png")])

    async def start_image_generation(self, ctx, payload, endpoint):
        """Start the image generation task and return the task ID."""
        try:
            # Get the API URL from the config
            api_url = await self.config.api_url()

            # Start the image generation task
            response = requests.post(f"{api_url}/{endpoint}", json=payload)
            response.raise_for_status()

            # Parse response JSON
            response_json = response.json()

            # Assuming task ID is returned in the response (modify this according to your API)
            return response_json.get("id_task")

        except Exception as e:
            await ctx.reply(f"An error occurred while starting image generation: {str(e)}", mention_author=True)
            return None

    async def track_progress_with_live_preview(self, ctx, task_id, message):
        """Track the progress of the image generation and update live previews."""
        try:
            api_url = await self.config.api_url()

            previous_live_preview = None  # To track if live preview has changed

            # Poll the progress endpoint every 5 seconds
            while True:
                progress_payload = {
                    "id_task": task_id,
                    "id_live_preview": -1,
                    "live_preview": True
                }
                response = requests.post(f"{api_url}/internal/progress", json=progress_payload)
                response.raise_for_status()
                progress = response.json()

                # Check if the task is complete
                if progress.get("completed", False):
                    break

                # Extract progress info
                progress_percentage = progress.get("progress", 0) * 100
                eta = progress.get("eta", 0)

                # Extract the live preview image
                live_preview_data = progress.get("live_preview")
                if live_preview_data and live_preview_data != previous_live_preview:
                    # Decode the live preview image
                    live_preview_image = BytesIO(base64.b64decode(live_preview_data))
                    live_preview_image.seek(0)

                    # Edit the message with the updated live preview
                    await message.edit(
                        content=f"Progress: {progress_percentage:.2f}% - ETA: {eta:.2f} seconds",
                        attachments=[File(fp=live_preview_image, filename=f"live_preview_{uuid.uuid4().hex}.png")]
                    )

                    # Update the previous live preview to avoid redundant updates
                    previous_live_preview = live_preview_data

                # Sleep for 5 seconds before polling again
                await asyncio.sleep(5)

        except Exception as e:
            await ctx.reply(f"An error occurred while tracking progress: {str(e)}", mention_author=True)

    async def get_generated_image(self, ctx, payload, endpoint):
        """Retrieve the final generated image."""
        try:
            # Get the API URL from the config
            api_url = await self.config.api_url()

            # Sending request to the API to get the image
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
            await ctx.reply(f"An error occurred while retrieving the image: {str(e)}", mention_author=True)
            return None

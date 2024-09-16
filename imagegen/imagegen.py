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
        # Generate a UUID for this task and filenames
        task_id = str(uuid.uuid4())
        
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

        # High-Resolution settings for the first Image (txt2img) and set task_id
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
            "n_iter": 1,
            "force_task_id": task_id  # Set the task_id here
        }

        # Start image generation in the background
        async with ctx.typing():
            # Start polling the progress endpoint and sending the first live preview
            message = None  # No message sent until we get the first preview
            await self.track_progress_with_live_preview(ctx, task_id, message, payload)

    async def track_progress_with_live_preview(self, ctx, task_id, message, payload):
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

                    if message is None:
                        # Send the first message with the first live preview
                        message = await ctx.send(file=File(fp=live_preview_image, filename=f"live_preview_{task_id}.png"))
                    else:
                        # Edit the message with the updated live preview
                        await message.edit(
                            content=f"Progress: {progress_percentage:.2f}% - ETA: {eta:.2f} seconds",
                            attachments=[File(fp=live_preview_image, filename=f"live_preview_{task_id}.png")]
                        )

                    # Update the previous live preview to avoid redundant updates
                    previous_live_preview = live_preview_data

                # Sleep for 5 seconds before polling again
                await asyncio.sleep(5)

            # Once completed, get the final image
            final_image = await self.get_generated_image(ctx, payload, 'sdapi/v1/txt2img')

            # Edit the message to show the final image
            if final_image:
                await message.edit(content="", attachments=[File(fp=final_image, filename=f"{task_id}.png")])

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

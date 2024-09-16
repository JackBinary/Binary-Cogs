import base64
from io import BytesIO
import uuid
import requests
from discord import File
from redbot.core import commands
from redbot.core.config import Config
import threading
import asyncio
import time

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
        task_id = uuid.uuid4().hex
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
            "n_iter": 1,
            "force_task_id": task_id
        }

        # Start the image generation in a new thread
        threading.Thread(target=self.generate_image_and_track_progress, args=(ctx, payload, task_id)).start()

    def generate_image_and_track_progress(self, ctx, payload, task_id):
        """Run image generation in a separate thread, poll progress, and send live previews."""
        # Fetch the API URL in a thread-safe manner
        api_url = asyncio.run_coroutine_threadsafe(self.config.api_url(), self.bot.loop).result()

        # Start image generation
        image = self.generate_image(ctx, payload, f'{api_url}/sdapi/v1/txt2img')

        # If image generation failed, return
        if image is None:
            asyncio.run_coroutine_threadsafe(
                ctx.reply("Failed to generate the image. Please check the API and try again.", mention_author=True),
                self.bot.loop
            )
            return

        # Check for live previews while image is being generated
        self.poll_progress_and_send_preview(ctx, task_id, api_url)

        # Once the image is fully generated, send the final image
        asyncio.run_coroutine_threadsafe(
            ctx.reply(file=File(fp=image, filename=f"{task_id}.png"), mention_author=True),
            self.bot.loop
        )

    def poll_progress_and_send_preview(self, ctx, task_id, api_url):
        """Poll the progress endpoint and send live previews to Discord."""
        progress_endpoint = f"{api_url}/internal/progress"

        while True:
            try:
                # Send request to check progress
                response = requests.post(progress_endpoint, json={"id_task": task_id})
                response.raise_for_status()

                # Parse the response
                progress_data = response.json()

                # Check if the task is completed
                if progress_data.get("completed", False):
                    break

                # Check for a live preview
                live_preview_data = progress_data.get("live_preview", None)
                if live_preview_data:
                    # Decode the live preview image
                    live_preview_image_data = live_preview_data.split(",")[1]
                    live_preview_image = base64.b64decode(live_preview_image_data)
                    image_bytes = BytesIO(live_preview_image)
                    image_bytes.seek(0)

                    # Send the live preview image to Discord
                    asyncio.run_coroutine_threadsafe(
                        ctx.reply(file=File(fp=image_bytes, filename=f"live_preview_{task_id}.jpg")),
                        self.bot.loop
                    )

                # Sleep for a bit before checking again
                time.sleep(2)

            except requests.RequestException as e:
                asyncio.run_coroutine_threadsafe(
                    ctx.reply(f"An error occurred while polling for progress: {str(e)}", mention_author=True),
                    self.bot.loop
                )
                break

    def generate_image(self, ctx, payload, endpoint):
        """Helper function to send payload to the Stable Diffusion API and return the generated image."""
        try:
            # Set a timeout for the API request
            response = requests.post(endpoint, json=payload, timeout=30)
            response.raise_for_status()

            # Parse response JSON
            response_json = response.json()

            # Check if images are in the response
            if 'images' not in response_json or not response_json['images']:
                asyncio.run_coroutine_threadsafe(
                    ctx.reply("No images found in the API response."),
                    self.bot.loop
                )
                return None

            # Decode the base64-encoded image and return it as a BytesIO object
            image_data = base64.b64decode(response_json['images'][0])
            image = BytesIO(image_data)
            image.seek(0)
            return image

        except requests.exceptions.Timeout:
            asyncio.run_coroutine_threadsafe(
                ctx.reply("The request to the API timed out. Please try again later.", mention_author=True),
                self.bot.loop
            )
            return None

        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                ctx.reply(f"An error occurred while generating the image: {str(e)}", mention_author=True),
                self.bot.loop
            )
            return None

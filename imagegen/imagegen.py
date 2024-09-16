import threading
import base64
import uuid
from io import BytesIO
import requests
from discord import File
from redbot.core import commands
from redbot.core.config import Config
import time

class ImageGen(commands.Cog):
    """Cog for generating images using Stable Diffusion WebUI API with threading"""

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

        # Process tokens into prompt and other settings
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

        # Inform user the image is being generated
        await ctx.reply("Generating image...", mention_author=True)

        # Start threads for both image generation and live preview
        image_thread = threading.Thread(target=self.generate_image, args=(ctx, payload, task_id))
        preview_thread = threading.Thread(target=self.fetch_live_preview, args=(ctx, task_id))
        image_thread.start()
        preview_thread.start()

    def generate_image(self, ctx, payload, task_id):
        try:
            # Get the API URL from the config
            api_url = "http://127.0.0.1:7860"  # Replace this with your config logic
            response = requests.post(f"{api_url}/sdapi/v1/txt2img", json=payload, timeout=30)
            response.raise_for_status()

            # Handle the response
            response_json = response.json()
            if 'images' not in response_json or not response_json['images']:
                asyncio.run_coroutine_threadsafe(self.send_error(ctx, "No images found in the API response."), self.bot.loop)
                return

            # Convert the base64 image to BytesIO
            image_data = base64.b64decode(response_json['images'][0])
            image = BytesIO(image_data)
            image.seek(0)

            # Send the image back to Discord (switch to the event loop)
            asyncio.run_coroutine_threadsafe(self.send_final_image(ctx, image, task_id), self.bot.loop)

        except requests.exceptions.Timeout:
            asyncio.run_coroutine_threadsafe(self.send_error(ctx, "The request to the API timed out."), self.bot.loop)

        except Exception as e:
            asyncio.run_coroutine_threadsafe(self.send_error(ctx, f"An error occurred while generating the image: {str(e)}"), self.bot.loop)

    def fetch_live_preview(self, ctx, task_id):
        """Fetch live preview while the image is being generated"""
        try:
            api_url = "http://127.0.0.1:7860"  # Replace with your config logic
            live_preview_url = f"{api_url}/internal/progress"
            while True:
                progress_payload = {
                    "id_task": task_id,
                    "id_live_preview": -1,
                    "live_preview": True
                }
                # Request progress data
                response = requests.post(live_preview_url, json=progress_payload, timeout=10)
                response.raise_for_status()
                progress_data = response.json()

                # If completed, exit the loop
                if progress_data.get("completed"):
                    break

                # Process the live preview and send it as a Discord message
                if progress_data.get("live_preview"):
                    preview_image_data = progress_data['live_preview'].split(",")[1]
                    preview_image = BytesIO(base64.b64decode(preview_image_data))
                    preview_image.seek(0)
                    asyncio.run_coroutine_threadsafe(
                        self.send_live_preview(ctx, preview_image, task_id), self.bot.loop
                    )
                time.sleep(1)  # Sleep for 1 second before the next preview fetch

        except Exception as e:
            asyncio.run_coroutine_threadsafe(self.send_error(ctx, f"Error fetching live preview: {str(e)}"), self.bot.loop)

    async def send_live_preview(self, ctx, preview_image, task_id):
        """Helper function to send the live preview image to Discord."""
        await ctx.reply(file=File(fp=preview_image, filename=f"{task_id}_preview.png"), mention_author=True)

    async def send_final_image(self, ctx, image, task_id):
        """Helper function to send the final image back to Discord."""
        await ctx.reply(file=File(fp=image, filename=f"{task_id}.png"), mention_author=True)

    async def send_error(self, ctx, error_message):
        """Helper function to send an error message back to Discord."""
        await ctx.reply(error_message, mention_author=True)

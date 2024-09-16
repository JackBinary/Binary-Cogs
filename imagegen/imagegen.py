import base64
from io import BytesIO
import uuid
import requests
from discord import File
from redbot.core import commands
from redbot.core.config import Config
import asyncio

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
        print("Setting API URL")
        await self.config.api_url.set(url)
        await ctx.reply(f"API URL has been set to: {url}", mention_author=True)

    @commands.command()
    async def getapiurl(self, ctx):
        """Gets the current API URL."""
        print("Getting API URL")
        api_url = await self.config.api_url()
        await ctx.reply(f"The current API URL is: {api_url}", mention_author=True)

    @commands.command(name="draw")
    async def draw(self, ctx, *, text: str):
        """
        Generate images in Discord with txt2img followed by img2img for upscaling!
        """
        print("Starting draw command")
        task_id = uuid.uuid4().hex
        print(f"Task ID: {task_id}")
        tokens = [token.strip() for token in text.split(",")]
        positive_prompt = []
        negative_prompt = []
        # Default to portrait (both initial and upscaled resolutions)
        width, height = 832, 1216
        upscale_width, upscale_height = 1080, 1576
        seed = -1  # default to random
        strength = 0.5

        for token in tokens:
            print(f"Processing token: {token}")
            if "=" in token:
                key, value = token.split("=", 1)
                key, value = key.strip(), value.strip()
                print(f"Key: {key}, Value: {value}")
                if key == "aspect":
                    if value == "portrait":
                        width, height, upscale_width, upscale_height = 832, 1216, 1080, 1576
                    elif value == "square":
                        width, height, upscale_width, upscale_height = 1024, 1024, 1328, 1328
                    elif value == "landscape":
                        width, height, upscale_width, upscale_height = 1216, 832, 1576, 1080
                if key == "seed":
                    seed = int(value)
                    print(f"Seed set to: {seed}")
                if key == "strength":
                    strength = float(value)
                    print(f"Strength set to: {strength}")
            elif token.startswith("-"):
                negative_prompt.append(token.lstrip("-").strip())
                print(f"Added to negative prompt: {token.lstrip('-').strip()}")
            else:
                positive_prompt.append(token)
                print(f"Added to positive prompt: {token}")

        positive_prompt = ', '.join(positive_prompt)
        negative_prompt = ', '.join(negative_prompt)

        print(f"Final positive prompt: {positive_prompt}")
        print(f"Final negative prompt: {negative_prompt}")

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

        print("Payload created")
        print(payload)

        # Use typing indicator while generating image
        async with ctx.typing():
            print("Typing started")
            message = await ctx.reply("Generating image...", mention_author=True)
            print("Message sent: Generating image...")

            # Start the image generation in the background
            image_task = asyncio.create_task(self.generate_image(ctx, payload, 'sdapi/v1/txt2img'))

            live_preview = None
            print("Entering the in-progress loop")
            while not image_task.done():
                print("Waiting for image generation progress")
                await asyncio.sleep(0.5)
                progress_data = await self.get_live_preview(ctx, task_id)
                print(f"Progress data: {progress_data}")
                if progress_data and progress_data.get('active'):
                    try:
                        new_live_preview = progress_data['live_preview'].split(",")[1]
                        print(f"Live preview data: {new_live_preview}")
                    except (AttributeError, IndexError):
                        print("Error parsing live preview data")
                        continue
                    if new_live_preview != live_preview:
                        live_preview = new_live_preview
                        preview_image = BytesIO(base64.b64decode(live_preview))
                        preview_image.seek(0)
                        print(f"Sending live preview update: {task_id}_preview.png")
                        await message.edit(attachments=[File(fp=preview_image, filename=f"{task_id}_preview.png")])

            print("Image generation completed")

            # Wait for the final image
            image = await image_task

        # Check if the image is None
        if image is None:
            print("Image generation failed")
            await ctx.reply("Failed to generate the image. Please check the API and try again.", mention_author=True)
            return

        # Send the final image
        print("Sending final image")
        await message.edit(content=None, attachments=[File(fp=image, filename=f"{task_id}.png")])

    async def get_live_preview(self, ctx, task_id):
        """Helper function to send the request for live preview."""
        try:
            print("Fetching live preview")
            api_url = await self.config.api_url()
            progress_payload = {
                "id_task": task_id,
                "id_live_preview": -1,
                "live_preview": True
            }
            response = requests.post(f"{api_url}/internal/progress", json=progress_payload, timeout=10)
            response.raise_for_status()

            print(f"Live preview response: {response.json()}")
            return response.json()

        except Exception as e:
            print(f"Error occurred while fetching live preview: {e}")
            await ctx.reply(f"An error occurred while fetching live preview: {str(e)}", mention_author=True)
            return None

    async def generate_image(self, ctx, payload, endpoint):
        """Helper function to send payload to the Stable Diffusion API and return the generated image."""
        try:
            print("Generating image")
            # Get the API URL from the config
            api_url = await self.config.api_url()

            # Set a timeout for the API request
            response = requests.post(f"{api_url}/{endpoint}", json=payload, timeout=30)  # Set timeout to 30 seconds
            response.raise_for_status()

            # Parse response JSON
            response_json = response.json()
            print(f"Image generation response: {response_json}")

            # Check if images are in the response
            if 'images' not in response_json or not response_json['images']:
                print("No images found in the response")
                await ctx.reply("No images found in the API response.")
                return None

            # Decode the base64-encoded image and return it as a BytesIO object
            image_data = base64.b64decode(response_json['images'][0])
            image = BytesIO(image_data)
            image.seek(0)
            print("Image generation successful")
            return image

        except requests.exceptions.Timeout:
            print("API request timed out")
            await ctx.reply("The request to the API timed out. Please try again later.", mention_author=True)
            return None

        except Exception as e:
            print(f"Error occurred while generating image: {e}")
            await ctx.reply(f"An error occurred while generating the image: {str(e)}", mention_author=True)
            return None

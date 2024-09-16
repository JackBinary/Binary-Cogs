import base64
from io import BytesIO
import uuid
import requests
import asyncio
from discord import File
from redbot.core import commands
from redbot.core.config import Config

class ImageGen(commands.Cog):
    """Cog for generating images using Stable Diffusion WebUI API with live previews."""

    def __init__(self, bot):
        self.bot = bot
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
        Generate images in Discord with txt2img followed by img2img for upscaling, with live previews!
        """
        task_id = uuid.uuid4().hex
        tokens = [token.strip() for token in text.split(",")]
        positive_prompt = []
        negative_prompt = []
        width, height = 832, 1216
        upscale_width, upscale_height = 1080, 1576
        seed = -1
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

        async with ctx.typing():
            # Send the initial message with a placeholder image
            initial_message = await ctx.reply("Generating image... This may take a moment.", mention_author=True)

            # Start polling the live preview while the final image is being generated
            live_preview_task = asyncio.create_task(self.poll_live_preview(ctx, task_id, initial_message))

            # Generate the final image
            final_image = await self.generate_image(ctx, payload, 'sdapi/v1/txt2img')

            if final_image is None:
                await initial_message.edit(content="Failed to generate the image. Please check the API and try again.")
            else:
                await initial_message.edit(content="Here is your final image!",
                                           attachments=[File(fp=final_image, filename=f"{task_id}.png")])

            # Cancel live preview task once the final image is generated
            live_preview_task.cancel()
            try:
                await live_preview_task
            except asyncio.CancelledError:
                pass

    async def generate_image(self, ctx, payload, endpoint):
        """Helper function to send payload to the Stable Diffusion API and return the generated image."""
        try:
            api_url = await self.config.api_url()
            response = requests.post(f"{api_url}/{endpoint}", json=payload, timeout=30)
            response.raise_for_status()
            response_json = response.json()

            if 'images' not in response_json or not response_json['images']:
                await ctx.reply("No images found in the API response.")
                return None

            image_data = base64.b64decode(response_json['images'][0])
            image = BytesIO(image_data)
            image.seek(0)
            return image

        except requests.exceptions.Timeout:
            await ctx.reply("The request to the API timed out. Please try again later.", mention_author=True)
            return None

        except Exception as e:
            await ctx.reply(f"An error occurred while generating the image: {str(e)}", mention_author=True)
            return None

    async def poll_live_preview(self, ctx, task_id, message):
        """Polls the live preview endpoint to get image updates and edits the message with the preview."""
        last_preview_image_data = None  # Store the last preview image data for comparison

        while True:
            asyncio.sleep(0.5)
            try:
                # Poll the live preview endpoint
                progress_data = await self.get_live_preview(ctx, task_id)
    
                if progress_data:
                    if progress_data['active']:
                        try:
                            current_preview_image_data = progress_data.split(",")[1]
                        except AttributeError:
                            continue
                        if current_preview_image_data == last_preview_image_data:
                            continue
                            
                        preview_image = BytesIO(base64.b64decode(current_preview_image_data))
                        preview_image.seek(0)
                        await message.edit(attachments=[File(fp=preview_image, filename=f"{task_id}_preview.png")])

    async def get_live_preview(self, ctx, task_id):
        """Helper function to send the request for live preview."""
        try:
            api_url = await self.config.api_url()
            progress_payload = {
                "id_task": task_id,
                "id_live_preview": -1,
                "live_preview": True
            }
            response = requests.post(f"{api_url}/internal/progress", json=progress_payload, timeout=10)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            await ctx.reply(f"An error occurred while fetching live preview: {str(e)}", mention_author=True)
            return None

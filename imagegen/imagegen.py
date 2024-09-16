import uuid
import base64
import requests
import threading
from time import sleep
from io import BytesIO
from discord import File
from redbot.core import commands
from redbot.core.config import Config
import asyncio

class ImageGenerator:
    def __init__(self):
        self.api_url = "http://127.0.0.1:7860"
        self.txt2img = "sdapi/v1/txt2img"
        self.progress = "/internal/progress"
        self.tasks = []
        self.in_progress = []
        self.images = {}
        generator_thread = threading.Thread(target=self.generator)
        progress_thread = threading.Thread(target=self.get_progress)
        generator_thread.start()
        progress_thread.start()

    def set_url(self, url):
        self.api_url = url

    def new_task(self, task_id, payload):
        self.tasks.append({"id": task_id, "payload": payload})

    def callback(self, task_id):
        if task_id in self.images:
            return self.images[task_id]
        else:
            return False

    def generator(self):
        while True:
            if len(self.tasks) >= 1:
                task = self.tasks.pop(0)
                task_id = task["id"]
                payload = task["payload"]
                self.in_progress.append(task_id)

                # Generate image
                response = requests.post(f"{self.api_url}/{self.txt2img}", json=payload, timeout=60)
                response.raise_for_status()
                response_json = response.json()
                if 'images' in response_json:
                    self.in_progress.remove(task_id)
                    image_base64 = response_json['images'][0]
                    self.images[task_id] = {"image": image_base64, "complete": True}
            sleep(1)

    def get_progress(self):
        while True:
            for task_id in self.in_progress:
                payload = {
                    "id_task": task_id,
                    "id_live_preview": -1,
                    "live_preview": True
                }
                response = requests.post(f"{self.api_url}/{self.progress}", json=payload, timeout=60)
                response.raise_for_status()
                response_json = response.json()
                if 'live_preview' in response_json:
                    try:
                        image_base64 = response_json['live_preview'].split(",")[1]
                        self.images[task_id] = {"image": image_base64, "complete": False}
                    except AttributeError:
                        pass
            sleep(1)

    def remove_task(self, task_id):
        """Remove the task from the images dictionary after final image is sent."""
        if task_id in self.images:
            del self.images[task_id]

class ImageGen(commands.Cog):
    """Cog for generating images using Stable Diffusion WebUI API with ImageGenerator."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_global = {"api_url": "http://127.0.0.1:7860"}
        self.config.register_global(**default_global)

        # Initialize ImageGenerator without setting the API URL yet
        self.image_generator = ImageGenerator()

    @commands.Cog.listener()
    async def on_ready(self):
        # Set API URL when the bot is ready
        api_url = await self.config.api_url()
        self.image_generator.set_url(api_url)

    @commands.command()
    async def setapiurl(self, ctx, url: str):
        """Sets the API URL for the Stable Diffusion WebUI."""
        await self.config.api_url.set(url)
        self.image_generator.set_url(url)  # Update the ImageGenerator's URL
        await ctx.reply(f"API URL has been set to: {url}", mention_author=True)

    @commands.command()
    async def getapiurl(self, ctx):
        """Gets the current API URL."""
        api_url = await self.config.api_url()
        await ctx.reply(f"The current API URL is: {api_url}", mention_author=True)

    @commands.command(name="draw")
    async def draw(self, ctx, *, text: str):
        """Generate images with the Stable Diffusion WebUI."""
        task_id = uuid.uuid4().hex
        tokens = [token.strip() for token in text.split(",")]
        positive_prompt = []
        negative_prompt = []
        # Default to portrait dimensions and final resized resolution
        width, height = 832, 1216
        final_width, final_height = 1080, 1576
        seed = -1  # default to random
        strength = 0.5

        for token in tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                key, value = key.strip(), value.strip()
                if key == "aspect":
                    if value == "portrait":
                        width, height = 832, 1216
                        final_width, final_height = 1080, 1576
                    elif value == "square":
                        width, height = 1024, 1024
                        final_width, final_height = 1328, 1328
                    elif value == "landscape":
                        width, height = 1216, 832
                        final_width, final_height = 1576, 1080
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
            "negative_prompt": negative_prompt,
            "seed": seed,
            "steps": 8,
            "width": width,
            "height": height,
            "cfg_scale": 2.5,
            "sampler_name": "Euler a",
            "batch_size": 1,
            "n_iter": 1,
            "force_task_id": task_id
        }

        # Add the task to the ImageGenerator queue
        print(task_id, text)
        self.image_generator.new_task(task_id, payload)

        # Inform the user that the task has been submitted
        message = await ctx.reply(f"Generating...", mention_author=True)

        # Wait for the image generation result and fetch it
        async with ctx.typing():
            base64_image = None  # to track the last image's base64 string
            while True:
                result = self.image_generator.callback(task_id)
                if result:
                    current_image_base64 = result["image"]
                    if current_image_base64 != base64_image:  # Check if new image base64 string exists
                        base64_image = current_image_base64
                        # Decode the base64 string only when sending the image
                        image_data = base64.b64decode(base64_image)
                        image = BytesIO(image_data)
                        image.seek(0)

                        # Resize the image to the final dimensions
                        with Image.open(image) as img:
                            img = img.resize((final_width, final_height), Image.ANTIALIAS)
                            buffer = BytesIO()
                            img.save(buffer, format="PNG")
                            buffer.seek(0)

                        # Send the resized preview image
                        await message.edit(attachments=[File(fp=buffer, filename=f"{task_id}.png")])
    
                    if result["complete"]:
                        break
    
                await asyncio.sleep(1)  # Poll every second

            # Final cleanup after the image is complete
            self.image_generator.remove_task(task_id)
        await message.edit(content="Done!")

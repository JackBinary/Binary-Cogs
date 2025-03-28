import uuid
import base64
import requests
import threading
from time import sleep
from io import BytesIO
from PIL import Image
from discord import File, ButtonStyle, ui, Interaction
from redbot.core import commands
from redbot.core.config import Config
import asyncio

class ImageGenerator:
    def __init__(self):
        self.api_url = "http://127.0.0.1:7860"
        self.txt2img = "sdapi/v1/txt2img"
        self.img2img = "sdapi/v1/img2img"
        self.progress = "internal/progress"
        self.tasks = []
        self.in_progress = []
        self.images = {}
        generator_thread = threading.Thread(target=self.generator)
        progress_thread = threading.Thread(target=self.get_progress)
        generator_thread.start()
        progress_thread.start()

    def set_url(self, url):
        self.api_url = url

    def new_task(self, task_id, payload, type):
        self.tasks.append({"id": task_id, "payload": payload, "type":type})

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
                task_type = task["type"]
                self.in_progress.append(task_id)

                # Generate image
                if task_type == "img2img":
                    response = requests.post(f"{self.api_url}/{self.img2img}", json=payload, timeout=300)
                else:
                    response = requests.post(f"{self.api_url}/{self.txt2img}", json=payload, timeout=300)
                response.raise_for_status()
                response_json = response.json()
                if 'images' in response_json:
                    self.in_progress.remove(task_id)
                    image_base64 = response_json['images'][0]
                    self.images[task_id] = {"image": image_base64, "complete": True}
            sleep(0.5)

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
            sleep(0.5)

    def remove_task(self, task_id):
        """Remove the task from the images dictionary after final image is sent."""
        if task_id in self.images:
            del self.images[task_id]

class AcceptRetryDeleteButtons(ui.View):
    LABEL_TRY_AGAIN = "Try Again"
    LABEL_DRAWING = "Drawing..."

    def __init__(self, cog, ctx, task_id, payload, message, timeout=60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.task_id = task_id
        self.payload = payload
        self.message = message

    async def interaction_check(self, interaction: Interaction) -> bool:
        # Ensure only the original message author can interact with the buttons
        if interaction.user == self.ctx.author:
            return True
        await interaction.response.send_message("You are not allowed to interact with these buttons.", ephemeral=True)
        return False

    @ui.button(label="Accept", style=ButtonStyle.green)
    async def accept(self, interaction: Interaction, button: ui.Button):
        """Accept the generated image."""
        # Disable the buttons and update the message
        self.clear_items()
        await interaction.response.edit_message(content="", view=self)

        # Cancel the timeout since we've accepted
        self.stop()

    @ui.button(label="Try Again", style=ButtonStyle.primary)
    async def try_again(self, interaction: Interaction, button: ui.Button):
        """Restart generation with the same payload."""
        result = await self.interaction_check(interaction)
        if not result:
            return

        # Update the button to show "Drawing..." and disable all buttons
        button.label = self.LABEL_DRAWING
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(view=self)

        # Create a new task ID and retry image generation
        new_task_id = uuid.uuid4().hex
        await self.cog.retry_task(new_task_id, self)

    @ui.button(label="Delete", style=ButtonStyle.danger)
    async def delete(self, interaction: Interaction, button: ui.Button):
        """Delete the message."""
        result = await self.interaction_check(interaction)
        if not result:
            return

        # Delete the message
        await interaction.message.delete()

        # Cancel the timeout since we deleted the message
        self.stop()

    async def on_timeout(self):
        """Default action after timeout: Accept."""
        self.clear_items()
        await self.message.edit(content="", view=None)

class ImageGen(commands.Cog):
    """Cog for generating images using Stable Diffusion WebUI API with ImageGenerator."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_global = {
            "api_url": "http://127.0.0.1:7860",
        }
        default_channel = {
            "loras": "(squchan:0.6), (j.k.:0.4), (fizintine:0.5),"
        }
        self.config.register_global(**default_global)
        self.config.register_channel(**default_channel)

        # Initialize ImageGenerator without setting the API URL yet
        self.image_generator = ImageGenerator()

    @commands.Cog.listener()
    async def on_ready(self):
        # Set API URL when the bot is ready
        api_url = await self.config.api_url()
        self.image_generator.set_url(api_url)

    @commands.command()
    async def setlora(self, ctx, *, loras: str):
        """Set the default LoRAs for the current channel."""
        await self.config.channel(ctx.channel).loras.set(loras)
        await ctx.reply(f"LoRAs for this channel have been updated:\n{loras}", mention_author=True)

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
        seed = -1  # default to random
        strength = 0.5
        steps = 20

        for token in tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                key, value = key.strip(), value.strip()
                if key == "steps":
                    steps = int(value)
                elif key == "aspect":
                    if value == "portrait":
                        width, height = 832, 1216
                    elif value == "square":
                        width, height = 1024, 1024
                    elif value == "landscape":
                        width, height = 1216, 832
                elif key == "seed":
                    seed = int(value)
                elif key == "strength":
                    strength = float(value)
            elif token.startswith("-"):
                negative_prompt.append(token.lstrip("-").strip())
            else:
                positive_prompt.append(token)

        loras = await self.config.channel(ctx.channel).loras()
        is_nsfw = ctx.channel.is_nsfw()
        if not is_nsfw:
            positive_prompt.insert(0, "general")
            negative_prompt.insert(0, "nsfw, explicit")
        
        positive_prompt = f"{loras} masterpiece, best quality, amazing quality, " + ', '.join(positive_prompt)
        negative_prompt = "bad quality, worst quality, worst detail, sketch, censor, watermark, signature, " + ', '.join(negative_prompt)

        # High-Resolution settings for the first Image (txt2img)
        payload = {
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "seed": seed,
            "steps": steps,
            "width": width,
            "height": height,
            "cfg_scale": 4.5,
            "sampler_name": "Euler",
            "scheduler" : "Karras",
            "batch_size": 1,
            "n_iter": 1,
            "force_task_id": task_id
        }

        # Add the task to the ImageGenerator queue
        print(task_id, text)
        self.image_generator.new_task(task_id, payload, "txt2img")

        # Inform the user that the task has been submitted
        message = await ctx.reply(f"Generating...", mention_author=True)

        # Wait for the image generation result and fetch it
        async with ctx.typing():
            base64_image = None  # to track the last image's base64 string
            for _ in range(300):
                result = self.image_generator.callback(task_id)
                if result:
                    current_image_base64 = result["image"]
                    if current_image_base64 != base64_image:  # Check if new image base64 string exists
                        base64_image = current_image_base64
                        # Decode the base64 string only when sending the image
                        image_data = base64.b64decode(base64_image)
                        image = BytesIO(image_data)
                        image.seek(0)
                        
                        # Send the resized preview image
                        await message.edit(attachments=[File(fp=image, filename=f"{task_id}.png")])
    
                    if result["complete"]:
                        break
    
                await asyncio.sleep(1)  # Poll every second

        # Add interactive buttons for "Accept", "Try Again", and "Delete"
        view = AcceptRetryDeleteButtons(self, ctx, task_id, payload, message)
        await message.edit(content="Done!", view=view)

    async def retry_task(self, new_task_id, view):
        """Handles retrying the image generation with the same payload."""
        ctx, payload, message, = view.ctx, view.payload, view.message
        
        payload["force_task_id"] = new_task_id  # Set the new task ID for retry
        self.image_generator.new_task(new_task_id, payload, "txt2img")
        await message.edit(content="Generating...")
        # Wait for the new image to be generated
        base64_image = None  # to track the last image's base64 string
        while True:
            result = self.image_generator.callback(new_task_id)
            if result:
                current_image_base64 = result["image"]
                if current_image_base64 != base64_image:  # Check if new image base64 string exists
                    base64_image = current_image_base64
                    # Decode the base64 string only when sending the image
                    image_data = base64.b64decode(base64_image)
                    image = BytesIO(image_data)
                    image.seek(0)
                    await message.edit(attachments=[File(fp=image, filename=f"{new_task_id}.png")])

                if result["complete"]:
                    break

            await asyncio.sleep(0.5)  # Poll every second

        await message.edit(content="Done!")
        # Re-enable the buttons after retry
        view.children[1].label = view.LABEL_TRY_AGAIN
        for child in view.children:
            child.disabled = False

        await message.edit(view=view)

    @commands.command(name="tags")
    async def tags(self, ctx):
        """Process the attached image, send it to the tagger API, and return sorted tags."""
        
        # Check if the user attached an image
        if len(ctx.message.attachments) == 0:
            await ctx.reply("Please attach an image to use this command.", mention_author=True)
            return
        
        # Fetch the image from the attachment
        attachment = ctx.message.attachments[0]
        if not attachment.content_type.startswith('image/'):
            await ctx.reply("Please attach a valid image file.", mention_author=True)
            return
        
        # Download the image data
        image_data = await attachment.read()
        
        # Convert the image to base64
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        
        # Prepare the payload for the tagger API
        payload = {
            "image": image_base64,
            "model": "wd-v1-4-moat-tagger.v2",
            "threshold": 0.35,
            "queue": "",
            "name_in_queue": ""
        }
        
        # Send the request to the tagger API
        try:
            response = requests.post(f"{await self.config.api_url()}/tagger/v1/interrogate", json=payload, timeout=60)
            response.raise_for_status()
        except requests.RequestException as e:
            await ctx.reply(f"An error occurred while contacting the tagger API: {str(e)}", mention_author=True)
            return
        
        # Parse the JSON response
        try:
            data = response.json()
            tags = data.get("caption", {}).get("tag", {})
        except (ValueError, KeyError):
            await ctx.reply("Failed to parse the response from the tagger API.", mention_author=True)
            return
        
        # Sort the tags by score (descending order)
        sorted_tags = sorted(tags.items(), key=lambda x: x[1], reverse=True)
        
        # Generate a comma-separated string of tags
        tag_string = ", ".join([tag for tag, score in sorted_tags]).replace('_',' ')
        if len(tag_string) >= 3990:
            tag_string = tag_string[:3990]
            last_comma_index = tag_string.rfind(',')
            if last_comma_index != -1:
                tag_string = tag_string[:last_comma_index]
        
        # Reply with the formatted tags in a code block
        await ctx.reply(f"```\n{tag_string}\n```", mention_author=True)
    
    @commands.command(name="enhance")
    async def enhance(self, ctx, *, text: str):
        """Redraw an uploaded image using the Stable Diffusion img2img endpoint."""
        task_id = uuid.uuid4().hex
    
        # Check if the user attached an image
        if len(ctx.message.attachments) == 0:
            await ctx.reply("Please attach an image to use this command.", mention_author=True)
            return
    
        # Fetch the image from the attachment
        attachment = ctx.message.attachments[0]
        if not attachment.content_type.startswith('image/'):
            await ctx.reply("Please attach a valid image file.", mention_author=True)
            return
    
        # Download the image data
        image_data = await attachment.read()
    
        # Open the image to determine dimensions
        with BytesIO(image_data) as img_buffer:
            img = Image.open(img_buffer)
            orig_width, orig_height = img.size
    
        MAX_PIXELS = 2359296  # Max allowed total pixels
    
        def resize_image(width, height, max_pixels):
            """Resize the image while maintaining aspect ratio to not exceed max_pixels."""
            if width * height > max_pixels:
                scale_factor = (max_pixels / (width * height)) ** 0.5  # Square root to maintain aspect ratio
                new_width = int(width * scale_factor)
                new_height = int(height * scale_factor)
                return max(64, new_width // 32 * 32), max(64, new_height // 32 * 32)  # Ensure dimensions are multiples of 32
            return width, height
    
        # Apply resolution constraint
        new_width, new_height = resize_image(orig_width, orig_height, MAX_PIXELS)
    
        # Convert the image to base64
        image_base64 = base64.b64encode(image_data).decode("utf-8")
    
        # Prepare the payload for the tagger API to get tags
        tagger_payload = {
            "image": image_base64,
            "model": "wd-v1-4-moat-tagger.v2",
            "threshold": 0.35,
            "queue": "",
            "name_in_queue": ""
        }
    
        try:
            response = requests.post(f"{await self.config.api_url()}/tagger/v1/interrogate", json=tagger_payload, timeout=60)
            response.raise_for_status()
        except requests.RequestException as e:
            await ctx.reply(f"An error occurred while contacting the tagger API: {str(e)}", mention_author=True)
            return
    
        try:
            data = response.json()
            tags = data.get("caption", {}).get("tag", {})
        except (ValueError, KeyError):
            await ctx.reply("Failed to parse the response from the tagger API.", mention_author=True)
            return
    
        # Generate a comma-separated string of tags
        loras = await self.config.channel(ctx.channel).loras()
        is_nsfw = ctx.channel.is_nsfw()
        tag_list = [tag for tag, score in sorted(tags.items(), key=lambda x: x[1], reverse=True)]
        
        if not is_nsfw:
            tag_list.insert(0, "general")
            negative_prompt = "bad quality, worst quality, worst detail, sketch, censor, watermark, signature, nsfw, explicit"
        else:
            negative_prompt = "bad quality, worst quality, worst detail, sketch, censor, watermark, signature"
        
        positive_prompt = f"{loras} score_9, score_8_up, score_7_up, score_6_up, source_anime, " + ", ".join(tag_list).replace('_', ' ')
    
        payload = {
            "init_images": [image_base64],
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "seed": -1,
            "steps": 28,
            "width": new_width,
            "height": new_height,
            "cfg_scale": 2.5,
            "sampler_name": "Euler a",
            "scheduler": "SGM Uniform",
            "batch_size": 1,
            "n_iter": 1,
            "force_task_id": task_id,
            "denoising_strength": float(text) if text else 0.4
        }
    
        # Add the task to the ImageGenerator queue
        print(task_id, positive_prompt)
        self.image_generator.new_task(task_id, payload, "img2img")
    
        # Inform the user that the task has been submitted
        message = await ctx.reply(f"Generating...", mention_author=True)
    
        # Wait for the image generation result and fetch it
        async with ctx.typing():
            base64_image = None  # to track the last image's base64 string
            for _ in range(300):
                result = self.image_generator.callback(task_id)
                if result:
                    current_image_base64 = result["image"]
                    if current_image_base64 != base64_image:  # Check if new image base64 string exists
                        base64_image = current_image_base64
                        # Decode the base64 string only when sending the image
                        image_data = base64.b64decode(base64_image)
                        image = BytesIO(image_data)
                        image.seek(0)
    
                        # Send the resized preview image
                        await message.edit(attachments=[File(fp=image, filename=f"{task_id}.png")])
    
                    if result["complete"]:
                        break
    
                await asyncio.sleep(1)  # Poll every second
        await message.edit(content="Done!")
    

"""Cog for generating images using Stable Diffusion WebUI API."""

import asyncio
import base64
import uuid
from io import BytesIO

import requests
from PIL import Image
from discord import File
from redbot.core import commands
from redbot.core.config import Config

from .generator import ImageGenerator
from .ui_components import AcceptRetryDeleteButtons


class ImageGen(commands.Cog):
    """Cog for generating images using Stable Diffusion WebUI API with ImageGenerator."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=1234567890,
            force_registration=True
        )
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
        """Set API URL when the bot is ready"""
        api_url = await self.config.api_url()
        self.image_generator.set_url(api_url)

    @commands.command()
    async def setlora(self, ctx, *, loras: str):
        """Set the default LoRAs for the current channel."""
        await self.config.channel(ctx.channel).loras.set(loras)
        await ctx.reply(
            f"LoRAs for this channel have been updated:\n{loras}",
            mention_author=True
        )

    @commands.command()
    async def setapiurl(self, ctx, url: str):
        """Sets the API URL for the Stable Diffusion WebUI."""
        await self.config.api_url.set(url)
        self.image_generator.set_url(url)  # Update the ImageGenerator's URL
        await ctx.reply(
            f"API URL has been set to: {url}",
            mention_author=True
        )

    @commands.command()
    async def getapiurl(self, ctx):
        """Gets the current API URL."""
        api_url = await self.config.api_url()
        await ctx.reply(f"The current API URL is: {api_url}", mention_author=True)

    @commands.command(name="draw")
    async def draw(self, ctx, *, text: str): # pylint: disable=too-many-locals, too-many-statements
        """Generate images with the Stable Diffusion WebUI."""
        task_id = uuid.uuid4().hex
        tokens = [token.strip() for token in text.split(",")]

        prompt_config = {
            "positive": [],
            "negative": [],
            "width": 832,
            "height": 1216,
            "seed": -1,
            "steps": 20,
        }

        for token in tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                key, value = key.strip(), value.strip()
                match key:
                    case "steps":
                        prompt_config["steps"] = int(value)
                    case "aspect":
                        if value == "portrait":
                            prompt_config["width"], prompt_config["height"] = 832, 1216
                        elif value == "square":
                            prompt_config["width"], prompt_config["height"] = 1024, 1024
                        elif value == "landscape":
                            prompt_config["width"], prompt_config["height"] = 1216, 832
                    case "seed":
                        prompt_config["seed"] = int(value)
                    case _:  # Skip unknown keys
                        continue
            elif token.startswith("-"):
                prompt_config["negative"].append(token.lstrip("-").strip())
            else:
                prompt_config["positive"].append(token)

        loras = await self.config.channel(ctx.channel).loras()
        is_nsfw = ctx.channel.is_nsfw()
        if not is_nsfw:
            prompt_config["positive"].insert(0, "general")
            prompt_config["negative"].insert(0, "nsfw, explicit")

        positive_prompt = ", ".join([
            loras,
            "masterpiece",
            "best quality",
            "amazing quality",
            *prompt_config["positive"]
        ])

        negative_prompt = ", ".join([
            "bad quality",
            "worst quality",
            "worst detail",
            "sketch",
            "censor",
            "watermark",
            "signature",
            *prompt_config["negative"]
        ])

        payload = {
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "seed": prompt_config["seed"],
            "steps": prompt_config["steps"],
            "width": prompt_config["width"],
            "height": prompt_config["height"],
            "cfg_scale": 4.5,
            "sampler_name": "Euler",
            "scheduler": "Karras",
            "batch_size": 1,
            "n_iter": 1,
            "force_task_id": task_id
        }

        print(task_id, text)
        self.image_generator.new_task(task_id, payload, "txt2img")

        message = await ctx.reply("Generating...", mention_author=True)

        async with ctx.typing():
            base64_image = None
            for _ in range(300):
                result = self.image_generator.callback(task_id)
                if result:
                    current_image_base64 = result["image"]
                    if current_image_base64 != base64_image:
                        base64_image = current_image_base64
                        image_data = base64.b64decode(base64_image)
                        image = BytesIO(image_data)
                        image.seek(0)
                        await message.edit(
                            attachments=[
                                File(fp=image, filename=f"{task_id}.png")
                            ]
                        )
                    if result["complete"]:
                        break
                await asyncio.sleep(1)

        view = AcceptRetryDeleteButtons(self, ctx, task_id, payload, message)
        await message.edit(content="Done!", view=view)


    async def retry_task(self, new_task_id, view):
        """Handles retrying the image generation with the same payload."""
        _, payload, message, = view.ctx, view.payload, view.message

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
                    await message.edit(
                        attachments=[
                            File(
                                fp=image,
                                filename=f"{new_task_id}.png"
                            )
                        ]
                    )

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
            await ctx.reply(
                "Please attach an image to use this command.",
                mention_author=True
            )
            return

        # Fetch the image from the attachment
        attachment = ctx.message.attachments[0]
        if not attachment.content_type.startswith('image/'):
            await ctx.reply(
                "Please attach a valid image file.",
                mention_author=True
            )
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
            response = requests.post(
                f"{await self.config.api_url()}/tagger/v1/interrogate",
                json=payload,
                timeout=60
            )
            response.raise_for_status()
        except requests.RequestException as e:
            await ctx.reply(
                f"An error occurred while contacting the tagger API: {str(e)}",
                mention_author=True
            )
            return

        # Parse the JSON response
        try:
            data = response.json()
            tags = data.get("caption", {}).get("tag", {})
        except (ValueError, KeyError):
            await ctx.reply(
                "Failed to parse the response from the tagger API.",
                mention_author=True
            )
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
        await ctx.reply(
            f"```\n{tag_string}\n```",
            mention_author=True
        )

    @commands.command(name="enhance")
    async def enhance(self, ctx, *, text: str):  # pylint: disable=too-many-locals, too-many-statements
        """Redraw an uploaded image using the Stable Diffusion img2img endpoint."""
        task_id = uuid.uuid4().hex

        if not ctx.message.attachments:
            await ctx.reply("Please attach an image to use this command.", mention_author=True)
            return

        attachment = ctx.message.attachments[0]
        if not attachment.content_type.startswith("image/"):
            await ctx.reply("Please attach a valid image file.", mention_author=True)
            return

        image_data = await attachment.read()
        with BytesIO(image_data) as img_buffer:
            img = Image.open(img_buffer)
            orig_width, orig_height = img.size

        MIN_PIXELS = 1011712
        MAX_PIXELS = 2359296

        def resize_image(width, height, min_pixels, max_pixels):
            """Resize the image to fit within pixel bounds while maintaining aspect ratio."""
            original_pixels = width * height

            if original_pixels > max_pixels:
                scale = (max_pixels / original_pixels) ** 0.5
            elif original_pixels < min_pixels:
                scale = (min_pixels / original_pixels) ** 0.5
            else:
                return width, height

            new_w = max(64, int(width * scale) // 32 * 32)
            new_h = max(64, int(height * scale) // 32 * 32)
            return new_w, new_h

        new_width, new_height = resize_image(orig_width, orig_height, MIN_PIXELS, MAX_PIXELS)
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        tagger_payload = {
            "image": image_base64,
            "model": "wd-v1-4-moat-tagger.v2",
            "threshold": 0.35,
            "queue": "",
            "name_in_queue": ""
        }

        try:
            tagger_url = f"{await self.config.api_url()}/tagger/v1/interrogate"
            response = requests.post(tagger_url, json=tagger_payload, timeout=60)
            response.raise_for_status()
        except requests.RequestException as e:
            await ctx.reply(
                f"An error occurred while contacting the tagger API: {str(e)}",
                mention_author=True
            )
            return

        try:
            data = response.json()
            tags = data.get("caption", {}).get("tag", {})
        except (ValueError, KeyError):
            await ctx.reply(
                "Failed to parse the response from the tagger API.",
                mention_author=True
            )
            return

        loras = await self.config.channel(ctx.channel).loras()
        is_nsfw = ctx.channel.is_nsfw()
        tag_list = [
            tag for tag, score in sorted(tags.items(), key=lambda x: x[1], reverse=True)
        ]

        negative_prompt_tags = [
            "bad quality", "worst quality", "worst detail",
            "sketch", "censor", "watermark", "signature"
        ]
        if not is_nsfw:
            tag_list.insert(0, "general")
            negative_prompt_tags += ["nsfw", "explicit"]

        positive_prompt = ", ".join([
            loras,
            "masterpiece",
            "best quality",
            "amazing quality",
            *[tag.replace("_", " ") for tag in tag_list]
        ])
        negative_prompt = ", ".join(negative_prompt_tags)

        payload = {
            "init_images": [image_base64],
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "seed": -1,
            "steps": 20,
            "width": new_width,
            "height": new_height,
            "cfg_scale": 4.5,
            "sampler_name": "Euler a",
            "scheduler": "Karras",
            "batch_size": 1,
            "n_iter": 1,
            "force_task_id": task_id,
            "denoising_strength": float(text) if text else 0.4
        }

        print(task_id, positive_prompt)
        self.image_generator.new_task(task_id, payload, "img2img")
        message = await ctx.reply("Generating...", mention_author=True)

        async with ctx.typing():
            base64_image = None
            for _ in range(300):
                result = self.image_generator.callback(task_id)
                if result:
                    current_image_base64 = result["image"]
                    if current_image_base64 != base64_image:
                        base64_image = current_image_base64
                        decoded = base64.b64decode(base64_image)
                        image = BytesIO(decoded)
                        image.seek(0)
                        await message.edit(
                            attachments=[File(fp=image, filename=f"{task_id}.png")]
                        )
                    if result["complete"]:
                        break
                await asyncio.sleep(1)

        await message.edit(content="Done!")

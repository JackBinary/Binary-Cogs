import base64
from io import BytesIO
import json
import uuid
import requests
import discord
import os
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config


class ImageGen(commands.Cog):
    """
    Generate images in Discord!
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=133041100356059137,
            force_registration=True,
        )
        self.config_dir = ".imagegen"
        self.default_negative = "source_furry, source_pony, cartoon, 3d, realistic, monochrome, text, watermark, censored"
        self.default_positive = "score_9, score_8_up, score_7_up, score_6_up, source_anime"

    def get_channel_config_path(self, channel_id):
        return os.path.join(self.config_dir, f"{channel_id}.json")

    def load_channel_config(self, channel_id):
        config_path = self.get_channel_config_path(channel_id)
        if os.path.exists(config_path):
            with open(config_path, "r") as file:
                return json.load(file)
        return {"positive": "", "negative": ""}

    def save_channel_config(self, channel_id, config):
        config_path = self.get_channel_config_path(channel_id)
        with open(config_path, "w") as file:
            json.dump(config, file, indent=4)

    async def generate_image(self, ctx, payload, endpoint):
        async with ctx.typing():
            response = requests.post(url=f"http://192.168.1.177:7860/{endpoint}", json=payload).json()
            image = BytesIO(base64.b64decode(response['images'][0]))
            image.seek(0)
        return image

    @commands.command(name="draw")
    async def draw(self, ctx, *, text: str):
        """
        Generate images in Discord!
        """
        tokens = [token.strip() for token in text.split(",")]
        positive_prompt = []
        negative_prompt = []
        width, height = 832, 1248  # Default to portrait
        seed = -1  # default to random
        strength = 0.5

        for token in tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                key, value = key.strip(), value.strip()
                if key == "ratio":
                    if value == "portrait":
                        width, height = 832, 1248
                    elif value == "square":
                        width, height = 1024, 1024
                    elif value == "landscape":
                        width, height = 1248, 832
                if key == "seed":
                    seed = int(value)
                if key == "strength":
                    if value == "1":
                        strength = 0.2
                    elif value == "2":
                        strength = 0.4
                    elif value == "3":
                        strength = 0.5
                    elif value == "4":
                        strength = 0.6
                    elif value == "5":
                        strength = 0.7
            elif token.startswith("-"):
                negative_prompt.append(token.lstrip("-").strip())
            else:
                positive_prompt.append(token)

        try:
            channel_config = self.load_channel_config(ctx.channel.id)
            positive_prompt = f"{self.default_positive}, {channel_config['positive']}, {', '.join(positive_prompt)}"
            negative_prompt = f"{self.default_negative}, {channel_config['negative']}, {', '.join(negative_prompt)}"
        except Exception:
            positive_prompt = f"{self.default_positive}, <lora:Fizintine_Style:0.6> <lora:JdotKdot_PDXL-v1:0.7>, {', '.join(positive_prompt)}"
            negative_prompt = f"{self.default_negative}, <lora:Fizintine_Style:0.6> <lora:JdotKdot_PDXL-v1:0.7>, {', '.join(negative_prompt)}"

        if ctx.message.attachments:
            attachment = BytesIO()
            await ctx.message.attachments[0].save(attachment)
            attachment.seek(0)
            init_image = base64.b64encode(attachment.getvalue()).decode("utf-8")

            payload = {
                "prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "seed": seed,
                "steps": 8,
                "width": width,
                "height": height,
                "cfg_scale": 2,
                "sampler_name": "DPM++ 2M SDE",
                "scheduler": "SGM Uniform",
                "n_iter": 1,
                "batch_size": 1,
                "init_images": [init_image],
                "denoising_strength": strength
            }
            endpoint = 'sdapi/v1/img2img'

        else:
            payload = {
                "prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "seed": seed,
                "steps": 8,
                "width": width,
                "height": height,
                "cfg_scale": 2,
                "sampler_name": "DPM++ 2M SDE",
                "scheduler": "SGM Uniform",
                "n_iter": 1,
                "batch_size": 1,
            }
            endpoint = 'sdapi/v1/txt2img'

        image = await self.generate_image(ctx, payload, endpoint)

        view = ImageGenView(self, ctx, payload, endpoint, ctx.author.id, ctx.author.name)
        message = await ctx.send(file=discord.File(fp=image, filename=f"{uuid.uuid4().hex}.png"), view=view)
        view.set_image_message(message)

    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    @commands.command(name="drawset")
    async def drawset(self, ctx, mode: str, *, prompt: str):
        """
        Configure the channel positive and negative prompts.
        Usage: [p]drawset positive <positive prompt>
               [p]drawset negative <negative prompt>
        """
        mode = mode.lower()
        if mode not in ["positive", "negative"]:
            await ctx.send("Invalid mode! Use 'positive' or 'negative'.")
            return

        channel_config = self.load_channel_config(ctx.channel.id)
        channel_config[mode] = prompt
        self.save_channel_config(ctx.channel.id, channel_config)
        await ctx.send(f"{mode.capitalize()} prompt set to: {prompt}")


class ImageGenView(discord.ui.View):
    LABEL_ACCEPT = "Accept"
    LABEL_DELETE = "Delete"
    LABEL_TRY_AGAIN = "Try Again"
    LABEL_DRAWING = "Drawing.."

    def __init__(self, cog, ctx, payload, endpoint, requesting_user_id, requesting_user_name):
        super().__init__(timeout=120.0)
        self.cog = cog
        self.ctx = ctx
        self.payload = payload
        self.endpoint = endpoint
        self.requesting_user_id = requesting_user_id
        self.requesting_user_name = requesting_user_name
        self.photo_accepted = False
        self.image_message = None

        self.btn_try_again = discord.ui.Button(label=self.LABEL_TRY_AGAIN, style=discord.ButtonStyle.primary, row=1)
        self.btn_try_again.callback = self.on_try_again
        self.add_item(self.btn_try_again)

        self.btn_accept = discord.ui.Button(label=self.LABEL_ACCEPT, style=discord.ButtonStyle.success, row=1)
        self.btn_accept.callback = self.on_accept
        self.add_item(self.btn_accept)

        self.btn_delete = discord.ui.Button(label=self.LABEL_DELETE, style=discord.ButtonStyle.danger, row=1)
        self.btn_delete.callback = self.on_delete
        self.add_item(self.btn_delete)

    def set_image_message(self, image_message: discord.Message):
        self.image_message = image_message

    def get_image_message(self) -> discord.Message:
        if self.image_message is None:
            raise ValueError("image_message is None")
        return self.image_message

    async def on_try_again(self, interaction: discord.Interaction):
        if interaction.user.id != self.requesting_user_id:
            await interaction.response.send_message("You are not authorized to use this button.", ephemeral=True)
            return

        self.btn_try_again.label = self.LABEL_DRAWING
        self.btn_try_again.disabled = True
        self.btn_accept.disabled = True
        self.btn_delete.disabled = True

        await interaction.response.edit_message(view=self)
        image = await self.cog.generate_image(self.ctx, self.payload, self.endpoint)

        self.btn_try_again.label = self.LABEL_TRY_AGAIN
        self.btn_try_again.disabled = False
        self.btn_accept.disabled = False
        self.btn_delete.disabled = False

        await self.get_image_message().edit(attachments=[discord.File(fp=image, filename=f"{uuid.uuid4().hex}.png")], view=self)

    async def on_accept(self, interaction: discord.Interaction):
        if interaction.user.id != self.requesting_user_id:
            await interaction.response.send_message("You are not authorized to use this button.", ephemeral=True)
            return

        self.photo_accepted = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

    async def on_delete(self, interaction: discord.Interaction):
        if interaction.user.id != self.requesting_user_id:
            await interaction.response.send_message("You are not authorized to use this button.", ephemeral=True)
            return

        await interaction.message.delete()

    async def on_timeout(self):
        if not self.photo_accepted:
            await self.get_image_message().delete()

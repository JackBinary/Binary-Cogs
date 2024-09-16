import threading
import asyncio
import base64
from io import BytesIO
import requests
from queue import Queue
import time
import uuid
from redbot.core import commands, Config
from discord import File

class ImageGenerator:
    """Image Generator Object that handles image generation in a separate thread."""

    def __init__(self, config):
        self.config = config
        self.task_queue = Queue()
        self.results = {}
        self.lock = threading.Lock()  # For thread-safe access to results
        self.running = True
        # Start the background thread
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        print("[ImageGenerator] Initialized and worker thread started.")

    def _worker(self):
        """Background worker that processes image generation tasks."""
        print("[ImageGenerator] Worker started.")
        while self.running:
            try:
                print("[ImageGenerator] Waiting for task...")
                task_id, payload, api_url = self.task_queue.get(timeout=1)
                print(f"[ImageGenerator] Task received. Task ID: {task_id}, API URL: {api_url}")
                self._generate_image(task_id, payload, api_url)
            except Exception as e:
                # If the queue is empty or any other issue occurs
                print(f"[ImageGenerator] Exception in worker: {str(e)}")
                pass

    def post_task(self, payload, api_url):
        """Posts a new image generation task and returns a unique task_id."""
        task_id = uuid.uuid4().hex
        self.task_queue.put((task_id, payload, api_url))
        print(f"[ImageGenerator] Task posted with Task ID: {task_id}")
        return task_id

    def _generate_image(self, task_id, payload, api_url):
        """Internal method to generate images."""
        try:
            print(f"[ImageGenerator] Sending request to {api_url}/sdapi/v1/txt2img with payload: {payload}")
            response = requests.post(f"{api_url}/sdapi/v1/txt2img", json=payload, timeout=30)
            response.raise_for_status()
            response_json = response.json()
            print(f"[ImageGenerator] Response received for Task ID: {task_id}")

            if 'images' in response_json and response_json['images']:
                image_data = base64.b64decode(response_json['images'][0])
                image = BytesIO(image_data)
                image.seek(0)
                print(f"[ImageGenerator] Image decoded for Task ID: {task_id}")

                with self.lock:
                    # Save the final image in results
                    self.results[task_id] = {
                        "is_final": True,
                        "image": image
                    }
                    print(f"[ImageGenerator] Image stored for Task ID: {task_id}")
        except Exception as e:
            # Handle error and return
            print(f"[ImageGenerator] Error during image generation for Task ID: {task_id} - {str(e)}")
            with self.lock:
                self.results[task_id] = {"error": str(e)}

    def get_result(self, task_id):
        """Fetch the result (preview or final) for a given task_id."""
        with self.lock:
            result = self.results.get(task_id, None)
            print(f"[ImageGenerator] Checking result for Task ID: {task_id}, Result: {result}")
            if result:
                return result
            return {"is_final": False, "image": None}

    def stop(self):
        """Gracefully stop the image generator."""
        print("[ImageGenerator] Stopping worker thread.")
        self.running = False
        self.worker_thread.join()


class ImageGen(commands.Cog):
    """Cog for generating images using ImageGenerator in a separate thread."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_global = {"api_url": "http://127.0.0.1:7860"}
        self.config.register_global(**default_global)
        self.generator = ImageGenerator(self.config)
        print("[ImageGenCog] Initialized ImageGenCog.")

    @commands.command()
    async def setapiurl(self, ctx, url: str):
        """Sets the API URL for the Stable Diffusion WebUI."""
        print(f"[ImageGenCog] Setting API URL to: {url}")
        await self.config.api_url.set(url)
        await ctx.reply(f"API URL has been set to: {url}", mention_author=True)

    @commands.command()
    async def getapiurl(self, ctx):
        """Gets the current API URL."""
        api_url = await self.config.api_url()
        print(f"[ImageGenCog] Getting API URL: {api_url}")
        await ctx.reply(f"The current API URL is: {api_url}", mention_author=True)

    @commands.command()
    async def draw(self, ctx, *, text: str):
        """
        Generate images and provide live preview.
        """
        print("[ImageGenCog] Draw command invoked.")
        tokens = [token.strip() for token in text.split(",")]
        positive_prompt = []
        negative_prompt = []
        # Default to portrait resolution
        width, height = 832, 1216
        seed = -1  # default to random
        strength = 0.5

        # Process tokens into prompt and other settings
        for token in tokens:
            print(f"[ImageGenCog] Processing token: {token}")
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
                print(f"[ImageGenCog] Added to negative prompt: {token}")
            else:
                positive_prompt.append(token)
                print(f"[ImageGenCog] Added to positive prompt: {token}")

        positive_prompt = ', '.join(positive_prompt)
        negative_prompt = ', '.join(negative_prompt)

        # High-Resolution settings for the first Image (txt2img)
        payload = {
            "enable_hr": True,
            "denoising_strength": 0.7,
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "seed": seed,
            "steps": 8,
            "width": width,
            "height": height,
            "cfg_scale": 2.5,
            "sampler_name": "Euler a",
        }

        # Retrieve dynamic API URL from config
        api_url = await self.config.api_url()
        print(f"[ImageGenCog] API URL for request: {api_url}")

        # Post the task and get the task_id
        task_id = self.generator.post_task(payload, api_url)
        print(f"[ImageGenCog] Task posted with Task ID: {task_id}")

        await ctx.reply(f"Image generation started with Task ID: {task_id}")

        # Start monitoring the result
        threading.Thread(target=self._monitor_task, args=(ctx, task_id), daemon=True).start()

    def _monitor_task(self, ctx, task_id):
        """Monitor the image generation task and send the image when ready."""
        print(f"[ImageGenCog] Monitoring Task ID: {task_id}")
        while True:
            result = self.generator.get_result(task_id)

            if result.get("error"):
                # Send the error if any occurred
                print(f"[ImageGenCog] Error in Task ID: {task_id} - {result['error']}")
                asyncio.run_coroutine_threadsafe(
                    ctx.reply(f"Error: {result['error']}"), self.bot.loop
                )
                break

            if result["image"]:
                # Send the final image
                print(f"[ImageGenCog] Final image ready for Task ID: {task_id}")
                image = result["image"]
                asyncio.run_coroutine_threadsafe(
                    ctx.reply(file=File(fp=image, filename=f"{task_id}.png")), self.bot.loop
                )
                break

            time.sleep(1)  # Check every second for a result

    def cog_unload(self):
        """Ensure the generator thread is stopped when the cog is unloaded."""
        print("[ImageGenCog] Unloading cog and stopping ImageGenerator.")
        self.generator.stop()

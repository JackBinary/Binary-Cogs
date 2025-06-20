"""Handles image generation via Stable Diffusion WebUI API."""

import threading
from time import sleep
import requests


class ImageGenerator:
    """Manages image generation and live preview tracking for Stable Diffusion WebUI."""

    def __init__(self):
        self.api_url = "http://127.0.0.1:7860"
        self.txt2img = "sdapi/v1/txt2img"
        self.img2img = "sdapi/v1/img2img"
        self.progress = "internal/progress"
        self.tasks = []
        self.in_progress = []
        self.images = {}

        threading.Thread(target=self.generator, daemon=True).start()
        threading.Thread(target=self.get_progress, daemon=True).start()

    def set_url(self, url: str):
        """Set the base API URL for image generation."""
        self.api_url = url

    def new_task(self, task_id: str, payload: dict, task_type: str):
        """Queue a new image generation task."""
        self.tasks.append({"id": task_id, "payload": payload, "type": task_type})

    def callback(self, task_id: str):
        """Return image data for a completed or in-progress task."""
        return self.images.get(task_id, False)

    def generator(self):
        """Continuously processes queued image generation tasks using the WebUI API."""
        while True:
            if self.tasks:
                task = self.tasks.pop(0)
                task_id = task["id"]
                payload = task["payload"]
                task_type = task["type"]
                self.in_progress.append(task_id)

                try:
                    endpoint = self.img2img if task_type == "img2img" else self.txt2img
                    response = requests.post(
                        f"{self.api_url}/{endpoint}",
                        json=payload,
                        timeout=300
                    )
                    response.raise_for_status()
                    response_json = response.json()

                    if "images" in response_json:
                        image_base64 = response_json["images"][0]
                        self.images[task_id] = {
                            "image": image_base64,
                            "complete": True
                        }
                except requests.RequestException:
                    # Could log the error or track failure state here
                    pass
                finally:
                    if task_id in self.in_progress:
                        self.in_progress.remove(task_id)

            sleep(0.5)

    def get_progress(self):
        """Continuously fetches live preview images for in-progress tasks."""
        while True:
            for task_id in self.in_progress:
                try:
                    payload = {
                        "id_task": task_id,
                        "id_live_preview": -1,
                        "live_preview": True
                    }
                    response = requests.post(
                        f"{self.api_url}/{self.progress}",
                        json=payload,
                        timeout=60
                    )
                    response.raise_for_status()
                    response_json = response.json()

                    if "live_preview" in response_json:
                        image_base64 = response_json["live_preview"].split(",")[1]
                        self.images[task_id] = {
                            "image": image_base64,
                            "complete": False
                        }
                except (requests.RequestException, KeyError, IndexError, AttributeError):
                    continue

            sleep(0.5)

    def remove_task(self, task_id: str):
        """Remove a task from the image cache after it's been handled."""
        self.images.pop(task_id, None)

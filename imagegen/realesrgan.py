import gc  # Import for garbage collection

class RealESRGANAnimeUpscaler:
    def __init__(self, outscale=4, gpu_id=None):
        """Initialize the RealESRGANAnimeUpscaler with default settings for RealESRGAN_x4plus_anime_6B model."""
        self.model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=6, num_grow_ch=32, scale=4)
        self.netscale = 4
        self.outscale = outscale
        self.gpu_id = gpu_id
        self.model_path = self._download_model()

        # Initialize the RealESRGANer
        self.upsampler = RealESRGANer(
            scale=self.netscale,
            model_path=self.model_path,
            model=self.model,
            tile=1024,  # No tiling by default
            tile_pad=32,
            pre_pad=0,
            half=True,  # Use fp16 by default for better performance
            gpu_id=self.gpu_id
        )

    def _download_model(self):
        """Download the RealESRGAN_x4plus_anime_6B model weights if not already present."""
        model_url = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth'
        model_path = os.path.join('weights', 'RealESRGAN_x4plus_anime_6B.pth')
        if not os.path.isfile(model_path):
            model_path = load_file_from_url(url=model_url, model_dir='weights', progress=True, file_name=None)
        return model_path

    def enhance_image(self, input_image: BytesIO, ext: str = 'png') -> BytesIO:
        """
        Enhance an image from a BytesIO object and return the result as a BytesIO object.
        
        Args:
            input_image (BytesIO): The input image as a BytesIO stream.
            ext (str): The image format to return, e.g., 'png', 'jpg'.

        Returns:
            BytesIO: The enhanced image as a BytesIO stream.
        """
        # Load the image from the BytesIO object
        img = Image.open(input_image)
        img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)  # Convert to BGR for OpenCV compatibility

        # Enhance the image
        try:
            output, _ = self.upsampler.enhance(img, outscale=self.outscale)
        except RuntimeError as error:
            print(f'Error: {error}')
            raise
        finally:
            # Free GPU memory
            torch.cuda.empty_cache()  # Clear unused memory
            del img, output  # Manually delete objects
            gc.collect()  # Run garbage collection to free up memory

        # Convert the output back to BytesIO
        output_img = Image.fromarray(cv2.cvtColor(output, cv2.COLOR_BGR2RGB))  # Convert back to RGB
        output_bytes = BytesIO()
        output_img.save(output_bytes, format=ext)
        output_bytes.seek(0)  # Reset pointer to the start of the BytesIO object

        return output_bytes

    def __del__(self):
        """Ensure that the upsampler and model are cleaned up properly."""
        del self.upsampler
        torch.cuda.empty_cache()  # Clear GPU memory
        gc.collect()  # Clean up any lingering objects

# Example usage of the class:
# from your_module import RealESRGANAnimeUpscaler
# upscaler = RealESRGANAnimeUpscaler()
# with open("your_input_image.png", "rb") as img_file:
#     input_bytes = BytesIO(img_file.read())
# result = upscaler.enhance_image(input_bytes, ext="png")
# with open("output_image.png", "wb") as out_file:
#     out_file.write(result.getbuffer())

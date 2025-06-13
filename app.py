import os
import io
import time
import base64
import uuid
import PIL.Image
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# Google Cloud & GenAI specific imports
from google.cloud import storage
from google.api_core import exceptions as google_exceptions
from google import genai
from google.genai import types

# --- Configuration & Initialization ---
load_dotenv('.env')

app = Flask(__name__)

LOCAL_IMAGE_DIR = os.path.join('static', 'generated_images')
os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)

# Gemini Image Generation Client (using your existing setup)
API_KEY = os.environ.get("GOOGLE_API_KEY")
MODEL_ID_IMAGE = 'gemini-2.0-flash-exp-image-generation'

# Veo Video Generation Client (NEW)
PROJECT_ID = os.environ.get("PROJECT_ID")
LOCATION = os.environ.get("GOOGLE_CLOUD_REGION", "us-central1")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
MODEL_ID_VIDEO = "veo-3.0-generate-preview" # Your Veo model ID

if not all([API_KEY, PROJECT_ID, GCS_BUCKET_NAME, LOCATION]):
    raise RuntimeError("Missing required environment variables. Check your .env file.")

# Initialize clients
try:
    # Client for Gemini Image Generation
    gemini_image_client = genai.Client(api_key=API_KEY)
    print(f"Gemini Image Client initialized successfully for model: {MODEL_ID_IMAGE}")

    # Client for Veo Video Generation (Vertex AI)
    veo_video_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    print(f"Veo Video Client (Vertex AI) initialized successfully for project: {PROJECT_ID}")

    # Client for Google Cloud Storage
    gcs_client = storage.Client(project=PROJECT_ID)
    print("Google Cloud Storage Client initialized successfully.")

except Exception as e:
    print(f"Error during client initialization: {e}")
    gemini_image_client = veo_video_client = gcs_client = None


# --- Helper Function to Upload to GCS (NEW) ---
def upload_bytes_to_gcs(image_bytes: bytes, bucket_name: str, destination_blob_name: str) -> str:
    """Uploads image bytes to GCS and returns the GCS URI."""
    if not gcs_client:
        raise ConnectionError("GCS client is not initialized.")
    
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_string(image_bytes, content_type='image/png')
    
    gcs_uri = f"gs://{bucket_name}/{destination_blob_name}"
    print(f"Image successfully uploaded to {gcs_uri}")
    return gcs_uri


# --- Main Routes ---
@app.route('/')
def index():
    """Renders the main HTML page."""
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_video_from_sketch():
    """Full pipeline: sketch -> image -> video."""
    if not all([gemini_image_client, veo_video_client, gcs_client]):
        return jsonify({"error": "A server-side client is not initialized. Check server logs."}), 500

    if not request.json or 'image_data' not in request.json:
        return jsonify({"error": "Missing image_data in request"}), 400

    base64_image_data = request.json['image_data']
    user_prompt = request.json.get('prompt', '').strip()

    # --- Step 1: Generate Image with Gemini ---
    try:
        print("--- Step 1: Generating image from sketch with Gemini ---")
        if ',' in base64_image_data:
            base64_data = base64_image_data.split(',', 1)[1]
        else:
            base64_data = base64_image_data
        
        image_bytes = base64.b64decode(base64_data)
        sketch_pil_image = PIL.Image.open(io.BytesIO(image_bytes))

        # default_prompt = "Create a photorealistic image based on this sketch. Focus on realistic lighting, textures, and shadows to make it look like a photograph taken with a professional DSLR camera."
        default_prompt = "Convert this sketch into a photorealistic image as if it were taken from a real DSLR camera. The elements and objects should look real."
        #prompt_text = f"{default_prompt} {user_prompt}" if user_prompt else default_prompt

        response = gemini_image_client.models.generate_content(
            model=MODEL_ID_IMAGE,
            contents=[default_prompt, sketch_pil_image],
            config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE'])
        )

        if not response.candidates:
            raise ValueError("Gemini image generation returned no candidates.")

        generated_image_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith('image/'):
                generated_image_bytes = part.inline_data.data
                break
        
        if not generated_image_bytes:
            raise ValueError("Gemini did not return an image in the response.")
        
        print("Image generated successfully.")

        try:
            # Use a unique filename to prevent overwrites
            local_filename = f"generated-image-{uuid.uuid4()}.png"
            local_image_path = os.path.join(LOCAL_IMAGE_DIR, local_filename)
            # Write the bytes to a file in binary mode ('wb')
            with open(local_image_path, "wb") as f:
                f.write(generated_image_bytes)
            print(f"Image also saved locally to: {local_image_path}")
        except Exception as e:
            # This is not a critical error, so we just print a warning and continue.
            print(f"[Warning] Could not save image locally: {e}")

    except Exception as e:
        print(f"Error during Gemini image generation: {e}")
        return jsonify({"error": f"Failed to generate image: {e}"}), 500

    # --- Step 2 & 3: Upload Image to GCS and Generate Video with Veo ---
    try:
        print("\n--- Step 2: Uploading generated image to GCS ---")
        unique_id = uuid.uuid4()
        image_blob_name = f"images/generated-image-{unique_id}.png"
        output_gcs_prefix = f"gs://{GCS_BUCKET_NAME}/videos/" # Folder for video outputs

        image_gcs_uri = upload_bytes_to_gcs(generated_image_bytes, GCS_BUCKET_NAME, image_blob_name)
        
        print("\n--- Step 3: Calling Veo to generate video ---")
        default_video_prompt = "Animate this image. Add subtle, cinematic motion."
        video_prompt = f"{user_prompt}" if user_prompt else default_video_prompt
        print(video_prompt)
        
        operation = veo_video_client.models.generate_videos(
            model=MODEL_ID_VIDEO,
            prompt=video_prompt,
            image=types.Image(gcs_uri=image_gcs_uri, mime_type="image/png"),
            config=types.GenerateVideosConfig(
                aspect_ratio="16:9", 
                output_gcs_uri=output_gcs_prefix,
                duration_seconds=8,
                person_generation="allow_adult",
                enhance_prompt=True,
                generate_audio=True, # Keep it simple for now
            ),
        )

       
        # WARNING: This is a synchronous poll, which will block the server thread.
        # For production, consider an asynchronous pattern (e.g., websockets or long polling).
        timeout_seconds = 300 # 5 minutes
        start_time = time.time()
        while not operation.done:
            if time.time() - start_time > timeout_seconds:
                raise TimeoutError("Video generation timed out.")
            time.sleep(15)
            # You must get the operation object again to refresh its status
            operation = veo_video_client.operations.get(operation)
            print(operation)

        print("Video generation operation complete.")
        
        if not operation.response or not operation.result.generated_videos:
            raise ValueError("Veo operation completed but returned no video.")

        video_gcs_uri = operation.result.generated_videos[0].video.uri
        print(f"Video saved to GCS at: {video_gcs_uri}")
        
        # Convert gs:// URI to public https:// URL
        video_blob_name = video_gcs_uri.replace(f"gs://{GCS_BUCKET_NAME}/", "")

        public_video_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{video_blob_name}"
        print(f"Video generated successfully. Public URL: {public_video_url}")

        return jsonify({"generated_video_url": public_video_url})

    except Exception as e:
        print(f"An error occurred during video generation: {e}")
        return jsonify({"error": f"Failed to generate video: {e}"}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
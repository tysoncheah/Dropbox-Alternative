import os
import tempfile
import subprocess
import mimetypes
from google.cloud import storage
from PIL import Image
import functions_framework
from cloudevents.http import CloudEvent

# Initialize the GCS client
storage_client = storage.Client()

# Target bucket for downsized previews (passed via Environment Variables)
PREVIEW_BUCKET_NAME = os.environ.get("PREVIEW_BUCKET")

@functions_framework.cloud_event
def process_av_upload(cloud_event: CloudEvent) -> None:
    """
    Gen 2 Cloud Event handler triggered by Eventarc / GCS bucket updates.
    """
    # Unpack the Eventarc payload data
    data = cloud_event.data
    bucket_name = data.get('bucket')
    file_name = data.get('name')  # e.g., "movies/2026/family/trip.mp4"
    
    # Safety checks
    if not bucket_name or not file_name:
        print("Invalid event payload: missing bucket or file name.")
        return
        
    if bucket_name == PREVIEW_BUCKET_NAME:
        print("File is already in the preview bucket. Skipping.")
        return

    # Skip directory placeholder objects (0-byte folder markers)
    if file_name.endswith('/'):
        print(f"Skipping folder placeholder look: {file_name}")
        return

    # Determine file type
    mime_type, _ = mimetypes.guess_type(file_name)
    if not mime_type:
        print(f"Could not determine MIME type for {file_name}. Skipping.")
        return

    print(f"Processing Gen 2 Event for: {file_name} (Type: {mime_type})")

    # Extract the directory tree paths and pure filename to keep folder hierarchy
    dir_name, base_name = os.path.split(file_name)

    source_bucket = storage_client.bucket(bucket_name)
    source_blob = source_bucket.blob(file_name)
    dest_bucket = storage_client.bucket(PREVIEW_BUCKET_NAME)

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, base_name)
        
        print(f"Downloading {file_name} from {bucket_name} locally...")
        source_blob.download_to_filename(input_path)

        # ---------------- IMAGES PROCESSING ----------------
        if mime_type.startswith('image/'):
            output_path = os.path.join(tmpdir, f"preview_{base_name}")
            downsize_image(input_path, output_path)
            
            # Reconstruct same folder tree in the destination preview bucket
            preview_blob_name = os.path.join(dir_name, f"preview_{base_name}") if dir_name else f"preview_{base_name}"
            dest_blob = dest_bucket.blob(preview_blob_name)
            
            print(f"Uploading optimized image to {PREVIEW_BUCKET_NAME} as {preview_blob_name}...")
            dest_blob.upload_from_filename(output_path, content_type=mime_type)

        # ---------------- VIDEOS PROCESSING ----------------
        elif mime_type.startswith('video/'):
            raw_name = os.path.splitext(base_name)[0]
            output_filename = f"preview_{raw_name}.mp4" # Force web-standard container
            output_path = os.path.join(tmpdir, output_filename)
            
            downsize_video(input_path, output_path)
            
            # Reconstruct same folder tree in the destination preview bucket
            preview_blob_name = os.path.join(dir_name, output_filename) if dir_name else output_filename
            dest_blob = dest_bucket.blob(preview_blob_name)
            
            print(f"Uploading proxy video to {PREVIEW_BUCKET_NAME} as {preview_blob_name}...")
            dest_blob.upload_from_filename(output_path, content_type='video/mp4')
            
        else:
            print(f"Unsupported storage file payload type: {mime_type}.")


def downsize_image(input_path, output_path, max_size=(800, 800)):
    """Resizes an image maintaining aspect ratio and compresses it."""
    print("Resizing image mechanics...")
    with Image.open(input_path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        img.save(output_path, "JPEG", quality=75)
    print("Image optimization complete.")


def downsize_video(input_path, output_path):
    """Uses ffmpeg to create a low-res (480p), low-bitrate video proxy."""
    print("Invoking FFmpeg transcoding...")
    cmd = [
        'ffmpeg', '-y', 
        '-i', input_path,
        '-vf', 'scale=480:-2',       # Scale down to 480p width, keeping proportional height
        '-vcodec', 'libx264',
        '-crf', '28',                 # Compression density tier
        '-b:v', '500k',               # Target lightweight video stream bitrate
        '-acodec', 'aac',
        '-b:a', '64k',                # Low profile sound track
        '-movflags', '+faststart',    # Shifts index data upfront for streaming preview playback
        output_path
    ]
    
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"FFmpeg Error output: {result.stderr}")
        raise RuntimeError("FFmpeg processing engine crashed.")
    print("Video compression proxy execution complete.")
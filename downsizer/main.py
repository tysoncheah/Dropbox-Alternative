import os
import tempfile
import subprocess
import mimetypes
from google.cloud import storage
from PIL import Image

# Initialize the GCS client
storage_client = storage.Client()

# Target bucket for downsized previews (passed via Environment Variables)
PREVIEW_BUCKET_NAME = os.environ.get("PREVIEW_BUCKET")

def process_av_upload(event, context):
    """Triggered by a change to a Cloud Storage bucket."""
    bucket_name = event['bucket']
    file_name = event['name']
    
    # Avoid infinite loops if processing the same bucket
    if bucket_name == PREVIEW_BUCKET_NAME:
        print("File is already in the preview bucket. Skipping.")
        return

    # Determine file type
    mime_type, _ = mimetypes.guess_type(file_name)
    if not mime_type:
        print(f"Could not determine MIME type for {file_name}. Skipping.")
        return

    print(f"Processing file: {file_name} (Type: {mime_type}) from bucket: {bucket_name}")

    # Set up source bucket and blob references
    source_bucket = storage_client.bucket(bucket_name)
    source_blob = source_bucket.blob(file_name)
    
    # Destination setup
    dest_bucket = storage_client.bucket(PREVIEW_BUCKET_NAME)
    dest_blob = dest_bucket.blob(f"preview_{file_name}")

    # Create temporary working directory
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, os.path.basename(file_name))
        
        # Download the source file locally to the function instance
        print(f"Downloading {file_name} for processing...")
        source_blob.download_to_filename(input_path)

        if mime_type.startswith('image/'):
            output_path = os.path.join(tmpdir, f"preview_{os.path.basename(file_name)}")
            downsize_image(input_path, output_path)
            
            print(f"Uploading downsized image to {PREVIEW_BUCKET_NAME}...")
            dest_blob.upload_from_filename(output_path, content_type=mime_type)

        elif mime_type.startswith('video/'):
            # Force output extension to mp4 for uniform browser previewing
            output_filename = f"preview_{os.path.splitext(os.path.basename(file_name))[0]}.mp4"
            output_path = os.path.join(tmpdir, output_filename)
            
            # Adjust destination blob name for video extension change
            dest_blob = dest_bucket.blob(output_filename)
            
            downsize_video(input_path, output_path)
            
            print(f"Uploading proxy video to {PREVIEW_BUCKET_NAME}...")
            dest_blob.upload_from_filename(output_path, content_type='video/mp4')
            
        else:
            print(f"Unsupported file category for {mime_type}. No preview generated.")

def downsize_image(input_path, output_path, max_size=(800, 800)):
    """Resizes an image maintaining aspect ratio and compresses it."""
    print("Resizing image...")
    with Image.open(input_path) as img:
        # Convert RGBA to RGB if saving as JPEG
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        img.save(output_path, "JPEG", quality=75)
    print("Image optimization complete.")

def downsize_video(input_path, output_path):
    """Uses ffmpeg to create a low-res (480p), low-bitrate video proxy."""
    print("Transcoding video to low-res proxy...")
    # Scale down to 480p width, lower audio and video bitrates drastically
    cmd = [
        'ffmpeg', '-y', 
        '-i', input_path,
        '-vf', 'scale=480:-2',       # Scale to 480p width, keep aspect ratio
        '-vcodec', 'libx264',
        '-crf', '28',                 # Lower quality target (higher number = lower quality)
        '-b:v', '500k',               # Max video bitrate
        '-acodec', 'aac',
        '-b:a', '64k',                # Low audio bitrate
        '-movflags', '+faststart',    # Optimizes video layout for web streaming
        output_path
    ]
    
    # Execute ffmpeg command
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"FFmpeg Error: {result.stderr}")
        raise RuntimeError("FFmpeg processing failed.")
    print("Video optimization complete.")
    
    def process_av_upload(event, context):
    bucket_name = event['bucket']
    file_name = event['name']  # e.g., "movies/2026/family/trip.mp4"
    
    if bucket_name == PREVIEW_BUCKET_NAME:
        return

    # Skip directory placeholder objects (GCS creates 0-byte objects ending in '/' for empty folders)
    if file_name.endswith('/'):
        print(f"Skipping folder placeholder: {file_name}")
        return

    mime_type, _ = mimetypes.guess_type(file_name)
    if not mime_type:
        return

    # Extract the simulated folder path and the pure filename
    # e.g., dir_name = "movies/2026/family", base_name = "trip.mp4"
    dir_name, base_name = os.path.split(file_name)

    source_bucket = storage_client.bucket(bucket_name)
    source_blob = source_bucket.blob(file_name)
    
    dest_bucket = storage_client.bucket(PREVIEW_BUCKET_NAME)

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, base_name)
        source_blob.download_to_filename(input_path)

        if mime_type.startswith('image/'):
            output_path = os.path.join(tmpdir, f"preview_{base_name}")
            downsize_image(input_path, output_path)
            
            # Reconstruct the destination path keeping the folder structure
            preview_blob_name = os.path.join(dir_name, f"preview_{base_name}") if dir_name else f"preview_{base_name}"
            dest_blob = dest_bucket.blob(preview_blob_name)
            
            dest_blob.upload_from_filename(output_path, content_type=mime_type)

        elif mime_type.startswith('video/'):
            raw_name = os.path.splitext(base_name)[0]
            output_filename = f"preview_{raw_name}.mp4"
            output_path = os.path.join(tmpdir, output_filename)
            
            downsize_video(input_path, output_path)
            
            # Reconstruct the destination path keeping the folder structure
            preview_blob_name = os.path.join(dir_name, output_filename) if dir_name else output_filename
            dest_blob = dest_bucket.blob(preview_blob_name)
            
            dest_blob.upload_from_filename(output_path, content_type='video/mp4')
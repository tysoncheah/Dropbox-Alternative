# Use a lightweight, official Python image
FROM python:3.11-slim

# Install system dependencies (ffmpeg) and clean up cache to save space
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application script
COPY main.py .

# Cloud Run routes traffic to port 8080 by default
EXPOSE 8080

# Start the Functions Framework
# --target matches the function name in main.py
# --signature-type=cloudevent allows it to parse Google Cloud Storage events
CMD ["functions-framework", "--target=process_av_upload", "--signature-type=cloudevent"]
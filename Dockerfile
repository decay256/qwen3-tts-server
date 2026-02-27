# Qwen3-TTS Standalone GPU Server
# For RunPod serverless (load balancing mode) or any GPU host.
#
# Build:
#   docker build --platform linux/amd64 -t decay256/qwen3-tts:latest .
#
# Run locally:
#   docker run --gpus all -e API_KEY=your-key -p 8000:8000 decay256/qwen3-tts:latest
#
# Environment variables:
#   API_KEY          — Required. Bearer token for auth.
#   ENABLED_MODELS   — Models to load (default: voice_design,base)
#   VOICES_DIR       — Voice files directory (default: ./voices)
#   PROMPTS_DIR      — Clone prompts directory (default: ./voice-prompts)
#   PORT             — Server port (default: 8000)

FROM nvidia/cuda:12.1.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev git ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (install torch first for caching)
RUN pip3 install --no-cache-dir \
    torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121

# Install numpy first (needed by qwen-tts during metadata generation)
RUN pip3 install --no-cache-dir numpy

COPY requirements-server.txt .
RUN pip3 install --no-cache-dir -r requirements-server.txt

# Additional deps for standalone server + RunPod handler
RUN pip3 install --no-cache-dir \
    fastapi uvicorn[standard] pyyaml psutil runpod

# Copy server code
COPY server/ server/
COPY config.example.yaml .

# Create directories for voice data
RUN mkdir -p voices voice-prompts

# Pre-download models into the image (avoids 5+ min download on cold start)
RUN python3 -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign'); \
snapshot_download('Qwen/Qwen3-TTS-12Hz-1.7B-Base')"

# Default env
ENV ENABLED_MODELS=voice_design,base
ENV PORT=8000

# Health check for RunPod
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/ping')" || exit 1

EXPOSE 8000

# Default: RunPod serverless handler (queue-based)
# Override with: CMD ["python3", "-m", "server.standalone"] for direct HTTP
CMD ["python3", "-m", "server.runpod_handler"]

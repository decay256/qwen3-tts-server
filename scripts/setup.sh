#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Qwen3-TTS Server Setup"
echo "========================="

# Check for NVIDIA GPU
if ! command -v nvidia-smi &>/dev/null; then
    echo "⚠️  nvidia-smi not found. Make sure NVIDIA drivers are installed."
    echo "   Install: https://developer.nvidia.com/cuda-downloads"
    exit 1
fi

echo "GPU detected:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo ""

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "🐍 Python: $(python3 --version)"

# Install PyTorch with CUDA
echo "📦 Installing PyTorch with CUDA support..."
pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# Install project dependencies
echo "📦 Installing dependencies..."
pip install -e ".[dev]"

# Install FlashAttention for faster inference (optional)
echo "📦 Installing FlashAttention (optional, may take a few minutes)..."
pip install flash-attn --no-build-isolation 2>/dev/null || echo "⚠️  FlashAttention install failed — will use standard attention. This is fine."

# Download models
echo "📥 Downloading Qwen3-TTS models (~4GB total)..."
python3 -c "
from huggingface_hub import snapshot_download
import os

cache_dir = os.path.expanduser('~/.cache/qwen3-tts')
os.makedirs(cache_dir, exist_ok=True)

models = [
    'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign',
    'Qwen/Qwen3-TTS-12Hz-1.7B-Base',
]

for model in models:
    print(f'  Downloading {model}...')
    snapshot_download(model, cache_dir=cache_dir)
    print(f'  ✓ {model}')

print('✅ All models downloaded.')
"

# Generate auth token
if [ ! -f ".env" ]; then
    TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    echo "AUTH_TOKEN=$TOKEN" > .env
    echo ""
    echo "🔑 Auth token generated and saved to .env"
    echo "   Token: $TOKEN"
    echo "   ⚠️  Copy this token to your remote server's bridge configuration!"
else
    echo "ℹ️  .env already exists, keeping existing auth token."
fi

# Copy config if needed
if [ ! -f "config.yaml" ]; then
    cp config.example.yaml config.yaml
    echo "📋 Config template copied to config.yaml — edit with your remote server IP."
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit config.yaml — set your remote server IP"
echo "  2. Start the bridge on your remote server:"
echo "     export AUTH_TOKEN=\$(cat .env | cut -d= -f2)"
echo "     python -m bridge.server"
echo "  3. Start the local server:"
echo "     source .venv/bin/activate"
echo "     python -m server.main"

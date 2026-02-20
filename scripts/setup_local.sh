#!/usr/bin/env bash
# Setup script for the local GPU machine (Linux/WSL)
set -euo pipefail

echo "============================================"
echo "  Qwen3-TTS Local Server Setup"
echo "============================================"
echo ""

# Check Python version
PYTHON=${PYTHON:-python3}
PY_VERSION=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
echo "Python: $($PYTHON --version)"

# Check for CUDA
if command -v nvidia-smi &> /dev/null; then
    echo "GPU:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
    echo "⚠️  nvidia-smi not found. Make sure CUDA is installed."
fi

echo ""

# Create virtual environment if not in one
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv .venv
    source .venv/bin/activate
    echo "Activated venv: $VIRTUAL_ENV"
else
    echo "Using existing venv: $VIRTUAL_ENV"
fi

echo ""

# Install PyTorch with CUDA
echo "Installing PyTorch with CUDA support..."
pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install project dependencies
echo ""
echo "Installing project dependencies..."
pip install -e ".[dev]"

# Install flash-attn if possible
echo ""
echo "Attempting to install flash-attn (optional, improves speed)..."
pip install flash-attn --no-build-isolation 2>/dev/null || echo "⚠️  flash-attn install failed (optional, continuing without it)"

# Generate config if not exists
echo ""
if [[ ! -f config.yaml ]]; then
    echo "Generating API keys and config..."
    $PYTHON -m scripts.generate_keys
else
    echo "config.yaml already exists, skipping key generation."
fi

# Pre-download models
echo ""
echo "Pre-downloading Qwen3-TTS models (this may take a while)..."
$PYTHON -c "
from transformers import AutoTokenizer, AutoModelForCausalLM
import os

cache_dir = os.path.expanduser('~/.cache/qwen3-tts')
os.makedirs(cache_dir, exist_ok=True)

for model_id in ['Qwen/Qwen3-TTS-12Hz-1.7B-Base', 'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign']:
    print(f'Downloading {model_id}...')
    try:
        AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir, trust_remote_code=True)
        AutoModelForCausalLM.from_pretrained(model_id, cache_dir=cache_dir, trust_remote_code=True)
        print(f'  ✅ {model_id} ready')
    except Exception as e:
        print(f'  ⚠️  Failed to download {model_id}: {e}')
        print(f'  Models will be downloaded on first run.')
"

echo ""
echo "============================================"
echo "  ✅ Setup complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Edit config.yaml with your remote server details"
echo "  2. Start the server: python -m server.local_server"
echo ""

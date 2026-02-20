#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Qwen3-TTS Server Setup"
echo "========================="

# Check for NVIDIA GPU
if ! command -v nvidia-smi &>/dev/null; then
    echo "⚠️  nvidia-smi not found. NVIDIA drivers required."
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

# Install qwen-tts and dependencies
echo "📦 Installing qwen-tts and dependencies..."
pip install -r requirements.txt

# Install FlashAttention (optional, faster inference)
echo "📦 Installing FlashAttention (optional)..."
pip install flash-attn --no-build-isolation 2>/dev/null || \
    echo "⚠️  FlashAttention install failed — will use standard attention. This is fine."

# Generate auth token and create .env
if [ ! -f ".env" ]; then
    TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env <<EOF
AUTH_TOKEN=${TOKEN}
BRIDGE_URL=wss://YOUR_SERVER_IP:8765
ENABLED_MODELS=custom_voice,base
CUDA_DEVICE=cuda:0
BRIDGE_HTTP_PORT=8766
BRIDGE_WS_PORT=8765
RATE_LIMIT=30
LOG_LEVEL=INFO
MAX_TEXT_LENGTH=5000
VOICES_DIR=./voices
EOF
    echo ""
    echo "🔑 Auth token generated: ${TOKEN}"
    echo "   Saved to .env — edit BRIDGE_URL with your server IP!"
else
    echo "ℹ️  .env already exists, keeping existing config."
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env — set BRIDGE_URL to your OpenClaw server"
echo "  2. Start the bridge on your remote server:"
echo "     python -m bridge.server"
echo "  3. Start the local GPU server:"
echo "     source .venv/bin/activate"
echo "     python -m server.main"

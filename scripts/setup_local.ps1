# Setup script for the local GPU machine (Windows PowerShell)
$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Qwen3-TTS Local Server Setup (Windows)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
$pyVersion = python --version 2>&1
Write-Host "Python: $pyVersion"

# Check GPU
try {
    $gpu = nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
    Write-Host "GPU: $gpu"
} catch {
    Write-Host "⚠️  nvidia-smi not found. Make sure CUDA is installed." -ForegroundColor Yellow
}

Write-Host ""

# Create venv
if (-not $env:VIRTUAL_ENV) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    Write-Host "Activated venv: $env:VIRTUAL_ENV"
} else {
    Write-Host "Using existing venv: $env:VIRTUAL_ENV"
}

Write-Host ""

# Install PyTorch with CUDA
Write-Host "Installing PyTorch with CUDA support..."
pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install project
Write-Host ""
Write-Host "Installing project dependencies..."
pip install -e ".[dev]"

# Flash attention (optional)
Write-Host ""
Write-Host "Attempting flash-attn install (optional)..."
try {
    pip install flash-attn --no-build-isolation
} catch {
    Write-Host "⚠️  flash-attn install failed (optional)" -ForegroundColor Yellow
}

# Generate config
Write-Host ""
if (-not (Test-Path "config.yaml")) {
    Write-Host "Generating API keys and config..."
    python -m scripts.generate_keys
} else {
    Write-Host "config.yaml already exists."
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  ✅ Setup complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Edit config.yaml with your remote server details"
Write-Host "  2. Start the server: python -m server.local_server"
Write-Host ""

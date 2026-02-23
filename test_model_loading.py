#!/usr/bin/env python3
"""Test model loading timing on CPU."""

import os
import time
import sys
sys.path.insert(0, '.')

# Set CPU environment
os.environ['CUDA_DEVICE'] = 'cpu'
os.environ['ENABLED_MODELS'] = 'base_small'
os.environ['LOG_LEVEL'] = 'INFO'

from server import config
from server.tts_engine import TTSEngine

def test_model_loading():
    print(f"Testing model loading with:")
    print(f"  CUDA_DEVICE: {config.CUDA_DEVICE}")
    print(f"  ENABLED_MODELS: {config.ENABLED_MODELS}")
    print(f"  Available RAM: ~8GB")
    print()
    
    engine = TTSEngine()
    print("Starting model loading...")
    start_time = time.time()
    
    try:
        engine.load_models()
        load_time = time.time() - start_time
        print(f"✅ Model loading completed in {load_time:.2f} seconds")
        
        # Check health
        health = engine.get_health()
        print(f"Health check: {health}")
        
        return True, load_time
        
    except Exception as e:
        load_time = time.time() - start_time
        print(f"❌ Model loading failed after {load_time:.2f} seconds: {e}")
        return False, load_time

if __name__ == "__main__":
    success, duration = test_model_loading()
    exit(0 if success else 1)
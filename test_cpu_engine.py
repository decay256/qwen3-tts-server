#!/usr/bin/env python3
"""
Test CPU TTS engine loading and basic synthesis
"""

import sys
import os
import time
from pathlib import Path

# Add server module to path
sys.path.insert(0, str(Path(__file__).parent / "server"))

def test_engine_loading():
    """Test if the TTS engine can load models in CPU mode"""
    print("=== Testing CPU TTS Engine ===")
    
    try:
        from server.tts_engine import TTSEngine
        from server import config
        
        print(f"1. Config loaded - CUDA_DEVICE: {config.CUDA_DEVICE}")
        print(f"   Enabled models: {config.ENABLED_MODELS}")
        
        print("2. Creating TTS Engine...")
        engine = TTSEngine()
        
        print("3. Loading models (this will download ~600MB on first run)...")
        start_time = time.time()
        engine.load_models()
        load_time = time.time() - start_time
        print(f"   ✅ Models loaded in {load_time:.1f}s")
        
        print("4. Getting health info...")
        health = engine.get_health()
        print(f"   Status: {health['status']}")
        print(f"   Mode: {health['mode']}")
        print(f"   Device: {health['device']}")
        if 'ram_used_gb' in health:
            print(f"   RAM: {health['ram_used_gb']:.1f}GB / {health['ram_total_gb']:.1f}GB")
        
        print("5. Testing basic synthesis...")
        start_time = time.time()
        audio, sr = engine.generate_custom_voice(
            text="Hello world, this is a test of CPU TTS synthesis.",
            speaker="Ryan"
        )
        synth_time = time.time() - start_time
        print(f"   ✅ Synthesis completed in {synth_time:.1f}s")
        print(f"   Audio shape: {audio.shape}, Sample rate: {sr}")
        
        # Save test audio
        import soundfile as sf
        output_file = "test_cpu_synthesis.wav"
        sf.write(output_file, audio, sr)
        print(f"   ✅ Audio saved to {output_file}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_engine_loading()
    if success:
        print("\n🎉 CPU TTS Engine test PASSED!")
        print("Ready to start full server pipeline...")
    else:
        print("\n❌ CPU TTS Engine test FAILED")
        sys.exit(1)
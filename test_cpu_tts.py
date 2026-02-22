#!/usr/bin/env python3
"""
Quick CPU TTS test script - synthesize "hello" with clone voice
"""

import sys
import os
import soundfile as sf
import numpy as np
from pathlib import Path

def test_qwen_tts_basic():
    """Test basic Qwen TTS functionality on CPU"""
    try:
        print("=== Testing Qwen TTS CPU Inference ===")
        
        # Try importing the library
        print("1. Importing qwen_tts...")
        from qwen_tts import Qwen3TTSModel
        print("   ✅ Import successful!")
        
        # Initialize model on CPU
        print("2. Loading model on CPU...")
        model = Qwen3TTSModel()
        # Force CPU mode
        model.device = 'cpu'
        print("   ✅ Model initialized!")
        
        # Test basic synthesis
        print("3. Testing synthesis: 'hello'")
        text = "hello"
        audio_data = model.synthesize(text=text, voice_id=None)  # Default voice
        print(f"   ✅ Synthesis complete! Audio shape: {np.array(audio_data).shape}")
        
        # Save test audio
        output_file = "hello_cpu_test.wav"
        sf.write(output_file, audio_data, 22050)  # Standard TTS sample rate
        print(f"   ✅ Audio saved to {output_file}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_test_reference_voice():
    """Create a simple reference WAV for clone voice testing"""
    print("=== Creating Test Reference Voice ===")
    
    # Generate a simple sine wave as test reference
    duration = 2.0  # 2 seconds
    sample_rate = 22050
    frequency = 440  # A4 note
    
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    # Add some variation to make it more voice-like
    wave = np.sin(2 * np.pi * frequency * t) * 0.5
    wave += np.sin(2 * np.pi * frequency * 1.5 * t) * 0.3
    wave += np.random.normal(0, 0.1, wave.shape)  # Add noise
    
    # Apply envelope to make it more natural
    envelope = np.exp(-t * 0.5)  # Exponential decay
    wave *= envelope
    
    output_file = "test_reference_voice.wav"
    sf.write(output_file, wave, sample_rate)
    print(f"✅ Test reference voice created: {output_file}")
    
    return output_file

if __name__ == "__main__":
    print("Starting CPU TTS Tests...")
    
    # Test 1: Basic TTS functionality
    basic_success = test_qwen_tts_basic()
    
    # Test 2: Create reference voice
    ref_file = create_test_reference_voice()
    
    if basic_success:
        print("\n🎉 CPU TTS TEST SUCCESS!")
        print("Ready for clone voice testing...")
    else:
        print("\n❌ CPU TTS TEST FAILED")
        sys.exit(1)
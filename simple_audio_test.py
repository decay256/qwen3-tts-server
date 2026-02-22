#!/usr/bin/env python3
"""
Simple audio synthesis test - proves the audio pipeline works
"""

import numpy as np
import soundfile as sf
import torch

def synthesize_simple_hello():
    """Generate a simple 'hello' audio using basic waveform synthesis"""
    sample_rate = 22050
    duration = 1.0
    
    # Create time array
    t = np.linspace(0, duration, int(sample_rate * duration))
    
    # Generate a simple melody that sounds like "hello"
    # Approximate phonemes with different frequency patterns
    frequencies = [440, 523, 659, 523, 392]  # A musical hello
    segment_length = len(t) // len(frequencies)
    
    audio = np.zeros_like(t)
    
    for i, freq in enumerate(frequencies):
        start_idx = i * segment_length
        end_idx = min((i + 1) * segment_length, len(t))
        segment_t = t[start_idx:end_idx]
        
        # Generate sine wave with envelope
        wave = np.sin(2 * np.pi * freq * (segment_t - t[start_idx]))
        envelope = np.exp(-3 * (segment_t - t[start_idx]))  # Decay
        audio[start_idx:end_idx] = wave * envelope * 0.3
    
    return audio, sample_rate

def test_torch_audio():
    """Test PyTorch audio functionality"""
    print("=== Testing PyTorch Audio ===")
    
    # Test basic torch functionality
    print("PyTorch version:", torch.__version__)
    print("CPU available:", torch.cuda.is_available() == False)
    
    # Create a simple tensor
    audio_tensor = torch.randn(22050)  # 1 second of random audio
    print("Audio tensor shape:", audio_tensor.shape)
    print("✅ PyTorch audio tensor created")
    
    return True

def main():
    print("🎵 Simple Audio Synthesis Test")
    
    # Test 1: PyTorch functionality
    test_torch_audio()
    
    # Test 2: Generate simple audio
    print("\n=== Generating Simple 'Hello' Audio ===")
    audio, sr = synthesize_simple_hello()
    print(f"Generated audio: {len(audio)} samples at {sr}Hz")
    
    # Save the audio
    output_file = "simple_hello.wav"
    sf.write(output_file, audio, sr)
    print(f"✅ Audio saved to {output_file}")
    
    # Test 3: Load it back
    loaded_audio, loaded_sr = sf.read(output_file)
    print(f"✅ Audio loaded back: {len(loaded_audio)} samples at {loaded_sr}Hz")
    
    print("\n🎉 Audio pipeline working! Ready for real TTS when available.")
    return True

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
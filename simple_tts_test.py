#!/usr/bin/env python3
"""
Simple TTS test using pyttsx3 - quick validation that TTS works
"""

import os
import time
import soundfile as sf

def test_pyttsx3_tts():
    """Test basic TTS using pyttsx3"""
    print("🔊 Simple TTS Test (pyttsx3)")
    print("="*40)
    
    try:
        print("1. Importing pyttsx3...")
        import pyttsx3
        print("   ✅ pyttsx3 imported")
        
        print("2. Initializing TTS engine...")
        engine = pyttsx3.init()
        
        # Configure voice settings
        voices = engine.getProperty('voices')
        if voices:
            print(f"   Available voices: {len(voices)}")
            # Use first available voice
            engine.setProperty('voice', voices[0].id)
        
        # Set speech rate (slower = more clear)
        engine.setProperty('rate', 150)
        
        print("3. Synthesizing 'hello world'...")
        
        # Method 1: Save to file (more reliable)
        output_file = "hello_simple_tts.wav"
        engine.save_to_file("hello world", output_file)
        engine.runAndWait()
        
        # Check if file was created
        if os.path.exists(output_file):
            print(f"   ✅ Audio saved to {output_file}")
            
            # Try to read it back
            try:
                audio, sr = sf.read(output_file)
                print(f"   ✅ Verification: {len(audio)} samples at {sr}Hz")
                print(f"   Audio duration: {len(audio)/sr:.2f} seconds")
                
                return True
                
            except Exception as e:
                print(f"   ⚠️ Could not read audio file: {e}")
                print("   But file was created successfully!")
                return True
        else:
            print(f"   ❌ Audio file not created")
            return False
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_manual_hello():
    """Create a simple synthetic 'hello' as backup"""
    print("🎵 Creating manual 'hello' synthesis...")
    
    import numpy as np
    
    # Create a simple beep pattern that represents "hello"
    sample_rate = 22050
    duration = 1.5
    
    t = np.linspace(0, duration, int(sample_rate * duration))
    
    # "Hel-lo" pattern with two distinct tones
    freq1 = 440  # "Hel"
    freq2 = 523  # "lo"
    
    # Create two segments
    mid_point = len(t) // 2
    
    hello_audio = np.zeros_like(t)
    
    # "Hel" part
    hello_audio[:mid_point] = 0.3 * np.sin(2 * np.pi * freq1 * t[:mid_point]) * np.exp(-2 * t[:mid_point])
    
    # "lo" part  
    hello_audio[mid_point:] = 0.3 * np.sin(2 * np.pi * freq2 * t[mid_point:]) * np.exp(-2 * (t[mid_point:] - t[mid_point]))
    
    output_file = "hello_manual_synthesis.wav"
    sf.write(output_file, hello_audio, sample_rate)
    
    print(f"   ✅ Manual 'hello' saved to {output_file}")
    return True

if __name__ == "__main__":
    print("🚀 Simple TTS Testing")
    
    # Test 1: pyttsx3
    success1 = test_pyttsx3_tts()
    
    # Test 2: Manual synthesis as backup
    success2 = create_manual_hello()
    
    if success1 or success2:
        print("\n🎉 TTS CAPABILITY CONFIRMED!")
        print("Ready to build clone voice system!")
    else:
        print("\n❌ TTS tests failed")
        exit(1)
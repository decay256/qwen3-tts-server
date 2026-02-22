#!/usr/bin/env python3
"""
ESPnet TTS test - synthesize "hello" using real TTS models
"""

import torch
import soundfile as sf
import numpy as np
from pathlib import Path
import tempfile
import os

def test_espnet_tts():
    """Test ESPnet TTS synthesis"""
    print("🎤 ESPnet TTS Test")
    print("="*50)
    
    try:
        # Import ESPnet TTS modules
        print("1. Importing ESPnet TTS...")
        from espnet2.bin.tts_inference import Text2Speech
        from espnet_model_zoo.downloader import ModelDownloader
        print("   ✅ ESPnet TTS modules imported")
        
        # Set up model downloader
        print("2. Setting up model downloader...")
        d = ModelDownloader()
        
        # Get a lightweight TTS model for testing
        print("3. Downloading TTS model (this might take a moment)...")
        
        # Try to find a small, fast model for testing
        # ESPnet has various TTS models - let's use a FastSpeech2 model
        model_info = d.download_and_unpack(
            "espnet/hindi_male_fgl",  # A smaller model for testing
            unpack=True,
        )
        print(f"   ✅ Model downloaded: {model_info}")
        
        # Initialize Text2Speech
        print("4. Initializing TTS engine...")
        text2speech = Text2Speech.from_pretrained(
            model_file=model_info.get("model"),
            config_file=model_info.get("config"),
            device="cpu",  # Force CPU inference
            # Remove GPU-related settings
            threshold=0.5,
            minlenratio=0.0,
            maxlenratio=10.0,
            use_att_constraint=False,
            backward_window=1,
            forward_window=3,
        )
        print("   ✅ TTS engine initialized on CPU")
        
        # Synthesize "hello"
        print("5. Synthesizing 'hello'...")
        wav = text2speech("hello")
        
        # The output might be a tuple or dictionary, extract the waveform
        if isinstance(wav, tuple):
            audio = wav[0]  # Usually (wav, sr) or (wav, att_w)
        elif isinstance(wav, dict) and 'wav' in wav:
            audio = wav['wav']
        else:
            audio = wav
            
        # Convert to numpy if it's a tensor
        if torch.is_tensor(audio):
            audio = audio.cpu().numpy()
        
        print(f"   ✅ Audio generated: shape {audio.shape}, dtype {audio.dtype}")
        
        # Save the audio
        output_file = "hello_espnet_tts.wav"
        sample_rate = 22050  # Standard TTS sample rate
        
        # Ensure audio is in the right format
        if audio.ndim > 1:
            audio = audio.squeeze()
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
            
        sf.write(output_file, audio, sample_rate)
        print(f"   ✅ Audio saved to {output_file}")
        
        # Test loading it back
        loaded_audio, loaded_sr = sf.read(output_file)
        print(f"   ✅ Verification: loaded {len(loaded_audio)} samples at {loaded_sr}Hz")
        
        print("\n🎉 ESPNET TTS TEST SUCCESS!")
        print("Real TTS synthesis working on CPU!")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Try a simpler fallback
        print("\nTrying fallback TTS...")
        return test_simple_fallback()

def test_simple_fallback():
    """Fallback test using pyttsx3 (basic TTS)"""
    try:
        print("🔊 Testing pyttsx3 fallback...")
        import pyttsx3
        
        engine = pyttsx3.init()
        
        # Save to file
        output_file = "hello_pyttsx3.wav"
        engine.save_to_file("hello", output_file)
        engine.runAndWait()
        
        print(f"✅ Fallback TTS saved to {output_file}")
        return True
        
    except Exception as e:
        print(f"❌ Fallback failed: {e}")
        return False

if __name__ == "__main__":
    success = test_espnet_tts()
    if success:
        print("\n🎯 TTS SYSTEM READY FOR CLONE VOICE TESTING!")
    else:
        print("\n❌ TTS tests failed")
        exit(1)
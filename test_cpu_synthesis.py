#!/usr/bin/env python3
"""Test CPU synthesis with base_small model using voice clone."""

import base64
import json
import requests
import time
from pathlib import Path

def test_synthesis():
    """Test the CPU synthesis pipeline."""
    base_url = "http://localhost:9800/api/v1"
    headers = {"Authorization": "Bearer test-local-key-12345"}
    
    # Use existing reference audio
    ref_audio_path = "elena_voice_reference.wav"
    if not Path(ref_audio_path).exists():
        print(f"Reference audio not found: {ref_audio_path}")
        return False
    
    # Load and encode reference audio
    with open(ref_audio_path, "rb") as f:
        ref_audio_b64 = base64.b64encode(f.read()).decode()
    
    print("Step 1: Creating cloned voice...")
    # First, clone the voice
    clone_payload = {
        "voice_name": "elena_cpu_test",
        "reference_audio": ref_audio_b64
    }
    
    try:
        clone_response = requests.post(
            f"{base_url}/tts/clone",
            headers=headers,
            json=clone_payload,
            timeout=60
        )
        
        if clone_response.status_code != 200:
            print(f"❌ Voice cloning failed: {clone_response.status_code}")
            print(f"Response: {clone_response.text}")
            return False
            
        clone_data = clone_response.json()
        print(f"✅ Voice cloned successfully: {clone_data}")
        voice_id = clone_data["voice_id"]
        
    except Exception as e:
        print(f"❌ Voice cloning failed: {e}")
        return False
    
    print("Step 2: Testing synthesis with cloned voice...")
    # Now test synthesis with the cloned voice
    test_text = "Hello, this is a test of CPU synthesis using voice cloning with the base small model."
    synthesis_payload = {
        "text": test_text,
        "voice_id": voice_id,
        "format": "wav"
    }
    
    print(f"Text: {test_text}")
    print(f"Voice ID: {voice_id}")
    
    start_time = time.time()
    try:
        response = requests.post(
            f"{base_url}/tts/synthesize",
            headers=headers,
            json=synthesis_payload,
            timeout=120  # 2 minutes timeout
        )
        
        synthesis_time = time.time() - start_time
        
        if response.status_code == 200:
            print(f"✅ Synthesis successful in {synthesis_time:.2f}s")
            
            # Parse JSON response
            response_data = response.json()
            audio_b64 = response_data.get("audio")
            
            if not audio_b64:
                print("❌ No audio data in response")
                return False
                
            # Decode and save the output
            audio_bytes = base64.b64decode(audio_b64)
            output_path = "cpu_test_output.wav"
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            print(f"📁 Output saved to: {output_path}")
            
            # Check file size
            file_size = len(audio_bytes)
            print(f"📏 Output file size: {file_size} bytes")
            
            return True
        else:
            print(f"❌ Synthesis failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False

if __name__ == "__main__":
    success = test_synthesis()
    exit(0 if success else 1)
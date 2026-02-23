#!/usr/bin/env python3
"""
Test Pass 2: Designed Voice Synthesis
Test synthesis using a designed voice from the catalog
"""

import time
import requests
import json
from pathlib import Path

def test_designed_synthesis():
    start_time = time.time()
    
    # Test data - using a designed voice from the catalog
    text = "Hello, this is a test"
    voice_id = "Narrator"  # From the voice catalog
    output_file = "/tmp/test_design_pass2.mp3"
    
    # API endpoint
    url = "http://localhost:9800/api/v1/tts/design"
    
    payload = {
        "text": text,
        "description": "A clear, professional narrator voice",
        "format": "mp3"
    }
    
    print(f"Testing designed voice synthesis...")
    print(f"Text: {text}")
    print(f"Voice: {voice_id}")
    print(f"Output: {output_file}")
    
    try:
        # Make the request with API key
        headers = {
            "Authorization": "Bearer test-local-key-12345",
            "Content-Type": "application/json"
        }
        print(f"Sending request to {url}")
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        
        if response.status_code == 200:
            # Save the audio
            with open(output_file, 'wb') as f:
                f.write(response.content)
            
            end_time = time.time()
            duration = end_time - start_time
            file_size = len(response.content)
            
            print(f"SUCCESS!")
            print(f"Duration: {duration:.2f} seconds")
            print(f"File size: {file_size:,} bytes ({file_size/1024:.2f} KB)")
            print(f"Output saved to: {output_file}")
            
            # Verify file exists and has content
            if Path(output_file).exists() and file_size > 0:
                print("File verification: PASSED")
                return True, duration, file_size
            else:
                print("File verification: FAILED")
                return False, duration, file_size
        else:
            print(f"ERROR: HTTP {response.status_code}")
            print(f"Response: {response.text}")
            return False, 0, 0
            
    except Exception as e:
        print(f"ERROR: {e}")
        return False, 0, 0

if __name__ == "__main__":
    success, duration, size = test_designed_synthesis()
    exit(0 if success else 1)
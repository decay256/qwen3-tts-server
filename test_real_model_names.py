#!/usr/bin/env python3
"""
Test with real Qwen TTS model names found from demo
"""

def test_real_models():
    """Test with the actual model names from qwen-tts-demo"""
    print("🎯 Testing Real Qwen TTS Models")
    print("="*50)
    
    try:
        from qwen_tts import Qwen3TTSModel
        
        # Real model names from the demo help
        models_to_test = [
            "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",  # Best for voice cloning
            "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",  # Custom voice
            "Qwen/Qwen3-TTS-12Hz-1.7B-Base",         # Basic model
        ]
        
        for model_name in models_to_test:
            print(f"\n🔄 Testing model: {model_name}")
            try:
                print("   Loading model...")
                # Use CPU and float32 for compatibility
                model = Qwen3TTSModel.from_pretrained(
                    model_name,
                    device_map="cpu",
                    torch_dtype="float32"
                )
                print(f"   ✅ Successfully loaded {model_name}!")
                
                # Test basic synthesis
                print("   Testing synthesis...")
                test_text = "hello world"
                result = model.synthesize(test_text)
                print(f"   ✅ Synthesis successful! Type: {type(result)}")
                
                if hasattr(result, 'shape'):
                    print(f"   Audio shape: {result.shape}")
                
                # Try to save the result
                try:
                    import soundfile as sf
                    import numpy as np
                    
                    # Convert to numpy if needed
                    if hasattr(result, 'cpu'):
                        audio_data = result.cpu().numpy()
                    elif hasattr(result, 'numpy'):
                        audio_data = result.numpy()
                    else:
                        audio_data = result
                    
                    # Handle different audio shapes
                    if len(audio_data.shape) > 1:
                        audio_data = audio_data.flatten()
                    
                    # Save audio
                    output_file = f"qwen_test_{model_name.split('/')[-1].lower().replace('-', '_')}.wav"
                    sample_rate = 22050  # Standard sample rate
                    sf.write(output_file, audio_data, sample_rate)
                    print(f"   ✅ Audio saved to {output_file}")
                    
                except Exception as save_e:
                    print(f"   ⚠️ Couldn't save audio: {save_e}")
                
                print(f"   🎉 {model_name} is working!")
                return model, model_name
                
            except Exception as e:
                print(f"   ❌ Failed {model_name}: {e}")
                # Don't print full traceback for model not found errors
                if "is not a local folder" not in str(e):
                    import traceback
                    traceback.print_exc()
                continue
        
        print("\n❌ No models worked")
        return None, None
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def create_local_server(model, model_name):
    """Create a simple local TTS server"""
    print(f"\n🚀 Creating Local TTS Server with {model_name}")
    print("="*60)
    
    try:
        from flask import Flask, request, jsonify, send_file
        import tempfile
        import soundfile as sf
        import numpy as np
        import io
        
        app = Flask(__name__)
        
        @app.route('/synthesize', methods=['POST'])
        def synthesize():
            try:
                data = request.json
                text = data.get('text', 'hello')
                
                print(f"Synthesizing: {text}")
                result = model.synthesize(text)
                
                # Convert to numpy
                if hasattr(result, 'cpu'):
                    audio_data = result.cpu().numpy()
                elif hasattr(result, 'numpy'):
                    audio_data = result.numpy()
                else:
                    audio_data = result
                
                # Handle different shapes
                if len(audio_data.shape) > 1:
                    audio_data = audio_data.flatten()
                
                # Create temporary file
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                    sf.write(f.name, audio_data, 22050)
                    temp_file = f.name
                
                return send_file(temp_file, mimetype='audio/wav')
                
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @app.route('/health', methods=['GET'])
        def health():
            return jsonify({'status': 'ok', 'model': model_name})
        
        print("✅ Flask server created")
        print("📋 Endpoints:")
        print("   POST /synthesize - { \"text\": \"your text here\" }")
        print("   GET  /health - Status check")
        print("\n🎯 Ready to start server!")
        
        return app
        
    except Exception as e:
        print(f"❌ Server creation failed: {e}")
        return None

def main():
    """Main test function"""
    print("🎯 Real Qwen TTS Local Server Test")
    print("="*70)
    
    # Step 1: Load a working model
    model, model_name = test_real_models()
    
    if model and model_name:
        print(f"\n🎉 SUCCESS! Working model: {model_name}")
        
        # Step 2: Create local server
        server_app = create_local_server(model, model_name)
        
        if server_app:
            print("\n🚀 Server ready to run!")
            print("To start the server, run:")
            print("  python3 -c \"from test_real_model_names import main; app = main(); app.run(host='0.0.0.0', port=9800)\"")
            return server_app
        else:
            print("❌ Server creation failed")
            return None
    else:
        print("\n❌ No working model found")
        return None

if __name__ == "__main__":
    result = main()
    if result:
        print("\n🏆 Local Qwen TTS server is ready!")
        # If running directly, start the server
        if result:
            print("Starting server on port 9800...")
            result.run(host='0.0.0.0', port=9800, debug=True)
    else:
        print("\n💥 Failed to create working server")
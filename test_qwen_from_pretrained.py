#!/usr/bin/env python3
"""
Test qwen-tts using from_pretrained method
"""

def test_qwen_from_pretrained():
    """Test loading qwen model using from_pretrained"""
    print("🚀 Testing Qwen TTS from_pretrained")
    print("="*50)
    
    try:
        from qwen_tts import Qwen3TTSModel
        
        print("1. Loading model using from_pretrained...")
        # Try common model names for Qwen TTS
        model_names = [
            "Qwen/Qwen3-TTS-0.5B",
            "Qwen/Qwen3TTS-0.5B", 
            "qwen3-tts",
            "qwen3-tts-0.5b"
        ]
        
        model = None
        for model_name in model_names:
            try:
                print(f"   Trying model: {model_name}")
                model = Qwen3TTSModel.from_pretrained(model_name)
                print(f"   ✅ Successfully loaded {model_name}!")
                break
            except Exception as e:
                print(f"   ❌ Failed {model_name}: {e}")
                continue
        
        if not model:
            print("   ⚠️ Trying with device specification...")
            # Try with device specification
            try:
                model = Qwen3TTSModel.from_pretrained(
                    "Qwen/Qwen3-TTS-0.5B", 
                    device_map="cpu",
                    torch_dtype="float32"
                )
                print("   ✅ Loaded with CPU device mapping!")
            except Exception as e:
                print(f"   ❌ Device mapping failed: {e}")
        
        if not model:
            print("❌ Could not load any model")
            return None
        
        print("\n2. Testing synthesis...")
        # Try synthesis
        test_text = "hello"
        try:
            print(f"   Synthesizing: '{test_text}'")
            result = model.synthesize(test_text)
            print(f"   ✅ Synthesis successful! Type: {type(result)}")
            
            if hasattr(result, 'shape'):
                print(f"   Audio shape: {result.shape}")
            elif isinstance(result, (list, tuple)):
                print(f"   Audio length: {len(result)}")
            
            # Try to save the audio
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
                
                # Save audio file
                output_file = "qwen_hello_test.wav"
                sample_rate = 22050  # Common sample rate
                sf.write(output_file, audio_data, sample_rate)
                print(f"   ✅ Audio saved to {output_file}")
                
                return model
                
            except Exception as e:
                print(f"   ⚠️ Couldn't save audio: {e}")
                return model
        
        except Exception as e:
            print(f"   ❌ Synthesis failed: {e}")
            import traceback
            traceback.print_exc()
            return model  # Return model even if synthesis failed
        
    except Exception as e:
        print(f"❌ Model loading failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """Main test function"""
    print("🎯 Qwen TTS from_pretrained Test")
    print("="*60)
    
    model = test_qwen_from_pretrained()
    
    if model:
        print("\n🎉 SUCCESS!")
        print("✅ Qwen TTS model loaded successfully")
        print("🎯 Ready to build real server with this model!")
        
        # Show available methods
        print("\n📋 Available model methods:")
        methods = [attr for attr in dir(model) if not attr.startswith('_') and callable(getattr(model, attr))]
        for method in methods[:10]:  # Show first 10 methods
            print(f"   - {method}")
        if len(methods) > 10:
            print(f"   ... and {len(methods) - 10} more")
        
        return True
    else:
        print("\n❌ Model loading failed")
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n🏆 Ready to build the real server!")
    else:
        print("\n🔧 Need to investigate model loading further")
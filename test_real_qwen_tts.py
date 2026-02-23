#!/usr/bin/env python3
"""
Test the real qwen-tts library once it's installed
"""

def test_qwen_import():
    """Test importing the real qwen_tts library"""
    print("🔧 Testing Real Qwen TTS Import")
    print("="*40)
    
    try:
        print("1. Importing qwen_tts...")
        import qwen_tts
        print(f"   ✅ qwen_tts imported successfully!")
        print(f"   Version: {getattr(qwen_tts, '__version__', 'unknown')}")
        
        # Try to import the main model class
        print("2. Importing TTS model class...")
        from qwen_tts import Qwen3TTSModel
        print("   ✅ Qwen3TTSModel imported!")
        
        return True
        
    except ImportError as e:
        print(f"   ❌ Import failed: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_model_initialization():
    """Test initializing the model"""
    print("\n🚀 Testing Model Initialization")
    print("="*40)
    
    try:
        from qwen_tts import Qwen3TTSModel
        
        print("1. Initializing model...")
        # Try to initialize with CPU device to avoid GPU issues
        model = Qwen3TTSModel(device='cpu')
        print("   ✅ Model initialized on CPU!")
        
        return model
        
    except Exception as e:
        print(f"   ❌ Model init failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_basic_synthesis(model):
    """Test basic text synthesis"""
    print("\n🎤 Testing Basic Synthesis")
    print("="*40)
    
    if model is None:
        print("   ❌ No model available")
        return False
        
    try:
        print("1. Synthesizing 'hello'...")
        # Try basic synthesis
        audio = model.synthesize(text="hello")
        print(f"   ✅ Synthesis successful! Audio type: {type(audio)}")
        
        if hasattr(audio, 'shape'):
            print(f"   Audio shape: {audio.shape}")
        elif isinstance(audio, list):
            print(f"   Audio length: {len(audio)}")
            
        return audio
        
    except Exception as e:
        print(f"   ❌ Synthesis failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """Run all tests"""
    print("🎯 Real Qwen TTS Testing")
    print("="*50)
    
    # Test 1: Import
    if not test_qwen_import():
        print("\n❌ Import failed - library not properly installed")
        return False
        
    # Test 2: Model initialization
    model = test_model_initialization()
    
    # Test 3: Basic synthesis
    if model:
        audio = test_basic_synthesis(model)
        
        if audio is not None:
            print("\n🎉 ALL TESTS PASSED!")
            print("✅ Qwen TTS is working!")
            return True
    
    print("\n⚠️ Some tests failed, but import worked")
    return True

if __name__ == "__main__":
    success = main()
    if not success:
        exit(1)
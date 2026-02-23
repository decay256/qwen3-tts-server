#!/usr/bin/env python3
"""
Test real qwen-tts API and find correct usage
"""

def explore_qwen_api():
    """Explore the actual qwen-tts API"""
    print("🔍 Exploring Qwen TTS API")
    print("="*40)
    
    try:
        import qwen_tts
        print(f"✅ qwen_tts imported")
        
        # Check what's available in the module
        print("\n📦 Available classes/functions:")
        for attr in dir(qwen_tts):
            if not attr.startswith('_'):
                obj = getattr(qwen_tts, attr)
                print(f"   - {attr}: {type(obj)}")
        
        # Try to import the model
        from qwen_tts import Qwen3TTSModel
        print(f"\n🏗️ Qwen3TTSModel class found")
        
        # Check the model's __init__ signature
        import inspect
        sig = inspect.signature(Qwen3TTSModel.__init__)
        print(f"   Constructor signature: {sig}")
        
        # Try different initialization approaches
        print("\n🚀 Testing different initialization approaches:")
        
        # Approach 1: No arguments
        try:
            print("1. Trying: Qwen3TTSModel()")
            model = Qwen3TTSModel()
            print("   ✅ Success with no args!")
            return model
        except Exception as e:
            print(f"   ❌ Failed: {e}")
        
        # Approach 2: Common device arguments
        for device_arg in ['device_map', 'torch_device', 'device_id']:
            try:
                print(f"2. Trying: Qwen3TTSModel({device_arg}='cpu')")
                model = Qwen3TTSModel(**{device_arg: 'cpu'})
                print(f"   ✅ Success with {device_arg}='cpu'!")
                return model
            except Exception as e:
                print(f"   ❌ Failed: {e}")
        
        # Approach 3: Check if there's a load method
        try:
            print("3. Trying class methods...")
            for attr in dir(Qwen3TTSModel):
                if 'load' in attr.lower() or 'from' in attr.lower():
                    print(f"   Found method: {attr}")
        except Exception as e:
            print(f"   ❌ Failed to inspect methods: {e}")
        
        return None
        
    except Exception as e:
        print(f"❌ API exploration failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_synthesis(model):
    """Test basic synthesis if model works"""
    if not model:
        print("❌ No model to test")
        return False
        
    print("\n🎤 Testing Synthesis")
    print("="*30)
    
    try:
        # Try common synthesis methods
        for method_name in ['synthesize', 'generate', 'tts', 'speak', '__call__']:
            if hasattr(model, method_name):
                method = getattr(model, method_name)
                print(f"   Found method: {method_name}")
                
                try:
                    # Try with simple text
                    print(f"   Trying {method_name}('hello')")
                    result = method("hello")
                    print(f"   ✅ Success! Result type: {type(result)}")
                    
                    if hasattr(result, 'shape'):
                        print(f"   Result shape: {result.shape}")
                    elif isinstance(result, (list, tuple)):
                        print(f"   Result length: {len(result)}")
                        
                    return result
                    
                except Exception as e:
                    print(f"   ❌ {method_name} failed: {e}")
                    continue
        
        print("   ❌ No working synthesis method found")
        return None
        
    except Exception as e:
        print(f"❌ Synthesis test failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """Run API exploration and testing"""
    print("🎯 Qwen TTS Real API Test")
    print("="*50)
    
    # Step 1: Explore API
    model = explore_qwen_api()
    
    # Step 2: Test synthesis if model works
    if model:
        audio = test_synthesis(model)
        
        if audio is not None:
            print("\n🎉 SUCCESS!")
            print("✅ Model initialization worked")
            print("✅ Synthesis worked")
            print("🎯 Ready to build real server!")
            return True
    
    print("\n⚠️ Partial success - need to investigate API further")
    return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n🏆 Real Qwen TTS is functional!")
    else:
        print("\n❓ Need more API investigation")
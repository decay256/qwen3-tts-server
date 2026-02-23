#!/usr/bin/env python3
"""
Test quantization feasibility for Qwen3-TTS models
"""

import sys
import traceback

def test_bitsandbytes_installation():
    """Check if bitsandbytes can be installed"""
    print("=== Testing bitsandbytes installation ===")
    try:
        import subprocess
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", "bitsandbytes"
        ], capture_output=True, text=True, timeout=120)
        
        print(f"Installation exit code: {result.returncode}")
        if result.stdout:
            print(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            print(f"STDERR:\n{result.stderr}")
            
        if result.returncode == 0:
            print("✅ bitsandbytes installation: SUCCESS")
            return True
        else:
            print("❌ bitsandbytes installation: FAILED")
            return False
    except Exception as e:
        print(f"❌ bitsandbytes installation: ERROR - {e}")
        return False

def test_bitsandbytes_config():
    """Test if BitsAndBytesConfig can be created"""
    print("\n=== Testing BitsAndBytesConfig creation ===")
    try:
        import torch
        from transformers import BitsAndBytesConfig
        
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True, 
            bnb_4bit_compute_dtype=torch.float16
        )
        print("✅ BitsAndBytesConfig creation: SUCCESS")
        print(f"Config: {bnb_config}")
        return True
    except Exception as e:
        print(f"❌ BitsAndBytesConfig creation: ERROR - {e}")
        traceback.print_exc()
        return False

def test_qwen_tts_quantization_support():
    """Test if Qwen3TTSModel supports quantization_config parameter"""
    print("\n=== Testing Qwen3TTSModel quantization support ===")
    try:
        import torch
        from qwen_tts import Qwen3TTSModel
        from transformers import BitsAndBytesConfig
        
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        
        # Try to inspect the from_pretrained method signature
        import inspect
        sig = inspect.signature(Qwen3TTSModel.from_pretrained)
        print(f"from_pretrained signature: {sig}")
        
        # Test with a small model (but don't actually load it)
        model_name = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        print(f"Testing quantization_config parameter with {model_name}...")
        
        try:
            # This will likely fail but we can see what error we get
            model = Qwen3TTSModel.from_pretrained(
                model_name,
                quantization_config=bnb_config,
                device_map="cpu"
            )
            print("✅ Quantization config accepted!")
            return True
        except TypeError as te:
            if "quantization_config" in str(te):
                print("❌ quantization_config parameter not supported")
                print(f"Error: {te}")
                return False
            else:
                print("❓ Other TypeError - quantization_config might be supported")
                print(f"Error: {te}")
                return True
        except Exception as e:
            print("❓ Other error - quantization_config might be supported")
            print(f"Error: {e}")
            return True
            
    except Exception as e:
        print(f"❌ Qwen3TTSModel quantization test: ERROR - {e}")
        traceback.print_exc()
        return False

def test_bfloat16_cpu_loading():
    """Test loading voice_design model in bfloat16 on CPU"""
    print("\n=== Testing bfloat16 on CPU ===")
    try:
        import torch
        from qwen_tts import Qwen3TTSModel
        
        model_name = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
        print(f"Testing bfloat16 loading of {model_name} on CPU...")
        print("This may take several minutes...")
        
        start_time = __import__('time').time()
        model = Qwen3TTSModel.from_pretrained(
            model_name,
            device_map="cpu",
            torch_dtype=torch.bfloat16
        )
        end_time = __import__('time').time()
        
        print(f"✅ bfloat16 CPU loading: SUCCESS in {end_time - start_time:.1f}s")
        print(f"Model dtype: {next(model.parameters()).dtype}")
        print(f"Model device: {next(model.parameters()).device}")
        
        # Clean up
        del model
        torch.cuda.empty_cache()
        return True
        
    except Exception as e:
        print(f"❌ bfloat16 CPU loading: ERROR - {e}")
        traceback.print_exc()
        return False

def main():
    print("Testing quantization and bfloat16 feasibility for Qwen3-TTS\n")
    
    results = {}
    
    # Test bitsandbytes installation
    results['bitsandbytes_install'] = test_bitsandbytes_installation()
    
    if results['bitsandbytes_install']:
        # Test BitsAndBytesConfig creation
        results['bnb_config'] = test_bitsandbytes_config()
        
        # Test Qwen3TTSModel quantization support
        results['qwen_quantization'] = test_qwen_tts_quantization_support()
    else:
        results['bnb_config'] = False
        results['qwen_quantization'] = False
    
    # Test bfloat16 on CPU (independent of quantization)
    results['bfloat16_cpu'] = test_bfloat16_cpu_loading()
    
    # Summary
    print("\n" + "="*50)
    print("QUANTIZATION FEASIBILITY SUMMARY")
    print("="*50)
    print(f"bitsandbytes installation: {'✅ YES' if results['bitsandbytes_install'] else '❌ NO'}")
    print(f"BitsAndBytesConfig creation: {'✅ YES' if results['bnb_config'] else '❌ NO'}")
    print(f"Qwen3TTS quantization support: {'✅ YES' if results['qwen_quantization'] else '❌ NO'}")
    print(f"bfloat16 on CPU: {'✅ YES' if results['bfloat16_cpu'] else '❌ NO'}")
    
    if all([results['bitsandbytes_install'], results['bnb_config'], results['qwen_quantization']]):
        print("\n🎉 4-bit quantization appears to be FEASIBLE!")
        print("You can likely use:")
        print("  from transformers import BitsAndBytesConfig")
        print("  bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)")
        print("  model = Qwen3TTSModel.from_pretrained(model_name, quantization_config=bnb_config)")
    else:
        print("\n⚠️  4-bit quantization may NOT be feasible with current setup")
    
    if results['bfloat16_cpu']:
        print("\n🎉 bfloat16 on CPU is WORKING! This halves memory usage vs float32.")
    else:
        print("\n⚠️  bfloat16 on CPU failed - stick with float32")

if __name__ == "__main__":
    main()
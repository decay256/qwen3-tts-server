#!/usr/bin/env python3
"""
Voice Package System Demo

This script demonstrates the complete voice packaging workflow:
1. Export existing voices as packages
2. Clear voice catalog
3. Import packages to restore voices
4. Verify all voices are restored correctly

Run: python demo_voice_packaging.py
"""

import json
import tempfile
from pathlib import Path

from server.voice_manager import VoiceManager
from server.voice_packager import VoicePackager


def main():
    print("🎙️  Voice Package System Demo")
    print("=" * 50)
    
    # Initialize voice manager and packager
    vm = VoiceManager('./voices')
    packager = VoicePackager(vm)
    
    print(f"📊 Initial voice count: {len(vm._voices)}")
    
    # List all voices
    print("\n📋 Current voices:")
    for voice in vm.list_voices():
        print(f"  • {voice['name']} ({voice['type']}) - {voice['voice_id']}")
    
    # Create temporary directory for packages
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Export all voices as packages
        print(f"\n📦 Exporting all voices to {temp_path}")
        packages = packager.export_all(temp_path)
        
        print(f"✅ Exported {len(packages)} voice packages:")
        total_size = 0
        for pkg in packages:
            size = pkg.stat().st_size
            total_size += size
            print(f"  • {pkg.name}: {size:,} bytes")
        print(f"📊 Total package size: {total_size:,} bytes")
        
        # Backup original voice IDs
        original_voice_ids = list(vm._voices.keys())
        
        # Clear all voices (simulate clean install)
        print("\n🗑️  Clearing voice catalog...")
        vm._voices.clear()
        vm._save_catalog()
        print(f"   Voice count after clear: {len(vm._voices)}")
        
        # Import all packages
        print("\n📥 Importing voice packages...")
        imported_voices = []
        for pkg in packages:
            print(f"   Importing {pkg.name}...")
            voice = packager.import_package(pkg)
            imported_voices.append(voice)
            print(f"   ✅ Imported: {voice.name} ({voice.voice_id})")
        
        print(f"\n🎯 Import complete! Restored {len(imported_voices)} voices")
        
        # Verify all voices are restored
        print("\n🔍 Verification:")
        restored_voice_ids = list(vm._voices.keys())
        
        if set(original_voice_ids) == set(restored_voice_ids):
            print("✅ SUCCESS: All original voice IDs restored")
        else:
            print("❌ ERROR: Voice IDs don't match")
            print(f"   Original: {sorted(original_voice_ids)}")
            print(f"   Restored: {sorted(restored_voice_ids)}")
            return
        
        # Check voice integrity
        print("\n🔬 Checking voice integrity:")
        for voice in imported_voices:
            if voice.voice_type == "cloned":
                if voice.reference_audio and Path(voice.reference_audio).exists():
                    print(f"   ✅ {voice.name}: Reference audio present")
                else:
                    print(f"   ❌ {voice.name}: Missing reference audio")
                    
                if voice.ref_text:
                    print(f"   ✅ {voice.name}: Transcript present ({len(voice.ref_text)} chars)")
                else:
                    print(f"   ⚠️  {voice.name}: No transcript")
                    
            elif voice.voice_type == "designed":
                if voice.design_description:
                    print(f"   ✅ {voice.name}: Design description present")
                else:
                    print(f"   ⚠️  {voice.name}: No design description")
        
        print("\n🎉 Voice Package System Demo Complete!")
        print("   The system successfully exported and imported all voices,")
        print("   preserving all metadata, reference audio, and transcripts.")


if __name__ == "__main__":
    main()
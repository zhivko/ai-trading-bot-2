#!/usr/bin/env python3
"""
Test script to check Whisper installation and model loading.
"""

try:
    import whisper
    print("✅ Whisper import successful")

    try:
        print("🔧 Loading Whisper base model...")
        model = whisper.load_model("base", device="cpu")
        print("✅ Whisper base model loaded successfully")

        # Test transcription with a simple audio file if available
        print("Whisper is ready for transcription")

    except Exception as e:
        print(f"❌ Error loading Whisper model: {e}")

except ImportError as e:
    print(f"❌ Failed to import Whisper: {e}")
except Exception as e:
    print(f"❌ Unexpected error: {e}")

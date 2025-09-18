#!/usr/bin/env python3
"""
Simple test to check if Whisper can be imported and basic functionality works.
"""

try:
    import whisper
    print("✅ Whisper import successful")

    # Try to load the model with GPU fallback (this might take a while)
    print("Loading Whisper model (this may take a few minutes)...")
    try:
        # Try to load with GPU acceleration
        model = whisper.load_model("base")
        print("✅ Whisper model loaded successfully")
    except Exception as e:
        print(f"❌ GPU loading failed: {e}")
        print("Attempting to load on CPU...")
        # Force CPU loading
        import torch
        torch.cuda.is_available = lambda: False  # Temporarily disable CUDA
        model = whisper.load_model("base")
        print("✅ Whisper model loaded on CPU")

    # Test with a simple audio file creation
    import wave
    import struct
    import math
    import tempfile
    import os

    # Create a simple test WAV file
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
        temp_filename = temp_file.name

    try:
        # Generate a simple sine wave
        sample_rate = 16000  # Whisper works well with 16kHz
        duration = 1  # 1 second
        frequency = 440  # A note

        frames = []
        for i in range(int(duration * sample_rate)):
            value = int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
            frames.append(struct.pack('<h', value))

        # Write WAV file
        with wave.open(temp_filename, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b''.join(frames))

        print("✅ Test audio file created")

        # Test transcription
        print("Testing transcription...")
        result = model.transcribe(temp_filename)
        print("✅ Transcription completed")
        print(f"Result: {result}")

    finally:
        # Clean up
        try:
            os.unlink(temp_filename)
        except:
            pass

except ImportError as e:
    print(f"❌ Import error: {e}")
except Exception as e:
    print(f"❌ Error: {e}")

print("Test completed.")

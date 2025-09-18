#!/usr/bin/env python3
"""
Test script for the audio transcription endpoint.
This script creates a simple test audio file and tests the transcription endpoint.
"""

import requests
import io
import wave
import struct
import math
import os
import tempfile

def create_test_wav_file(filename, duration=3, sample_rate=44100, frequency=440):
    """
    Create a simple test WAV file with a sine wave tone.
    """
    # Generate sine wave
    frames = []
    for i in range(int(duration * sample_rate)):
        # Generate sine wave
        value = int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
        frames.append(struct.pack('<h', value))

    # Write WAV file
    with wave.open(filename, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b''.join(frames))

def test_audio_transcription():
    """
    Test the audio transcription endpoint.
    """
    # Create a temporary test audio file
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
        temp_filename = temp_file.name

    try:
        # Create test audio file
        create_test_wav_file(temp_filename, duration=2, frequency=440)  # 2 second A note

        # Test the endpoint
        url = "http://192.168.1.52:5000/transcribe_audio"

        with open(temp_filename, 'rb') as audio_file:
            files = {'audio_file': ('test_audio.wav', audio_file, 'audio/wav')}
            response = requests.post(url, files=files)

        print(f"Response status code: {response.status_code}")
        print(f"Response content: {response.text}")

        if response.status_code == 200:
            result = response.json()
            print("✅ Audio transcription test successful!")
            print(f"Transcribed text: '{result.get('transcribed_text', 'N/A')}'")
            print(f"Language: {result.get('language', 'N/A')}")
        else:
            print("❌ Audio transcription test failed!")
            print(f"Error: {response.text}")

    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to the server. Make sure the FastAPI app is running on localhost:5000")
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
    finally:
        # Clean up
        try:
            os.unlink(temp_filename)
        except:
            pass

if __name__ == "__main__":
    print("Testing audio transcription endpoint...")
    test_audio_transcription()

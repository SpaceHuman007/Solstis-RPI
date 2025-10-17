#!/usr/bin/env python3
"""
Simple audio output test for Raspberry Pi audio jack
Generates speech and plays it through the audio output
"""

import os
import subprocess
import time
import struct
import math
import tempfile
import wave
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Audio configuration
OUT_DEVICE = os.getenv("AUDIO_DEVICE", "plughw:0,0")  # Default to plughw:0,0
OUT_SR = int(os.getenv("OUT_SR", "24000"))  # Audio output sample rate

# ElevenLabs config
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

# ElevenLabs voice settings
ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.5"))
ELEVENLABS_SIMILARITY_BOOST = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.5"))
ELEVENLABS_STYLE = float(os.getenv("ELEVENLABS_STYLE", "0.0"))
ELEVENLABS_SPEAKER_BOOST = os.getenv("ELEVENLABS_SPEAKER_BOOST", "true").lower() == "true"

def spawn_aplay(rate):
    """Spawn aplay process for audio playback"""
    args = ["aplay", "-t", "raw", "-f", "S16_LE", "-r", str(rate), "-c", "1"]
    if OUT_DEVICE:
        args += ["-D", OUT_DEVICE]
    else:
        # Use default audio device
        args += ["-D", "default"]
    
    print(f"🔊 Spawn Command: {' '.join(args)}")
    
    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"🔊 Spawn Success: aplay process created with PID {process.pid}")
        return process
    except Exception as e:
        print(f"🔊 Spawn Error: Failed to create aplay process: {e}")
        raise

def text_to_speech_elevenlabs(text):
    """Convert text to speech using ElevenLabs TTS API"""
    if not ELEVENLABS_API_KEY:
        print("❌ ELEVENLABS_API_KEY not set - cannot generate speech")
        return b""
    
    try:
        print(f"🎤 ElevenLabs TTS Request: '{text[:50]}{'...' if len(text) > 50 else ''}'")
        print(f"🎤 ElevenLabs TTS Config: voice_id={ELEVENLABS_VOICE_ID}, model_id=eleven_turbo_v2_5, format=pcm_24000")
        
        # ElevenLabs TTS API endpoint with PCM format as query parameter
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}?output_format=pcm_24000"
        
        # Prepare headers
        headers = {
            "Accept": "audio/pcm",  # Request PCM format
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        # Prepare data
        data = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",  # Use turbo model that fully supports PCM
            "voice_settings": {
                "stability": ELEVENLABS_STABILITY,
                "similarity_boost": ELEVENLABS_SIMILARITY_BOOST,
                "style": ELEVENLABS_STYLE,
                "use_speaker_boost": ELEVENLABS_SPEAKER_BOOST
            }
        }
        
        # Make request
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            audio_data = response.content
            print(f"🎤 ElevenLabs TTS Success: Generated {len(audio_data)} bytes of PCM audio data (24kHz)")
            return audio_data
        else:
            print(f"🎤 ElevenLabs TTS Error: {response.status_code} - {response.text}")
            return b""
    
    except Exception as e:
        print(f"🎤 ElevenLabs TTS Error: {e}")
        return b""

def play_audio(audio_data):
    """Play audio data using aplay"""
    try:
        print(f"🔊 Audio Playback: Starting playback of {len(audio_data)} bytes")
        print(f"🔊 Audio Config: sample_rate={OUT_SR}, device={OUT_DEVICE or 'default'}")
        
        player = spawn_aplay(OUT_SR)
        
        print(f"🔊 Audio Write: Writing {len(audio_data)} bytes to player stdin")
        player.stdin.write(audio_data)
        player.stdin.close()
        print(f"🔊 Audio Write: Closed stdin, waiting for playback to complete")
        
        # Wait for playback to complete
        return_code = player.wait(timeout=10)
        print(f"🔊 Audio Complete: player finished with return code {return_code}")
        
        if return_code != 0:
            print(f"🔊 Audio Warning: aplay returned non-zero exit code {return_code}")
        
    except subprocess.TimeoutExpired:
        print(f"🔊 Audio Timeout: player process timed out, killing it")
        player.kill()
    except Exception as e:
        print(f"🔊 Audio Error: {e}")

def test_audio_output():
    """Run audio output tests with speech"""
    print("🎤 Starting Audio Output Test with Speech")
    print(f"📊 Configuration:")
    print(f"   - Sample Rate: {OUT_SR} Hz")
    print(f"   - Output Device: {OUT_DEVICE or 'default'}")
    print(f"   - ElevenLabs Voice ID: {ELEVENLABS_VOICE_ID}")
    print()
    
    if not ELEVENLABS_API_KEY:
        print("❌ ELEVENLABS_API_KEY not set in environment variables")
        print("   Please set your ElevenLabs API key to test speech output")
        return
    
    # Test 1: Simple greeting
    print("🎤 Test 1: Playing greeting message...")
    speech_data = text_to_speech_elevenlabs("Hello! This is a test of the audio output system.")
    if speech_data:
        play_audio(speech_data)
    time.sleep(1.0)
    
    # Test 2: Numbers and letters
    print("🎤 Test 2: Playing numbers and letters...")
    speech_data = text_to_speech_elevenlabs("Testing one, two, three. A, B, C.")
    if speech_data:
        play_audio(speech_data)
    time.sleep(1.0)
    
    # Test 3: Longer sentence
    print("🎤 Test 3: Playing longer sentence...")
    speech_data = text_to_speech_elevenlabs("This is a longer test sentence to verify that the audio output is working correctly through the audio jack.")
    if speech_data:
        play_audio(speech_data)
    time.sleep(1.0)
    
    # Test 4: Medical kit reference
    print("🎤 Test 4: Playing medical kit reference...")
    speech_data = text_to_speech_elevenlabs("Band-Aids, gauze pads, and medical tape are available in your kit.")
    if speech_data:
        play_audio(speech_data)
    
    print("🎤 Audio output test completed!")

if __name__ == "__main__":
    try:
        test_audio_output()
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"❌ Test failed: {e}")

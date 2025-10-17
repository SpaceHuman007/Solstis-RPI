#!/usr/bin/env python3
"""
ElevenLabs speech diagnostic test
"""

import os
import subprocess
import tempfile
import wave
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Configuration
OUT_DEVICE = os.getenv("AUDIO_DEVICE", "plughw:0,0")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")

def test_elevenlabs_connection():
    """Test ElevenLabs API connection"""
    print("🔍 Testing ElevenLabs API connection...")
    
    if not ELEVENLABS_API_KEY:
        print("❌ ELEVENLABS_API_KEY not set")
        return False
    
    if ELEVENLABS_API_KEY.startswith("YOUR-") or len(ELEVENLABS_API_KEY) < 10:
        print("❌ ELEVENLABS_API_KEY appears to be placeholder or invalid")
        return False
    
    print(f"✅ API Key found (length: {len(ELEVENLABS_API_KEY)})")
    return True

def test_elevenlabs_mp3():
    """Test ElevenLabs with MP3 format (easier to debug)"""
    print("🎤 Testing ElevenLabs TTS with MP3 format...")
    
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        data = {
            "text": "Hello, this is a test.",
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5,
                "style": 0.0,
                "use_speaker_boost": True
            }
        }
        
        print(f"Making request to: {url}")
        response = requests.post(url, json=data, headers=headers)
        
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            audio_data = response.content
            print(f"✅ Got {len(audio_data)} bytes of MP3 audio")
            
            # Save to file for inspection
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio_data)
                temp_file = f.name
            
            print(f"Saved audio to: {temp_file}")
            
            # Try to play with mpg123
            try:
                result = subprocess.run(
                    ["mpg123", "-q", temp_file],
                    capture_output=True,
                    timeout=10
                )
                if result.returncode == 0:
                    print("✅ MP3 playback successful")
                else:
                    print(f"❌ MP3 playback failed: {result.stderr.decode()}")
            except FileNotFoundError:
                print("❌ mpg123 not installed - cannot test MP3 playback")
            except subprocess.TimeoutExpired:
                print("❌ MP3 playback timed out")
            
            # Clean up
            os.unlink(temp_file)
            return True
        else:
            print(f"❌ ElevenLabs API error: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ ElevenLabs test failed: {e}")
        return False

def test_elevenlabs_pcm():
    """Test ElevenLabs with PCM format"""
    print("🎤 Testing ElevenLabs TTS with PCM format...")
    
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}?output_format=pcm_24000"
        
        headers = {
            "Accept": "audio/pcm",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        data = {
            "text": "Hello, this is a PCM test.",
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5,
                "style": 0.0,
                "use_speaker_boost": True
            }
        }
        
        print(f"Making request to: {url}")
        response = requests.post(url, json=data, headers=headers)
        
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            audio_data = response.content
            print(f"✅ Got {len(audio_data)} bytes of PCM audio")
            
            # Try to play with aplay
            try:
                process = subprocess.Popen(
                    ["aplay", "-t", "raw", "-f", "S16_LE", "-r", "24000", "-c", "1", "-D", OUT_DEVICE],
                    stdin=subprocess.PIPE
                )
                process.stdin.write(audio_data)
                process.stdin.close()
                return_code = process.wait(timeout=10)
                
                if return_code == 0:
                    print("✅ PCM playback successful")
                else:
                    print(f"❌ PCM playback failed with return code: {return_code}")
                    
            except subprocess.TimeoutExpired:
                print("❌ PCM playback timed out")
                process.kill()
            except Exception as e:
                print(f"❌ PCM playback error: {e}")
            
            return True
        else:
            print(f"❌ ElevenLabs API error: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ ElevenLabs PCM test failed: {e}")
        return False

def main():
    print("🔍 ElevenLabs Speech Diagnostic Test")
    print("=" * 50)
    
    # Test 1: API Connection
    if not test_elevenlabs_connection():
        print("\n❌ Cannot proceed without valid API key")
        return
    
    print("\n" + "=" * 50)
    
    # Test 2: MP3 Format
    mp3_success = test_elevenlabs_mp3()
    
    print("\n" + "=" * 50)
    
    # Test 3: PCM Format
    pcm_success = test_elevenlabs_pcm()
    
    print("\n" + "=" * 50)
    print("📊 DIAGNOSTIC SUMMARY:")
    print(f"   API Connection: ✅")
    print(f"   MP3 Format: {'✅' if mp3_success else '❌'}")
    print(f"   PCM Format: {'✅' if pcm_success else '❌'}")
    
    if mp3_success and not pcm_success:
        print("\n💡 RECOMMENDATION: Use MP3 format instead of PCM")
        print("   The issue is likely with PCM format conversion")
    elif not mp3_success and not pcm_success:
        print("\n💡 RECOMMENDATION: Check ElevenLabs API key and network connection")
    elif pcm_success:
        print("\n💡 RECOMMENDATION: PCM format works - check your main code")

if __name__ == "__main__":
    main()

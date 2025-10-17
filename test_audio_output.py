#!/usr/bin/env python3
"""
Simple audio output test for Raspberry Pi audio jack
Generates a test tone and plays it through the audio output
"""

import os
import subprocess
import time
import struct
import math
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Audio configuration
OUT_DEVICE = os.getenv("AUDIO_DEVICE", "plughw:0,0")  # Default to plughw:0,0
OUT_SR = int(os.getenv("OUT_SR", "24000"))  # Audio output sample rate

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

def generate_tone(frequency=440, duration=2.0, sample_rate=24000, amplitude=0.3):
    """
    Generate a sine wave tone
    frequency: frequency in Hz
    duration: duration in seconds
    sample_rate: sample rate in Hz
    amplitude: amplitude (0.0 to 1.0)
    """
    samples = int(duration * sample_rate)
    audio_data = bytearray()
    
    for i in range(samples):
        # Generate sine wave
        t = i / sample_rate
        sample = amplitude * math.sin(2 * math.pi * frequency * t)
        
        # Convert to 16-bit signed integer
        sample_int = int(sample * 32767)
        
        # Pack as little-endian signed 16-bit
        audio_data.extend(struct.pack('<h', sample_int))
    
    return bytes(audio_data)

def generate_chirp(start_freq=200, end_freq=800, duration=3.0, sample_rate=24000, amplitude=0.3):
    """
    Generate a frequency sweep (chirp) from start_freq to end_freq
    """
    samples = int(duration * sample_rate)
    audio_data = bytearray()
    
    for i in range(samples):
        # Calculate current frequency (linear sweep)
        t = i / sample_rate
        progress = t / duration
        current_freq = start_freq + (end_freq - start_freq) * progress
        
        # Generate sine wave at current frequency
        sample = amplitude * math.sin(2 * math.pi * current_freq * t)
        
        # Convert to 16-bit signed integer
        sample_int = int(sample * 32767)
        
        # Pack as little-endian signed 16-bit
        audio_data.extend(struct.pack('<h', sample_int))
    
    return bytes(audio_data)

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
    """Run audio output tests"""
    print("🎵 Starting Audio Output Test")
    print(f"📊 Configuration:")
    print(f"   - Sample Rate: {OUT_SR} Hz")
    print(f"   - Output Device: {OUT_DEVICE or 'default'}")
    print()
    
    # Test 1: Simple tone (440 Hz A note)
    print("🎵 Test 1: Playing 440 Hz tone for 2 seconds...")
    tone_data = generate_tone(frequency=440, duration=2.0, sample_rate=OUT_SR)
    play_audio(tone_data)
    time.sleep(0.5)
    
    # Test 2: Higher frequency tone
    print("🎵 Test 2: Playing 800 Hz tone for 2 seconds...")
    tone_data = generate_tone(frequency=800, duration=2.0, sample_rate=OUT_SR)
    play_audio(tone_data)
    time.sleep(0.5)
    
    # Test 3: Frequency sweep (chirp)
    print("🎵 Test 3: Playing frequency sweep from 200 Hz to 800 Hz for 3 seconds...")
    chirp_data = generate_chirp(start_freq=200, end_freq=800, duration=3.0, sample_rate=OUT_SR)
    play_audio(chirp_data)
    time.sleep(0.5)
    
    # Test 4: Lower frequency tone
    print("🎵 Test 4: Playing 220 Hz tone for 2 seconds...")
    tone_data = generate_tone(frequency=220, duration=2.0, sample_rate=OUT_SR)
    play_audio(tone_data)
    
    print("🎵 Audio output test completed!")

if __name__ == "__main__":
    try:
        test_audio_output()
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"❌ Test failed: {e}")

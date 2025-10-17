#!/usr/bin/env python3
"""
Simple audio test for Raspberry Pi - basic tone generation
"""

import subprocess
import time
import struct
import math

def generate_tone(frequency=440, duration=2.0, sample_rate=22050, amplitude=0.3):
    """Generate a simple sine wave tone"""
    samples = int(duration * sample_rate)
    audio_data = bytearray()
    
    for i in range(samples):
        t = i / sample_rate
        sample = amplitude * math.sin(2 * math.pi * frequency * t)
        sample_int = int(sample * 32767)
        audio_data.extend(struct.pack('<h', sample_int))
    
    return bytes(audio_data)

def test_basic_audio():
    """Test basic audio output with different configurations"""
    print("🔊 Testing basic audio output...")
    
    # Test 1: Default device, 22kHz
    print("Test 1: Default device, 22kHz, 440Hz tone")
    tone_data = generate_tone(frequency=440, duration=2.0, sample_rate=22050)
    
    try:
        process = subprocess.Popen(
            ["aplay", "-t", "raw", "-f", "S16_LE", "-r", "22050", "-c", "1"],
            stdin=subprocess.PIPE
        )
        process.stdin.write(tone_data)
        process.stdin.close()
        process.wait()
        print("✅ Test 1 completed")
    except Exception as e:
        print(f"❌ Test 1 failed: {e}")
    
    time.sleep(1)
    
    # Test 2: plughw:0,0 device, 22kHz
    print("Test 2: plughw:0,0 device, 22kHz, 440Hz tone")
    try:
        process = subprocess.Popen(
            ["aplay", "-t", "raw", "-f", "S16_LE", "-r", "22050", "-c", "1", "-D", "plughw:0,0"],
            stdin=subprocess.PIPE
        )
        process.stdin.write(tone_data)
        process.stdin.close()
        process.wait()
        print("✅ Test 2 completed")
    except Exception as e:
        print(f"❌ Test 2 failed: {e}")
    
    time.sleep(1)
    
    # Test 3: plughw:0,0 device, 44.1kHz
    print("Test 3: plughw:0,0 device, 44.1kHz, 440Hz tone")
    tone_data_44k = generate_tone(frequency=440, duration=2.0, sample_rate=44100)
    try:
        process = subprocess.Popen(
            ["aplay", "-t", "raw", "-f", "S16_LE", "-r", "44100", "-c", "1", "-D", "plughw:0,0"],
            stdin=subprocess.PIPE
        )
        process.stdin.write(tone_data_44k)
        process.stdin.close()
        process.wait()
        print("✅ Test 3 completed")
    except Exception as e:
        print(f"❌ Test 3 failed: {e}")
    
    time.sleep(1)
    
    # Test 4: Different frequency
    print("Test 4: plughw:0,0 device, 22kHz, 800Hz tone")
    tone_data_800 = generate_tone(frequency=800, duration=2.0, sample_rate=22050)
    try:
        process = subprocess.Popen(
            ["aplay", "-t", "raw", "-f", "S16_LE", "-r", "22050", "-c", "1", "-D", "plughw:0,0"],
            stdin=subprocess.PIPE
        )
        process.stdin.write(tone_data_800)
        process.stdin.close()
        process.wait()
        print("✅ Test 4 completed")
    except Exception as e:
        print(f"❌ Test 4 failed: {e}")

if __name__ == "__main__":
    test_basic_audio()

#!/usr/bin/env python3
# Test script for ElevenLabs audio setup

import subprocess
import sys
import os

def test_audio_devices():
    """Test audio device availability"""
    print("🔊 Testing audio devices...")
    
    # Test mpg123
    try:
        result = subprocess.run(['mpg123', '--version'], capture_output=True, text=True)
        print(f"✅ mpg123 available: {result.stdout.strip()}")
    except FileNotFoundError:
        print("❌ mpg123 not found - run: sudo apt-get install mpg123")
        return False
    
    # Test aplay
    try:
        result = subprocess.run(['aplay', '-l'], capture_output=True, text=True)
        print(f"✅ aplay available")
        print("Available playback devices:")
        print(result.stdout)
    except FileNotFoundError:
        print("❌ aplay not found - run: sudo apt-get install alsa-utils")
        return False
    
    # Test arecord
    try:
        result = subprocess.run(['arecord', '-l'], capture_output=True, text=True)
        print(f"✅ arecord available")
        print("Available capture devices:")
        print(result.stdout)
    except FileNotFoundError:
        print("❌ arecord not found - run: sudo apt-get install alsa-utils")
        return False
    
    return True

def test_mpg123_device():
    """Test mpg123 with specific device"""
    print("\n🔊 Testing mpg123 with Respeaker device...")
    
    # Test with plughw:3,0 (Respeaker)
    try:
        cmd = ['mpg123', '-q', '-t', '-a', 'plughw:3,0', '/dev/null']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✅ mpg123 works with plughw:3,0")
        else:
            print(f"⚠️  mpg123 returned code {result.returncode} with plughw:3,0")
            print(f"Error: {result.stderr}")
    except Exception as e:
        print(f"❌ Error testing mpg123: {e}")

if __name__ == "__main__":
    print("🎵 ElevenLabs Audio Setup Test")
    print("=" * 40)
    
    if test_audio_devices():
        test_mpg123_device()
        print("\n✅ Audio setup test completed!")
        print("You can now run: sudo python3 solstis_elevenlabs_flow.py")
    else:
        print("\n❌ Audio setup issues detected. Please install missing packages.")
        sys.exit(1)

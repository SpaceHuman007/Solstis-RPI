#!/usr/bin/env python3
# Audio debugging script for ElevenLabs

import subprocess
import sys
import os

def test_mpg123_devices():
    """Test mpg123 with different audio devices"""
    print("🔊 Testing mpg123 with different audio devices...")
    
    devices_to_test = [
        'default',
        'plughw:3,0',
        'plughw:0,0',  # Headphones
        'plughw:1,0',  # HDMI
        'plughw:2,0'   # HDMI
    ]
    
    for device in devices_to_test:
        print(f"\n🎵 Testing device: {device}")
        try:
            # Test with a simple command that should work
            cmd = ['mpg123', '-q', '-t', '-a', device, '/dev/null']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                print(f"✅ {device}: Works")
            else:
                print(f"❌ {device}: Failed (code {result.returncode})")
                if result.stderr:
                    print(f"   Error: {result.stderr.strip()}")
                    
        except subprocess.TimeoutExpired:
            print(f"⏰ {device}: Timeout")
        except Exception as e:
            print(f"💥 {device}: Exception - {e}")

def test_audio_devices():
    """List available audio devices"""
    print("🔊 Available audio devices:")
    
    try:
        result = subprocess.run(['aplay', '-l'], capture_output=True, text=True)
        print("Playback devices:")
        print(result.stdout)
    except Exception as e:
        print(f"Error listing playback devices: {e}")
    
    try:
        result = subprocess.run(['arecord', '-l'], capture_output=True, text=True)
        print("Capture devices:")
        print(result.stdout)
    except Exception as e:
        print(f"Error listing capture devices: {e}")

def test_simple_playback():
    """Test simple audio playback"""
    print("\n🎵 Testing simple audio playback...")
    
    # Create a simple test tone using sox if available
    try:
        # Generate a 1-second 440Hz tone
        cmd = ['sox', '-n', '-r', '44100', '-b', '16', 'test_tone.wav', 'synth', '1', 'sine', '440']
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Try to play it with different methods
        methods = [
            ['aplay', 'test_tone.wav'],
            ['aplay', '-D', 'default', 'test_tone.wav'],
            ['aplay', '-D', 'plughw:0,0', 'test_tone.wav'],
            ['mpg123', '-q', '-a', 'default', 'test_tone.wav'],
            ['mpg123', '-q', '-a', 'plughw:0,0', 'test_tone.wav']
        ]
        
        for method in methods:
            try:
                print(f"Testing: {' '.join(method)}")
                result = subprocess.run(method, capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    print(f"✅ {' '.join(method)}: Success")
                else:
                    print(f"❌ {' '.join(method)}: Failed ({result.returncode})")
            except Exception as e:
                print(f"💥 {' '.join(method)}: {e}")
        
        # Clean up
        os.remove('test_tone.wav')
        
    except FileNotFoundError:
        print("sox not available, skipping tone test")
    except Exception as e:
        print(f"Error creating test tone: {e}")

if __name__ == "__main__":
    print("🎵 ElevenLabs Audio Debug Tool")
    print("=" * 40)
    
    test_audio_devices()
    test_mpg123_devices()
    test_simple_playback()
    
    print("\n✅ Audio debugging completed!")

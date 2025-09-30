#!/usr/bin/env python3
"""
Test script for noise adaptation settings
Run this to see how the system detects your background noise level
"""

import os
import sys
import time
import subprocess
import struct
import math

# Add the current directory to Python path to import from solstis_elevenlabs_flow
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the speech detection functions
from solstis_elevenlabs_flow import (
    calculate_rms, 
    measure_noise_floor, 
    spawn_arecord,
    NOISE_SAMPLES_COUNT,
    NOISE_MULTIPLIER,
    MIN_SPEECH_THRESHOLD,
    MAX_SPEECH_THRESHOLD
)

def test_noise_adaptation():
    """Test noise adaptation with current microphone setup"""
    
    print("🔊 Testing Noise Adaptation")
    print("=" * 50)
    
    # Get microphone device (same as main script)
    MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
    
    print(f"Microphone: {MIC_DEVICE}")
    print(f"Noise samples: {NOISE_SAMPLES_COUNT}")
    print(f"Noise multiplier: {NOISE_MULTIPLIER}x")
    print(f"Threshold range: {MIN_SPEECH_THRESHOLD} - {MAX_SPEECH_THRESHOLD}")
    print()
    
    try:
        # Start audio recording
        print("🎤 Starting audio capture...")
        arec = spawn_arecord(16000, MIC_DEVICE)  # 16kHz sample rate
        
        # Measure noise floor
        print("🔊 Measuring background noise...")
        print("(Please stay quiet for a few seconds)")
        print()
        
        adaptive_threshold = measure_noise_floor(arec, 512)  # 512 bytes per frame
        
        print()
        print("📊 Results:")
        print(f"   Adaptive threshold: {adaptive_threshold:.1f} RMS")
        print()
        
        # Test real-time detection
        print("🎯 Testing real-time speech detection...")
        print("(Speak normally, then stay quiet)")
        print("Press Ctrl+C to stop")
        print()
        
        frame_bytes = 512
        speech_detected_count = 0
        silence_count = 0
        
        try:
            while True:
                chunk = arec.stdout.read(frame_bytes)
                if not chunk:
                    break
                
                rms = calculate_rms(chunk)
                is_speech = rms > adaptive_threshold
                
                if is_speech:
                    speech_detected_count += 1
                    silence_count = 0
                    status = "🗣️  SPEECH"
                else:
                    silence_count += 1
                    speech_detected_count = 0
                    status = "🔇 silence"
                
                # Show status every 10 frames to avoid spam
                if (speech_detected_count + silence_count) % 10 == 0:
                    print(f"RMS: {rms:6.1f} | Threshold: {adaptive_threshold:6.1f} | {status}")
                
                time.sleep(0.01)  # Small delay to avoid overwhelming output
                
        except KeyboardInterrupt:
            print("\n🛑 Test stopped by user")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        try:
            if 'arec' in locals():
                arec.terminate()
        except:
            pass

if __name__ == "__main__":
    test_noise_adaptation()

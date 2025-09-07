#!/usr/bin/env python3
# Simple wake word test

import os
from dotenv import load_dotenv

load_dotenv(override=True)

WAKEWORD = os.getenv("WAKEWORD", "hello")

def test_wake_word():
    try:
        from respeaker import Microphone
        print(f"Testing wake word detection for: '{WAKEWORD}'")
        print("Say the wake word clearly...")
        print("Press Ctrl+C to stop")
        
        mic = Microphone()
        count = 0
        while True:
            count += 1
            if count % 50 == 0:  # Print every 50 attempts
                print(f"\nStill listening... (attempt {count})")
            
            try:
                if mic.wakeup(WAKEWORD):
                    print(f"\n✅ Wake word '{WAKEWORD}' detected!")
                    break
                else:
                    print(".", end="", flush=True)
            except Exception as e:
                print(f"\nError in wakeup: {e}")
                break
                
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Check if ReSpeaker is properly installed")
        print("2. Check if pocketsphinx is installed")
        print("3. Check audio devices: arecord -l")
        print("4. Test microphone: arecord -D plughw:CARD=seeed2micvoicec,DEV=0 -r 16000 -c 1 -f S16_LE -t wav -d 3 test.wav")

if __name__ == "__main__":
    test_wake_word()

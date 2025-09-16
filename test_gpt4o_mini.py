#!/usr/bin/env python3
# Test script for GPT-4o mini implementation

import os
from dotenv import load_dotenv
import openai

load_dotenv()

def test_openai_connection():
    """Test OpenAI API connection"""
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Test chat completion
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello, this is a test."}],
            max_tokens=50
        )
        
        print("✅ Chat completion test passed")
        print(f"Response: {response.choices[0].message.content}")
        
        # Test TTS
        tts_response = client.audio.speech.create(
            model="tts-1",
            voice="nova",
            input="Hello, this is a test of text to speech.",
            response_format="pcm"
        )
        
        print("✅ TTS test passed")
        print(f"Audio data length: {len(tts_response.content)} bytes")
        
        return True
        
    except Exception as e:
        print(f"❌ OpenAI API test failed: {e}")
        return False

def test_whisper():
    """Test Whisper transcription (requires audio file)"""
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Create a simple test audio file (silence)
        import wave
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            with wave.open(temp_file.name, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                # Write 1 second of silence
                wav_file.writeframes(b'\x00' * 32000)
            
            with open(temp_file.name, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )
            
            os.unlink(temp_file.name)
        
        print("✅ Whisper transcription test passed")
        print(f"Transcript: '{transcript}'")
        
        return True
        
    except Exception as e:
        print(f"❌ Whisper test failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing GPT-4o mini implementation...")
    print("=" * 50)
    
    # Check environment variables
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY not set in environment")
        exit(1)
    
    print("✅ Environment variables loaded")
    
    # Test OpenAI API
    if test_openai_connection():
        print("\n✅ All OpenAI API tests passed!")
    else:
        print("\n❌ OpenAI API tests failed!")
        exit(1)
    
    # Test Whisper
    if test_whisper():
        print("\n✅ All Whisper tests passed!")
    else:
        print("\n❌ Whisper tests failed!")
        exit(1)
    
    print("\n🎉 All tests passed! The GPT-4o mini implementation is ready to use.")

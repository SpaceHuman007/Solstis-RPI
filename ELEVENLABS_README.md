# Solstis ElevenLabs Voice Assistant

This is a version of the Solstis voice assistant that uses ElevenLabs for both Text-to-Speech (TTS) and Speech-to-Text (STT) instead of OpenAI's services.

## Key Changes from Original

### ElevenLabs Integration
- **TTS**: Uses ElevenLabs API instead of OpenAI TTS
- **STT**: Uses ElevenLabs Speech-to-Text API instead of OpenAI Whisper
- **Chat**: Still uses OpenAI GPT for conversation processing

### Configuration Variables

Add these environment variables to your `.env` file:

```bash
# ElevenLabs Configuration
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
ELEVENLABS_VOICE_ID=pNInz6obpgDQGcFmaJgB  # Default: Adam voice
ELEVENLABS_MODEL_ID=eleven_monolingual_v1  # Default model

# OpenAI Configuration (still needed for chat)
OPENAI_API_KEY=your_openai_api_key_here
MODEL=gpt-4-turbo  # Chat model

# Picovoice Configuration (unchanged)
PICOVOICE_ACCESS_KEY=your_picovoice_access_key_here
SOLSTIS_WAKEWORD_PATH=Solstice_en_raspberry-pi_v3_0_0.ppn
STEP_COMPLETE_WAKEWORD_PATH=step-complete_en_raspberry-pi_v3_0_0.ppn

# Audio Configuration (unchanged)
MIC_DEVICE=plughw:3,0
OUT_SR=24000
USER_NAME=User

# LED and Reed Switch Configuration (unchanged)
LED_ENABLED=true
LED_COUNT=788
REED_SWITCH_ENABLED=true
REED_SWITCH_PIN=16
```

## ElevenLabs Voice Options

You can change the voice by updating `ELEVENLABS_VOICE_ID` in your `.env` file. Some popular voice IDs:

- **Adam** (default): `pNInz6obpgDQGcFmaJgB`
- **Antoni**: `ErXwobaYiN019PkySvjV`
- **Arnold**: `VR6AewLTigWG4xSOukaG`
- **Bella**: `EXAVITQu4vr4xnSDxMaL`
- **Domi**: `AZnzlk1XvdvUeBnXmlld`
- **Elli**: `MF3mGyEYCl7XYWbV9V6O`
- **Josh**: `TxGEqnHWrfWFTfGW9XjX`
- **Rachel**: `21m00Tcm4TlvDq8ikWAM`
- **Sam**: `yoZ06aMxZJJ28mfd3POQ`

## Quick Setup

1. **Install system dependencies:**
   ```bash
   chmod +x install_audio.sh
   ./install_audio.sh
   ```

2. **Install Python packages:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your .env file** with API keys (see Configuration section below)

## Usage

Run the ElevenLabs version:

```bash
sudo python3 solstis_elevenlabs_flow.py
```

## Features

- **High-quality TTS**: ElevenLabs provides more natural-sounding speech
- **Accurate STT**: ElevenLabs speech recognition with good accuracy
- **Same functionality**: All original features preserved (LED control, reed switch, wake words, etc.)
- **Medical kit assistance**: Same comprehensive medical kit item detection and LED highlighting

## Requirements

Install the required packages:

```bash
pip install requests pvporcupine python-dotenv
```

Install system audio packages:

```bash
sudo apt-get update
sudo apt-get install alsa-utils
```

Make sure you have:
- ElevenLabs API key
- OpenAI API key (for chat)
- Picovoice access key
- Wake word model files (.ppn files)

## Voice Volume Control

If some ElevenLabs voices are too quiet, you can adjust these environment variables:

```bash
# Voice settings for louder output
export ELEVENLABS_STABILITY=0.5          # Voice consistency (0.0-1.0)
export ELEVENLABS_SIMILARITY_BOOST=0.5   # Voice similarity (0.0-1.0) 
export ELEVENLABS_STYLE=0.0              # Style exaggeration (0.0-1.0)
export ELEVENLABS_SPEAKER_BOOST=true    # Boost speaker characteristics (true/false)
```

**For louder voices, try:**
- `ELEVENLABS_SPEAKER_BOOST=true` (enabled by default)
- `ELEVENLABS_SIMILARITY_BOOST=0.7` (higher = more distinctive/louder)
- `ELEVENLABS_STYLE=0.2` (slight style boost can increase volume)

**Alternative volume control methods:**
1. **System volume**: Use `alsamixer` or `pavucontrol` to increase system volume
2. **Audio device volume**: Some Respeaker devices have hardware volume controls
3. **Different voice**: Try different ElevenLabs voices - some are naturally louder
4. **Audio post-processing**: Add volume normalization in the audio pipeline

## Differences from OpenAI Version

1. **Audio Format**: ElevenLabs TTS uses Turbo v2.5 model with PCM format at 24kHz
2. **API Calls**: Uses REST API calls to ElevenLabs instead of OpenAI SDK
3. **Voice Quality**: Generally higher quality and more natural-sounding speech
4. **Cost**: ElevenLabs pricing may differ from OpenAI TTS pricing

## Troubleshooting

### Audio Issues
- **No audio playback**: Check that `aplay` is working (same as OpenAI version)
- **Audio device conflicts**: The system automatically avoids using the same device for input/output
- **STT not working**: Verify ElevenLabs API key and model_id parameter

### Debugging Tools
Run the audio debug script to diagnose issues:
```bash
python3 debug_audio.py
```

This will test:
- Available audio devices
- mpg123 compatibility with different devices
- Simple audio playback methods

If you need test audio files, create them with:
```bash
python3 create_test_audio.py
```

### Common Problems
- **Import errors**: Make sure all Python packages are installed
- **GPIO errors**: Run with `sudo` for GPIO access
- **Audio device busy**: Check if another process is using the audio device
- **aplay errors**: Usually indicates audio device conflicts or permissions
- **ElevenLabs API errors**: Ensure API key is valid and has sufficient credits
- **Voice ID issues**: Check that the voice ID exists and is accessible with your API key

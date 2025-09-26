# Solstis Voice Assistant Environment Configuration

This document describes all the environment variables you can configure for the Solstis voice assistant.

## Quick Setup

Create a `.env` file in your project root and add the variables you want to customize. All variables have sensible defaults.

## Configuration Sections

### PICOVOICE CONFIGURATION
```bash
# Get your access key from: https://console.picovoice.ai/
PICOVOICE_ACCESS_KEY=YOUR-PICOVOICE-ACCESSKEY-HERE

# Wake word model file paths (relative to script location)
SOLSTIS_WAKEWORD_PATH=Solstice_en_raspberry-pi_v3_0_0.ppn
STEP_COMPLETE_WAKEWORD_PATH=step-complete_en_raspberry-pi_v3_0_0.ppn
```

### AUDIO DEVICE CONFIGURATION
```bash
# Microphone device (use 'arecord -l' to list available devices)
MIC_DEVICE=plughw:3,0
MIC_SR=16000

# Audio output device (leave empty for default)
AUDIO_DEVICE=
OUT_SR=24000
```

### OPENAI CONFIGURATION
```bash
# Get your API key from: https://platform.openai.com/api-keys
OPENAI_API_KEY=your-openai-api-key-here

# Model selection
MODEL=gpt-4-turbo
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=shimmer
```

### SPEECH DETECTION & NOISE FILTERING
```bash
# Base RMS threshold for speech detection (higher = less sensitive to noise)
# Default: 800 (increased from 500 for better noise rejection)
SPEECH_THRESHOLD=800

# Silence detection settings
SILENCE_DURATION=2.0
QUICK_SILENCE_AFTER_SPEECH=0.6
MIN_SPEECH_DURATION=0.5
MAX_SPEECH_DURATION=15.0

# Noise filtering settings (NEW - helps reduce background noise sensitivity)
NOISE_SAMPLES=10              # Number of audio samples to calculate ambient noise level
MIN_SPEECH_FRAMES=3           # Minimum consecutive frames of speech required to trigger
NOISE_MULTIPLIER=2.5          # Multiplier above ambient noise for speech detection
```

### CONVERSATION TIMEOUTS
```bash
T_SHORT=30.0      # Short timeout for initial responses
T_NORMAL=10.0      # Normal timeout for conversation
T_LONG=15.0       # Long timeout for step completion
```

### LED CONTROL CONFIGURATION
```bash
LED_ENABLED=true
LED_COUNT=788
LED_PIN=13
LED_FREQ_HZ=800000
LED_DMA=10
LED_BRIGHTNESS=70
LED_INVERT=false
LED_CHANNEL=1
LED_DURATION=10.0

# LED pulsing (speaking indicator) - Solstis middle section
SPEAK_LEDS_START1=643
SPEAK_LEDS_END1=663
SPEAK_LEDS_START2=696
SPEAK_LEDS_END2=727
SPEAK_COLOR_R=0
SPEAK_COLOR_G=180
SPEAK_COLOR_B=255
```

### USER CONFIGURATION
```bash
USER_NAME=User
```

## Noise Filtering Tuning Guide

If you're still experiencing background noise issues, try these adjustments:

### For Very Noisy Environments:
```bash
SPEECH_THRESHOLD=1200         # Increase base threshold
MIN_SPEECH_FRAMES=5           # Require more sustained speech
NOISE_MULTIPLIER=3.5          # Stricter noise filtering
NOISE_SAMPLES=8               # Faster noise adaptation
```

### For Quiet Environments:
```bash
SPEECH_THRESHOLD=600          # Decrease base threshold
MIN_SPEECH_FRAMES=2           # Allow shorter speech bursts
NOISE_MULTIPLIER=2.0          # More lenient noise filtering
```

### For Very Quiet Environments:
```bash
SPEECH_THRESHOLD=400          # Very sensitive threshold
MIN_SPEECH_FRAMES=1           # Single frame detection
NOISE_MULTIPLIER=1.5          # Minimal noise filtering
```

## Troubleshooting

### Speech Detection Issues:
- **Too sensitive to noise**: Increase `SPEECH_THRESHOLD`, `MIN_SPEECH_FRAMES`, or `NOISE_MULTIPLIER`
- **Not detecting speech**: Decrease `SPEECH_THRESHOLD`, `MIN_SPEECH_FRAMES`, or `NOISE_MULTIPLIER`
- **Slow response**: Decrease `NOISE_SAMPLES` for faster adaptation

### Audio Device Issues:
- **No microphone input**: Check `MIC_DEVICE` with `arecord -l`
- **No audio output**: Check `AUDIO_DEVICE` with `aplay -l`
- **Audio conflicts**: Ensure `MIC_DEVICE` and `AUDIO_DEVICE` are different

### Performance Issues:
- **High CPU usage**: Increase `NOISE_SAMPLES` to reduce calculation frequency
- **Memory usage**: Decrease `LED_COUNT` if not using full LED strip
- **Slow wake word detection**: Check `PICOVOICE_ACCESS_KEY` is valid

## Example .env File

```bash
# Required settings
PICOVOICE_ACCESS_KEY=your-actual-picovoice-key-here
OPENAI_API_KEY=your-actual-openai-key-here

# Audio settings for your setup
MIC_DEVICE=plughw:3,0
AUDIO_DEVICE=plughw:2,0

# Noise filtering for noisy environment
SPEECH_THRESHOLD=1000
MIN_SPEECH_FRAMES=4
NOISE_MULTIPLIER=3.0

# User customization
USER_NAME=Jake
```

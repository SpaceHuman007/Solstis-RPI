# Solstis Voice Assistant for Raspberry Pi 4

A voice-activated medical assistant that listens for wake words and provides real-time medical guidance using OpenAI's Realtime API.

## �� Quick Start

1. **Clone and setup:**
   ```bash
   git clone <your-repo>
   cd solstis-voice-pi
   chmod +x *.sh
   ```

2. **Install dependencies:**
   ```bash
   ./install.sh
   ```

3. **Configure:**
   ```bash
   nano .env  # Add your OpenAI API key
   ```

4. **Test audio:**
   ```bash
   ./test_audio.sh
   ```

5. **Start Solstis:**
   ```bash
   ./start_solstis.sh
   ```

## 📋 Requirements

- Raspberry Pi 4
- ReSpeaker microphone array (or compatible USB mic)
- Speakers/headphones
- OpenAI API key
- Internet connection

## ⚙️ Configuration

Edit `.env` file:

```bash
# Required
OPENAI_API_KEY=your_api_key_here

# Optional (defaults shown)
AUDIO_DEVICE=plughw:1,0
OUT_SR=24000
VOICE=verse
WAKEWORD=solstis
KIT_TYPE=standard
USER_NAME=User
```

## 🎤 Kit Types

- `standard` - General first aid kit
- `college` - Student-focused medical supplies
- `oc_standard` - Occupational safety kit
- `oc_vehicle` - Vehicle emergency kit

## 🔧 Troubleshooting

**Audio issues:**
```bash
./test_audio.sh          # Test audio setup
aplay -l                 # List playback devices
arecord -l               # List recording devices
```

**Service management:**
```bash
sudo systemctl start solstis    # Start as service
sudo systemctl status solstis   # Check status
sudo journalctl -u solstis -f   # View logs
```

**Common fixes:**
- Audio not working: Check `AUDIO_DEVICE` in `.env`
- Wake word not detected: Adjust microphone sensitivity
- No response: Verify OpenAI API key and internet connection

## 📁 Files

- `solstis_voice_pi.py` - Main Python application
- `install.sh` - Installation script
- `setup_audio.sh` - Audio configuration
- `test_audio.sh` - Audio testing
- `setup_service.sh` - System service setup
- `start_solstis.sh` - Startup script
- `.env` - Configuration file

## 🎯 Usage

1. Say the wake word: **"Solstis"**
2. Wait for confirmation beep
3. Describe your medical situation
4. Follow Solstis's step-by-step guidance

Example: *"Solstis, I cut my finger with a kitchen knife and it's bleeding a lot."*

## 🚨 Emergency Protocol

Solstis will always:
- Assess for life-threatening emergencies first
- Guide you to call 911 if needed
- Provide step-by-step first aid instructions
- Use only items from your configured kit

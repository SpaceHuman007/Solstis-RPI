#!/bin/bash
# Solstis Voice Assistant Installation Script for Raspberry Pi 4

echo "🩺 Installing Solstis Voice Assistant for Raspberry Pi 4..."

# Update system packages
echo "📦 Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install audio dependencies
echo "🎵 Installing audio dependencies..."
sudo apt-get install -y alsa-utils pulseaudio pulseaudio-utils
sudo apt-get install -y python3-pip python3-venv python3-dev

# Install ReSpeaker dependencies
echo "🎤 Installing ReSpeaker dependencies..."
sudo apt-get install -y pocketsphinx pocketsphinx-en-us
sudo apt-get install -y python3-respeaker

# Install Python packages
echo "🐍 Installing Python packages..."
pip3 install python-dotenv websockets respeaker

# Set up audio permissions
echo "🔊 Setting up audio permissions..."
sudo usermod -a -G audio $USER

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file template..."
    cat > .env << EOF
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key_here

# Audio Configuration
AUDIO_DEVICE=plughw:1,0
OUT_SR=24000
VOICE=verse

# Wake Word Configuration
WAKEWORD=solstis

# Kit Configuration
KIT_TYPE=standard
USER_NAME=User

# Model Configuration
MODEL=gpt-4o-realtime-preview
EOF
    echo "⚠️  Please edit .env file and add your OpenAI API key!"
fi

# Create startup script
echo "🚀 Creating startup script..."
cat > start_solstis.sh << 'EOF'
#!/bin/bash
# Solstis Voice Assistant Startup Script

# Change to script directory
cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Start Solstis
python3 solstis_voice_pi.py
EOF

chmod +x start_solstis.sh

echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env file and add your OpenAI API key"
echo "2. Test audio: aplay /usr/share/sounds/alsa/Front_Left.wav"
echo "3. Run: ./start_solstis.sh"
echo ""
echo "For troubleshooting, check:"
echo "- Audio devices: aplay -l"
echo "- Microphone: arecord -l"
echo "- Audio groups: groups $USER"
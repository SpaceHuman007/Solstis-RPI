#!/bin/bash
# Solstis Voice Assistant Startup Script

echo "🩺 Starting Solstis Voice Assistant..."

# Change to script directory
cd "$(dirname "$0")"

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "Please run install.sh first to create the .env file."
    exit 1
fi

# Check if OpenAI API key is set
if grep -q "your_openai_api_key_here" .env; then
    echo "❌ Please edit .env file and add your OpenAI API key!"
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Check if required files exist
if [ ! -f FullCodeTest.py ]; then
    echo "❌ solstis_voice_pi.py not found!"
    echo "Please make sure the Python script is in the same directory."
    exit 1
fi

# Test audio before starting
echo "🔊 Testing audio..."
if ! aplay /usr/share/sounds/alsa/Front_Left.wav >/dev/null 2>&1; then
    echo "⚠️  Audio test failed - continuing anyway..."
fi

# Start Solstis
echo "🚀 Starting Solstis Voice Assistant..."
echo "Kit Type: $KIT_TYPE"
echo "User: $USER_NAME"
echo "Wake Word: $WAKEWORD"
echo "Voice: $VOICE"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python3 FullCodeTest.py
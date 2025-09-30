#!/bin/bash
# Quick installation script for ElevenLabs system dependencies

echo "🔊 Installing audio packages for ElevenLabs..."

# Install mpg123 and alsa-utils
sudo apt-get update
sudo apt-get install -y mpg123 alsa-utils

# Verify installation
if command -v mpg123 &> /dev/null; then
    echo "✅ mpg123 installed successfully"
else
    echo "❌ mpg123 installation failed"
    exit 1
fi

if command -v aplay &> /dev/null; then
    echo "✅ aplay available"
else
    echo "❌ aplay not found"
    exit 1
fi

echo ""
echo "🎉 Audio packages installed successfully!"
echo "You can now run: sudo python3 solstis_elevenlabs_flow.py"

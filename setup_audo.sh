#!/bin/bash
# Audio Setup Script for Solstis Voice Assistant

echo "🔊 Setting up audio for Solstis Voice Assistant..."

# List available audio devices
echo "📋 Available audio devices:"
echo "Playback devices:"
aplay -l
echo ""
echo "Recording devices:"
arecord -l

# Test audio output
echo "🎵 Testing audio output..."
if command -v aplay &> /dev/null; then
    echo "Playing test sound..."
    aplay /usr/share/sounds/alsa/Front_Left.wav 2>/dev/null || echo "⚠️  Test sound not available"
else
    echo "❌ aplay not found"
fi

# Configure ALSA for better audio
echo "⚙️  Configuring ALSA..."
sudo tee /etc/asound.conf > /dev/null << 'EOF'
pcm.!default {
    type hw
    card 1
    device 0
}

ctl.!default {
    type hw
    card 1
}
EOF

# Add user to audio group
echo "👤 Adding user to audio group..."
sudo usermod -a -G audio $USER

echo "✅ Audio setup complete!"
echo ""
echo "You may need to log out and log back in for audio group changes to take effect."
echo "Test your setup with: ./test_audio.sh"
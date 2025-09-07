#!/bin/bash
# Audio Test Script for Solstis Voice Assistant

echo "🧪 Testing audio setup..."

# Test 1: List audio devices
echo "Test 1: Audio devices"
echo "Playback devices:"
aplay -l
echo ""
echo "Recording devices:"
arecord -l
echo ""

# Test 2: Test playback
echo "Test 2: Audio playback"
if aplay /usr/share/sounds/alsa/Front_Left.wav 2>/dev/null; then
    echo "✅ Playback working"
else
    echo "❌ Playback failed - check speakers/headphones"
fi
echo ""

# Test 3: Test recording
echo "Test 3: Audio recording (5 seconds)"
echo "Speak now..."
if timeout 5s arecord -f cd -t wav test_recording.wav 2>/dev/null; then
    echo "✅ Recording successful"
    echo "Playing back recording..."
    aplay test_recording.wav 2>/dev/null
    rm -f test_recording.wav
else
    echo "❌ Recording failed - check microphone"
fi
echo ""

# Test 4: Check audio groups
echo "Test 4: User audio groups"
echo "Current user groups:"
groups $USER
if groups $USER | grep -q audio; then
    echo "✅ User is in audio group"
else
    echo "❌ User not in audio group - run: sudo usermod -a -G audio $USER"
fi
echo ""

# Test 5: Test specific audio device
AUDIO_DEVICE=${AUDIO_DEVICE:-"plughw:1,0"}
echo "Test 5: Testing audio device: $AUDIO_DEVICE"
if timeout 3s arecord -D "$AUDIO_DEVICE" -f cd -t wav test_device.wav 2>/dev/null; then
    echo "✅ Audio device $AUDIO_DEVICE working"
    rm -f test_device.wav
else
    echo "❌ Audio device $AUDIO_DEVICE failed"
    echo "Try different device from aplay -l output"
fi

echo ""
echo "🎯 Audio test complete!"
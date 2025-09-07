#!/bin/bash
# Systemd Service Setup for Solstis Voice Assistant

echo "🔧 Setting up Solstis as a system service..."

# Get current directory
CURRENT_DIR=$(pwd)
USER_NAME=$(whoami)

# Create systemd service file
sudo tee /etc/systemd/system/solstis.service > /dev/null << EOF
[Unit]
Description=Solstis Voice Assistant
After=network.target sound.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/start_solstis.sh
Restart=always
RestartSec=10
Environment=PATH=/usr/bin:/usr/local/bin
Environment=PYTHONPATH=$CURRENT_DIR

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable solstis.service

echo "✅ Service created!"
echo ""
echo "Service commands:"
echo "  Start:   sudo systemctl start solstis"
echo "  Stop:    sudo systemctl stop solstis"
echo "  Status:  sudo systemctl status solstis"
echo "  Logs:    sudo journalctl -u solstis -f"
echo "  Enable:  sudo systemctl enable solstis"
echo "  Disable: sudo systemctl disable solstis"
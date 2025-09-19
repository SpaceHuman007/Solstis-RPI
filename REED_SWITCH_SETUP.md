# Reed Switch Setup Guide

This guide will help you connect and configure the Original Japan KOFU OKI Reed Switch to detect when the Solstis box is opened or closed.

## Hardware Setup

### Reed Switch Wiring
The reed switch has two wires:
- **Red wire**: Connect to GPIO pin 18 (or your chosen pin)
- **Black wire**: Connect to Ground (GND)

### Magnet Placement
- Place the magnet on the **lid** of the box
- Place the reed switch on the **base** of the box, aligned with the magnet
- When the box is **closed**, the magnet should be close to the reed switch (switch closed)
- When the box is **open**, the magnet should be away from the reed switch (switch open)

## Software Configuration

### Environment Variables
Add these to your `.env` file:

```bash
# Reed Switch Configuration
REED_SWITCH_ENABLED=true
REED_SWITCH_PIN=18
REED_SWITCH_DEBOUNCE_MS=100
```

### GPIO Pin Options
Common GPIO pins you can use:
- GPIO 18 (default)
- GPIO 23
- GPIO 24
- GPIO 25

## Testing

1. **Test the reed switch**:
   ```bash
   python3 test_reed_switch.py
   ```
   This will show you the current state of the reed switch in real-time.

2. **Run the main application**:
   ```bash
   python3 solstis_picovoice_gpt4o_mini.py
   ```

## How It Works

1. **Box Closed**: Magnet is near reed switch → Switch closed → GPIO reads LOW → Box state: CLOSED
2. **Box Open**: Magnet is away from reed switch → Switch open → GPIO reads HIGH → Box state: OPEN

### Behavior
- When the box **opens**: The opening message plays automatically
- When the box **closes**: The conversation resets and waits for the next opening
- The system continuously monitors the reed switch state

## Troubleshooting

### Reed Switch Not Working
1. Check wiring connections
2. Verify magnet placement
3. Test with the test script: `python3 test_reed_switch.py`
4. Check GPIO permissions (you may need to run with `sudo`)

### False Triggers
- Adjust the `REED_SWITCH_DEBOUNCE_MS` value (try 200ms or 500ms)
- Check magnet strength and positioning
- Ensure no other magnetic objects are interfering

### GPIO Permission Issues
If you get permission errors:
```bash
sudo usermod -a -G gpio $USER
```
Then logout and login again, or run with `sudo`.

## Safety Notes

- The reed switch is normally open (N/O), so it's safe if wiring breaks
- Use appropriate pull-up resistors (handled by GPIO.PUD_UP)
- Keep magnet away from electronics and credit cards

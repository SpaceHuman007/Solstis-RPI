#!/usr/bin/env python3
# Test script for reed switch functionality
# This script will help you verify that your reed switch is working correctly

import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# GPIO imports for reed switch
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available. Reed switch functionality disabled.")

# Reed switch config
REED_SWITCH_ENABLED = os.getenv("REED_SWITCH_ENABLED", "true").lower() == "true" and GPIO_AVAILABLE
REED_SWITCH_PIN = int(os.getenv("REED_SWITCH_PIN", "16"))  # GPIO pin connected to reed switch
REED_SWITCH_DEBOUNCE_MS = int(os.getenv("REED_SWITCH_DEBOUNCE_MS", "300"))  # Debounce time in milliseconds (increased for less sensitivity)
REED_SWITCH_CONFIRM_COUNT = int(os.getenv("REED_SWITCH_CONFIRM_COUNT", "3"))  # Number of consistent readings required
REED_SWITCH_POLL_INTERVAL = float(os.getenv("REED_SWITCH_POLL_INTERVAL", "0.2"))  # Polling interval in seconds (increased for less sensitivity)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def init_reed_switch():
    """Initialize the reed switch GPIO"""
    if not REED_SWITCH_ENABLED:
        log("Reed switch control disabled")
        return False
    
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(REED_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        log(f"Reed switch initialized on GPIO pin {REED_SWITCH_PIN}")
        return True
    except Exception as e:
        log(f"Failed to initialize reed switch: {e}")
        return False

def cleanup_reed_switch():
    """Clean up reed switch GPIO"""
    try:
        GPIO.cleanup(REED_SWITCH_PIN)
        log("Reed switch GPIO cleaned up")
    except Exception as e:
        log(f"Error cleaning up reed switch: {e}")

def read_reed_switch():
    """Read the current state of the reed switch with enhanced debouncing and confirmation"""
    if not REED_SWITCH_ENABLED:
        return False
    
    try:
        # Read multiple times to confirm the state (reduces false triggers)
        readings = []
        for i in range(REED_SWITCH_CONFIRM_COUNT):
            state = GPIO.input(REED_SWITCH_PIN)
            readings.append(state)
            if i < REED_SWITCH_CONFIRM_COUNT - 1:  # Don't sleep after the last reading
                time.sleep(REED_SWITCH_DEBOUNCE_MS / 1000.0)
        
        # Check if all readings are consistent
        if all(r == readings[0] for r in readings):
            # All readings are the same, return the confirmed state
            # Return True if box is open (HIGH), False if closed (LOW)
            return readings[0] == GPIO.HIGH
        else:
            # Readings are inconsistent, return the previous state or False
            log(f"⚠️  Inconsistent reed switch readings: {readings}")
            return False
        
    except Exception as e:
        log(f"Error reading reed switch: {e}")
        return False

def main():
    log("🔧 Reed Switch Test Starting...")
    log(f"Reed Switch: {'Enabled' if REED_SWITCH_ENABLED else 'Disabled'}")
    log(f"GPIO Pin: {REED_SWITCH_PIN}")
    log(f"Debounce: {REED_SWITCH_DEBOUNCE_MS}ms")
    log(f"Confirm Count: {REED_SWITCH_CONFIRM_COUNT} readings")
    log(f"Poll Interval: {REED_SWITCH_POLL_INTERVAL}s")
    log("📉 Sensitivity: REDUCED (less sensitive to false triggers)")
    
    if not REED_SWITCH_ENABLED:
        log("Reed switch is disabled. Check your GPIO installation.")
        return
    
    # Initialize reed switch
    if not init_reed_switch():
        log("Failed to initialize reed switch. Exiting.")
        return
    
    try:
        log("Reading reed switch state...")
        log("Press Ctrl+C to exit")
        log("")
        
        last_state = None
        while True:
            current_state = read_reed_switch()
            
            if current_state != last_state:
                if current_state:
                    log("📦 Box is OPEN (magnet absent)")
                else:
                    log("📦 Box is CLOSED (magnet present)")
                last_state = current_state
            
            time.sleep(REED_SWITCH_POLL_INTERVAL)  # Use configurable polling interval
            
    except KeyboardInterrupt:
        log("Test interrupted by user")
    finally:
        cleanup_reed_switch()
        log("Test complete")

if __name__ == "__main__":
    main()
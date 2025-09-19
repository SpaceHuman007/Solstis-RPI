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
REED_SWITCH_DEBOUNCE_MS = int(os.getenv("REED_SWITCH_DEBOUNCE_MS", "100"))  # Debounce time in milliseconds

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
    """Read the current state of the reed switch with debouncing"""
    if not REED_SWITCH_ENABLED:
        return False
    
    try:
        # Read the switch state (LOW = closed/magnet present, HIGH = open/magnet absent)
        # For normally open reed switch, LOW means box is closed, HIGH means box is open
        raw_state = GPIO.input(REED_SWITCH_PIN)
        
        # Add simple debouncing by reading multiple times
        time.sleep(REED_SWITCH_DEBOUNCE_MS / 1000.0)
        debounced_state = GPIO.input(REED_SWITCH_PIN)
        
        # Return True if box is open (HIGH), False if closed (LOW)
        return debounced_state == GPIO.HIGH
        
    except Exception as e:
        log(f"Error reading reed switch: {e}")
        return False

def main():
    log("🔧 Reed Switch Test Starting...")
    log(f"Reed Switch: {'Enabled' if REED_SWITCH_ENABLED else 'Disabled'}")
    log(f"GPIO Pin: {REED_SWITCH_PIN}")
    log(f"Debounce: {REED_SWITCH_DEBOUNCE_MS}ms")
    
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
            
            time.sleep(0.1)  # Check every 100ms
            
    except KeyboardInterrupt:
        log("Test interrupted by user")
    finally:
        cleanup_reed_switch()
        log("Test complete")

if __name__ == "__main__":
    main()
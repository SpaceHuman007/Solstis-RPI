#!/usr/bin/env python3
# LED Test Script for Solstis Kit
# This script helps you test and verify LED mappings for each kit item

import time
from rpi_ws281x import *

# LED strip configuration (same as your main script)
LED_COUNT = 788
LED_PIN = 13
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 30
LED_INVERT = False
LED_CHANNEL = 1

# LED mapping for kit items (same as in main script)
LED_MAPPINGS = {
    "band-aids": (45, 100),
    "gauze pads": (26, 50),
    "roll gauze": (51, 75),
    "abd pad": (76, 100),
    "medical tape": (101, 125),
    "antibiotic ointment": (126, 150),
    "tweezers": (151, 175),
    "trauma shears": (176, 200),
    "quickclot gauze": (201, 225),
    "hemostatic wipe": (201, 225),
    "burn gel dressing": (226, 250),
    "burn spray": (251, 275),
    "sting bite relief": (276, 300),
    "eye wash bottle": (301, 325),
    "glucose gel": (326, 350),
    "electrolyte powder": (351, 375),
    "ace bandage": (376, 400),
    "cold pack": (401, 425),
    "triangle bandage": (426, 450),
}

def init_led_strip():
    """Initialize the LED strip"""
    time.sleep(2.0)  # Give LEDs power time before driving DIN
    strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA,
                              LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    strip.begin()
    return strip

def clear_all_leds(strip):
    """Turn off all LEDs"""
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, 0)
    strip.show()

def light_item_leds(strip, item_name, color=(0, 240, 255)):
    """Light up LEDs for a specific item"""
    if item_name not in LED_MAPPINGS:
        print(f"No LED mapping found for item: {item_name}")
        return
    
    start, end = LED_MAPPINGS[item_name]
    print(f"Lighting LEDs {start}-{end} for item: {item_name}")
    
    # Clear all LEDs first
    clear_all_leds(strip)
    
    # Light up the specific range
    for i in range(start, end + 1):
        if i < strip.numPixels():
            strip.setPixelColor(i, Color(*color))
    
    strip.show()

def test_all_items(strip):
    """Test all items one by one"""
    print("Testing all kit items...")
    
    for item_name, (start, end) in LED_MAPPINGS.items():
        print(f"\nTesting: {item_name} (LEDs {start}-{end})")
        light_item_leds(strip, item_name)
        time.sleep(3)  # Show for 3 seconds
        clear_all_leds(strip)
        time.sleep(1)  # Brief pause between items

def main():
    print("🩺 Solstis LED Test Script")
    print("=" * 50)
    
    # Initialize LED strip
    try:
        strip = init_led_strip()
        print(f"LED strip initialized: {LED_COUNT} pixels")
    except Exception as e:
        print(f"Failed to initialize LED strip: {e}")
        return
    
    # Clear all LEDs first
    clear_all_leds(strip)
    
    while True:
        print("\nOptions:")
        print("1. Test all items sequentially")
        print("2. Test specific item")
        print("3. Show LED mapping")
        print("4. Exit")
        
        choice = input("\nEnter your choice (1-4): ").strip()
        
        if choice == "1":
            test_all_items(strip)
        
        elif choice == "2":
            print("\nAvailable items:")
            for i, item in enumerate(LED_MAPPINGS.keys(), 1):
                print(f"{i}. {item}")
            
            try:
                item_choice = int(input("\nEnter item number: ")) - 1
                items = list(LED_MAPPINGS.keys())
                if 0 <= item_choice < len(items):
                    item_name = items[item_choice]
                    light_item_leds(strip, item_name)
                    input("Press Enter to turn off LEDs...")
                    clear_all_leds(strip)
                else:
                    print("Invalid item number")
            except ValueError:
                print("Invalid input")
        
        elif choice == "3":
            print("\nLED Mappings:")
            for item, (start, end) in LED_MAPPINGS.items():
                print(f"{item}: LEDs {start}-{end}")
        
        elif choice == "4":
            break
        
        else:
            print("Invalid choice")
    
    # Clean up
    clear_all_leds(strip)
    print("LED test complete!")

if __name__ == "__main__":
    main()

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

# LED mapping for kit items with multiple ranges per item
LED_MAPPINGS = {
    "solstis middle": [(643, 663), (696, 727)],
    "quickclot": [(62, 86), (270, 293), (264, 264)],
    "burn spray": [(41, 62), (234, 269), (226, 226)],
    "burn dressing": [(241, 262), (220, 226), (601, 629)],
    "4 gauze pads": [(581, 623), (636, 642), (720, 727)],
    "cold pack": [(706, 719), (199, 212), (581, 594), (553, 567)],
    "electrolyte": [(691, 705), (523, 567)],
    "antibiotic": [(493, 548), (186, 193)],
    "tweezers": [(464, 517), (455, 456), (420, 422)],
    "scissors": [(461, 488), (153, 182)],
    "eyewash": [(130, 153), (439, 460)],
    "bandaids": [(402, 438), (126, 130)],
    "triangle bandage": [(390, 418), (679, 690), (519, 523)],
    "medical tape": [(382, 396), (335, 341), (111, 120)],
    "elastic bandage": [(318, 352)],
    "bite relief": [(661, 678), (386, 389), (370, 377)],
    "2 roll gauze": [(370, 381), (648, 661), (341, 356)],
    "abd": [(294, 326), (86, 102)],
    "oral gel": [(303, 317), (275, 285), (630, 647), (263, 264), (352, 356)],
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
    """Light up LEDs for a specific item (supports multiple ranges)"""
    if item_name not in LED_MAPPINGS:
        print(f"No LED mapping found for item: {item_name}")
        return
    
    ranges = LED_MAPPINGS[item_name]
    print(f"Lighting LEDs for item: {item_name}")
    
    # Clear all LEDs first
    clear_all_leds(strip)
    
    # Light up all ranges for this item
    for range_idx, (start, end) in enumerate(ranges):
        print(f"  Range {range_idx + 1}: LEDs {start}-{end}")
        for i in range(start, end + 1):
            if i < strip.numPixels():
                strip.setPixelColor(i, Color(*color))
    
    strip.show()

def light_custom_range(strip, start, end, color=(0, 240, 255)):
    """Light up a custom range of LEDs"""
    if start < 0 or end >= strip.numPixels() or start > end:
        print(f"Invalid range: {start}-{end}. Valid range: 0-{strip.numPixels()-1}")
        return
    
    print(f"Lighting LEDs {start}-{end}")
    
    # Clear all LEDs first
    clear_all_leds(strip)
    
    # Light up the specific range
    for i in range(start, end + 1):
        strip.setPixelColor(i, Color(*color))
    
    strip.show()

def light_single_led(strip, led_number, color=(0, 240, 255)):
    """Light up a single LED"""
    if led_number < 0 or led_number >= strip.numPixels():
        print(f"Invalid LED number: {led_number}. Valid range: 0-{strip.numPixels()-1}")
        return
    
    print(f"Lighting LED {led_number}")
    
    # Clear all LEDs first
    clear_all_leds(strip)
    
    # Light up the specific LED
    strip.setPixelColor(led_number, Color(*color))
    strip.show()

def test_all_items(strip):
    """Test all items one by one"""
    print("Testing all kit items...")
    
    for item_name, ranges in LED_MAPPINGS.items():
        print(f"\nTesting: {item_name}")
        for range_idx, (start, end) in enumerate(ranges):
            print(f"  Range {range_idx + 1}: LEDs {start}-{end}")
        light_item_leds(strip, item_name)
        time.sleep(3)  # Show for 3 seconds
        clear_all_leds(strip)
        time.sleep(1)  # Brief pause between items

def scan_led_range(strip, start_range, end_range, step=10, duration=2):
    """Scan through a range of LEDs to help identify physical locations"""
    print(f"Scanning LEDs {start_range}-{end_range} in steps of {step}")
    
    for i in range(start_range, end_range + 1, step):
        print(f"Lighting LEDs {i}-{i+step-1}")
        light_custom_range(strip, i, min(i+step-1, end_range))
        time.sleep(duration)
        clear_all_leds(strip)
        time.sleep(0.5)
    
    print("Scan complete!")

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
        print("3. Test custom LED range")
        print("4. Test single LED")
        print("5. Scan LED range (helpful for mapping)")
        print("6. Show LED mapping")
        print("7. Exit")
        
        choice = input("\nEnter your choice (1-7): ").strip()
        
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
            try:
                start = int(input(f"Enter start LED (0-{LED_COUNT-1}): "))
                end = int(input(f"Enter end LED (0-{LED_COUNT-1}): "))
                light_custom_range(strip, start, end)
                input("Press Enter to turn off LEDs...")
                clear_all_leds(strip)
            except ValueError:
                print("Invalid input - please enter numbers only")
        
        elif choice == "4":
            try:
                led_num = int(input(f"Enter LED number (0-{LED_COUNT-1}): "))
                light_single_led(strip, led_num)
                input("Press Enter to turn off LEDs...")
                clear_all_leds(strip)
            except ValueError:
                print("Invalid input - please enter a number only")
        
        elif choice == "5":
            try:
                start_range = int(input(f"Enter start of scan range (0-{LED_COUNT-1}): "))
                end_range = int(input(f"Enter end of scan range (0-{LED_COUNT-1}): "))
                step = int(input("Enter step size (default 10): ") or "10")
                duration = float(input("Enter duration per step in seconds (default 2): ") or "2")
                scan_led_range(strip, start_range, end_range, step, duration)
            except ValueError:
                print("Invalid input - please enter numbers only")
        
        elif choice == "6":
            print("\nLED Mappings:")
            for item, ranges in LED_MAPPINGS.items():
                range_strs = [f"{start}-{end}" for start, end in ranges]
                print(f"{item}: {', '.join(range_strs)}")
        
        elif choice == "7":
            break
        
        else:
            print("Invalid choice")
    
    # Clean up
    clear_all_leds(strip)
    print("LED test complete!")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# Light specific compartments on a WS2812/NeoPixel strip via menu
# Works with rpi_ws281x (GPIO13 / channel 1 per your config)

import time
from rpi_ws281x import *
import argparse

# ----------------------- STRIP CONFIG -----------------------
LED_COUNT      = 788     # Total pixels
LED_PIN        = 13      # GPIO 13 -> PWM1 (rpi_ws281x channel 1)
LED_FREQ_HZ    = 800000
LED_DMA        = 10
LED_BRIGHTNESS = 100
LED_INVERT     = False
LED_CHANNEL    = 1

# Display color (Cyan-ish). Change here if you like.
COLOR = Color(0, 240, 255)

# ----------------------- COMPARTMENT MAP --------------------
# Each item maps to a list of (start, end) inclusive ranges.
# Single LEDs can be written as (n, n).
ITEMS = [
    "Solstis Middle",
    "Quickclot",
    "Burn Spray",
    "Burn Dressing",
    '4" Gauze Pads',
    "Cold Pack",
    "Electrolyte",
    "Antibiotic",
    "Tweezers",
    "Scissors",
    "Eyewash",
    "Bandaids",
    "Triangle Bandage",
    "Medical tape",
    "Elastic bandage",
    "Bite relief",
    '2" Roll Gauze',
    "ABD",
    "Oral Gel",
]

RANGES = {
    1:  [(643,663), (696,727)],
    2:  [(62,86), (270,293), (264,264)],
    3:  [(41,62), (234,269), (226,226)],
    4:  [(241,262), (220,226), (601,629)],
    5:  [(581,623), (636,642), (720,727)],
    6:  [(706,719), (199,212), (581,594), (552,567)],
    7:  [(691,705), (523,567)],                 # adjust if needed
    8:  [(493,548), (186,193)],
    9:  [(464,517), (455,456), (420,422)],
    10: [(461,488), (153,182)],
    11: [(130,153), (439,460)],
    12: [(402,438), (126,130)],
    13: [(390,418), (679,690), (519,523)],
    14: [(382,396), (335,341), (111,120)],
    15: [(318,352)],
    16: [(661,678), (386,389), (370,377)],
    17: [(370,381), (648,661), (339,356)],
    18: [(294,326), (84,102)],
    19: [(303,317), (275,284), (630,642), (263,264)],
}

# ----------------------- HELPERS ----------------------------
def init_strip():
    time.sleep(2.0)  # give LEDs power time before driving DIN
    strip = Adafruit_NeoPixel(
        LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA,
        LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL
    )
    strip.begin()
    return strip

def clear_strip(strip):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, 0)
    strip.show()

def set_ranges(strip, ranges, color):
    for lo, hi in ranges:
        if lo > hi:
            lo, hi = hi, lo
        lo = max(0, lo)
        hi = min(strip.numPixels() - 1, hi)
        for i in range(lo, hi + 1):
            strip.setPixelColor(i, color)
    strip.show()

def print_menu():
    print("\n=== Medical Kit LED Highlighter ===")
    for idx, name in enumerate(ITEMS, start=1):
        print(f"{idx:>2}. {name}")
    print("Press Ctrl+C to Quit")
    print("-----------------------------------")

# ----------------------- MAIN LOOP --------------------------
def main():
    strip = init_strip()
    try:
        while True:
            print_menu()
            choice = input("Select item number (1-19): ").strip()
            if not choice.isdigit():
                print("Please enter a number 1-19.")
                continue
            num = int(choice)
            if num < 1 or num > len(ITEMS):
                print("Out of range. Choose 1-19.")
                continue

            name = ITEMS[num - 1]
            ranges = RANGES.get(num, [])
            if not ranges:
                print(f"No ranges defined for {name}.")
                continue

            clear_strip(strip)
            set_ranges(strip, ranges, COLOR)
            print(f"Lighting: {name} -> {ranges}")
            input("Press Enter to clear and return to menu...")
            clear_strip(strip)

    except KeyboardInterrupt:
        # Ctrl+C will end the script cleanly
        clear_strip(strip)
        print("\nStopped by user (Ctrl+C). Goodbye!")


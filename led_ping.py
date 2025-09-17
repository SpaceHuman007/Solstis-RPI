#!/usr/bin/env python3
import time
from rpi_ws281x import *

LED_COUNT      = 788
LED_PIN        = 13      # you’re wired to GPIO13
LED_FREQ_HZ    = 800000
LED_DMA        = 10
LED_BRIGHTNESS = 180
LED_INVERT     = False
LED_CHANNEL    = 1

def main():
    print("Init strip...")
    strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA,
                              LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    strip.begin()
    time.sleep(0.5)

    # clear
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, 0)
    strip.show()
    time.sleep(0.2)

    # light first 50 pixels bright white
    print("Lighting first 50 pixels for 10s...")
    for i in range(min(50, strip.numPixels())):
        strip.setPixelColor(i, Color(255, 255, 255))  # white
    strip.show()
    time.sleep(10)

    # turn off
    print("Clearing...")
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, 0)
    strip.show()
    print("Done.")

if __name__ == "__main__":
    main()

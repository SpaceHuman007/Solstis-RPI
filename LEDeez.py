#!/usr/bin/env python3
# NeoPixel library strandtest example
# Author: Tony DiCola (tony@tonydicola.com)
#
# Direct port of the Arduino NeoPixel library strandtest example.  Showcases
# various animations on a strip of NeoPixels.

import time
from rpi_ws281x import *
import argparse

# LED strip configuration:
LED_COUNT      = 788     # Number of LED pixels.
LED_PIN        = 13      # GPIO pin connected to the pixels (10 uses SPI /dev/spidev0.0).
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 10      # DMA channel to use for generating signal (try 10)
LED_BRIGHTNESS = 30     # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL    = 1       # set to '1' for GPIOs 13, 19, 41, 45 or 53


time.sleep(2.0)  # give LEDs power time before driving DIN
strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA,
                          LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
strip.begin()

# clear all
for i in range(strip.numPixels()):
        strip.setPixelColor(i, 0)
strip.show()

#for i in range (250,275):
#        strip.setPixelColor(i,Color(0,240,255))

# Range 2
#for i in range(150, 175):
#    strip.setPixelColor(i, Color(0, 240, 255))

# Range 3
for i in range (700,725):
    strip.setPixelColor(i, Color(0, 240, 255))

strip.show()



# keep on for 5 seconds
time.sleep(5)

# turn off
for i in range(strip.numPixels()):
    strip.setPixelColor(i, 0)
strip.show()
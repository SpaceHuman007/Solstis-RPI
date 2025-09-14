import board
import neopixel

LED_COUNT = 480
LED_PIN = board.D13   # GPIO 13 (use board pin mappings)
pixels = neopixel.NeoPixel(LED_PIN, LED_COUNT, brightness=0.5, auto_write=False)

# Clear
pixels.fill((0,0,0))
pixels.show()

# Light up 15–40
for i in range(15, 40):
    pixels[i] = (0, 240, 255)
pixels.show()

#!/usr/bin/env python3
import pvporcupine
import pyaudio
import struct
import sys

# === Config ===
ACCESS_KEY = os.getenv("PICOVOICE-ACCESSKEY")  # <-- paste your real AccessKey here
WAKEWORD_PATH = "Solstice_en_raspberry-pi_v3_0_0.ppn"  # use macOS ppn if running on Mac

def main():
    porcupine = None
    pa = None
    audio_stream = None

    try:
        # Initialize Porcupine with access key + custom keyword
        porcupine = pvporcupine.create(
            access_key=ACCESS_KEY,
            keyword_paths=[WAKEWORD_PATH]
        )

        pa = pyaudio.PyAudio()

        # Open audio stream (16-bit mono @ 16kHz)
        audio_stream = pa.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length
        )

        print("Listening for wake word... (say your keyword to trigger)")

        while True:
            pcm = audio_stream.read(porcupine.frame_length, exception_on_overflow=False)
            pcm_unpacked = struct.unpack_from("h" * porcupine.frame_length, pcm)

            result = porcupine.process(pcm_unpacked)
            if result >= 0:  # Detected!
                print("Wake word detected!")
                break

    except KeyboardInterrupt:
        print("Stopping...")

    finally:
        if porcupine is not None:
            porcupine.delete()
        if audio_stream is not None:
            audio_stream.close()
        if pa is not None:
            pa.terminate()

if __name__ == "__main__":
    main()

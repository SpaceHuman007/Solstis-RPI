#!/usr/bin/env python3
import struct, sys, signal, math
from datetime import datetime
import pvporcupine   # pip install pvporcupine
import pyaudio       # pip install pyaudio

# 👇 Replace with your real AccessKey string from Picovoice Console
ACCESS_KEY = "/AYhvVhr1kX+pDDx0SUAUF+Cbo8AFbiBE+L0HqqJuYoiFvqTfxIyYA=="

# Must use macOS-trained ppn file here, not Raspberry Pi one
WAKEWORD_PATH = "Solstice_en_raspberry-pi_v3_0_0.ppn"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def make_beep(sr=16000, hz=880, ms=200, ampl=12000):
    n = int(sr * ms / 1000)
    return b''.join(struct.pack("<h", int(ampl*math.sin(2*math.pi*hz*i/sr))) for i in range(n))

def main():
    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[WAKEWORD_PATH]
    )

    pa = pyaudio.PyAudio()
    stream_in = pa.open(
        rate=porcupine.sample_rate,
        channels=1,
        format=pyaudio.paInt16,
        input=True,
        frames_per_buffer=porcupine.frame_length
    )
    stream_out = pa.open(
        rate=porcupine.sample_rate,
        channels=1,
        format=pyaudio.paInt16,
        output=True
    )

    beep = make_beep(porcupine.sample_rate)
    log("Listening for wake word... (Ctrl+C to quit)")

    try:
        while True:
            pcm = stream_in.read(porcupine.frame_length, exception_on_overflow=False)
            pcm_unpacked = struct.unpack_from("h" * porcupine.frame_length, pcm)
            result = porcupine.process(pcm_unpacked)
            if result >= 0:
                log("Wake word detected!")
                stream_out.write(beep)
    except KeyboardInterrupt:
        log("Stopping...")
    finally:
        stream_in.close()
        stream_out.close()
        pa.terminate()
        porcupine.delete()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()

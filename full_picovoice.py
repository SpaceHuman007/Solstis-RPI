#!/usr/bin/env python3
# Porcupine wake-word tester using ALSA arecord/aplay devices (no PyAudio).

import os, sys, struct, signal, subprocess, math
from datetime import datetime
import pvporcupine  # pip install pvporcupine

# --- Config via env (matches your style) ---
ACCESS_KEY   = os.getenv("PICOVOICE_ACCESS_KEY", "YOUR-PICOVOICE-ACCESSKEY-HERE")
WAKEWORD_PATH = os.getenv("WAKEWORD_PATH", "Solstice_en_raspberry-pi_v3_0_0.ppn")

# Mic input: ALSA device string like "plughw:3,0"
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR     = int(os.getenv("MIC_SR", "16000"))  # Porcupine requires 16k
# Speaker output device (for beep)
OUT_DEVICE = os.getenv("AUDIO_DEVICE")  # e.g., "plughw:3,0" or None for default
OUT_SR     = int(os.getenv("OUT_SR", "16000"))  # beep sample-rate

BEEP_HZ    = int(os.getenv("BEEP_HZ", "880"))
BEEP_MS    = int(os.getenv("BEEP_MS", "200"))
BEEP_AMPL  = int(os.getenv("BEEP_AMPL", "12000"))  # 0..32767

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def spawn_arecord(rate, device):
    # 16-bit mono raw at desired rate (Porcupine: 16k)
    args = [
        "arecord", "-t", "raw",
        "-f", "S16_LE",
        "-r", str(rate),
        "-c", "1",
        "-D", device
    ]
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def spawn_aplay(rate):
    args = ["aplay", "-t", "raw", "-f", "S16_LE", "-r", str(rate), "-c", "1"]
    if OUT_DEVICE:
        args += ["-D", OUT_DEVICE]
    return subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

def make_beep(sr, hz, ms, ampl):
    """Generate a simple sine beep as raw PCM16 bytes."""
    n = int(sr * ms / 1000.0)
    data = bytearray()
    for i in range(n):
        v = int(ampl * math.sin(2 * math.pi * hz * (i / sr)))
        data += struct.pack("<h", v)
    return bytes(data)

def main():
    if not os.path.exists(WAKEWORD_PATH):
        log(f"ERROR: WAKEWORD_PATH not found: {WAKEWORD_PATH}")
        sys.exit(1)

    if ACCESS_KEY.startswith("YOUR-") or not ACCESS_KEY:
        log("ERROR: No valid Picovoice AccessKey set. Export PICOVOICE_ACCESS_KEY or edit script.")
        sys.exit(1)

    porcupine = None
    arec = None
    aplay = None

    try:
        log(f"Loading Porcupine with keyword: {WAKEWORD_PATH}")
        porcupine = pvporcupine.create(
            access_key=ACCESS_KEY,
            keyword_paths=[WAKEWORD_PATH]
        )

        if MIC_SR != porcupine.sample_rate:
            log(f"NOTE: Overriding MIC_SR → {porcupine.sample_rate} (Porcupine requirement).")
        mic_sr = porcupine.sample_rate  # 16000
        frame_len = porcupine.frame_length
        frame_bytes = frame_len * 2  # 16-bit mono => 2 bytes/sample

        log(f"Mic device: {MIC_DEVICE} @ {mic_sr} Hz | frame {frame_len} samples ({frame_bytes} bytes)")
        arec = spawn_arecord(mic_sr, MIC_DEVICE)

        # Prepare speaker & beep
        aplay = spawn_aplay(OUT_SR)
        beep = make_beep(OUT_SR, BEEP_HZ, BEEP_MS, BEEP_AMPL)

        log("Listening for wake word... Press Ctrl+C to quit.")
        leftover = b""

        while True:
            chunk = arec.stdout.read(frame_bytes)
            if not chunk:
                log("Mic stream ended (EOF). Is the device busy or disconnected?")
                break

            buf = leftover + chunk
            offset = 0
            while len(buf) - offset >= frame_bytes:
                frame = buf[offset:offset + frame_bytes]
                offset += frame_bytes
                pcm = struct.unpack_from("<" + "h" * frame_len, frame)
                r = porcupine.process(pcm)
                if r >= 0:
                    log("Wake word detected! 🔊")
                    try:
                        aplay.stdin.write(beep)
                        aplay.stdin.flush()
                    except BrokenPipeError:
                        pass
            leftover = buf[offset:]

    except KeyboardInterrupt:
        log("Stopping (Ctrl+C).")
    except Exception as e:
        log(f"ERROR: {e}")
    finally:
        try:
            if porcupine: porcupine.delete()
        except: pass
        try:
            if arec: arec.terminate()
        except: pass
        try:
            if aplay and aplay.stdin:
                aplay.stdin.write(bytes([0] * (OUT_SR * 2 // 10)))
                aplay.stdin.close()
        except: pass
        try:
            if aplay: aplay.terminate()
        except: pass

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()

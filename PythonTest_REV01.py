#!/usr/bin/env python3
# Minimal mic↔model↔speaker loop on Raspberry Pi using ALSA (Python)

import asyncio
import base64
import json
import os
import signal
import subprocess
import sys
import select

import websockets  # pip install websockets
from dotenv import load_dotenv  # pip install python-dotenv

load_dotenv(override=True)

# --- config ---
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr)
    sys.exit(1)

URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime"

# speaker (ReSpeaker jack)
OUT_DEVICE = os.getenv("AUDIO_DEVICE")  # e.g. "plughw:3,0"
OUT_SR = 24000

# mic (ReSpeaker capture)
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR = 24000


# ---- spawn aplay (RAW PCM) ----
def spawn_aplay():
    args = ["aplay", "-t", "raw", "-f", "S16_LE", "-r", str(OUT_SR), "-c", "1"]
    if OUT_DEVICE:
        args.extend(["-D", OUT_DEVICE])
    return subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)


# ---- spawn arecord (RAW PCM) ----
def spawn_arecord():
    args = ["arecord", "-t", "raw", "-f", "S16_LE", "-r", str(MIC_SR), "-c", "1", "-D", MIC_DEVICE]
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


async def main():
    aplay = spawn_aplay()

    async with websockets.connect(
        URL,
        extra_headers={
            "Authorization": f"Bearer {API_KEY}",
            "OpenAI-Beta": "realtime=v1",
        },
        max_size=16 * 1024 * 1024,
    ) as ws:
        print("WS connected.")

        # ask server for PCM16 audio output
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "output_audio_format": "pcm16",
                "instructions": "You are a helpful assistant running on a Raspberry Pi. Be brief.",
            },
        }))

        async def ws_reader():
            print("[DEBUG] ws_reader started.")
            while True:
                msg = await ws.recv()
                try:
                    evt = json.loads(msg)
                except Exception:
                    continue

                t = evt.get("type")
                if t == "response.audio.delta":
                    pcm = base64.b64decode(evt.get("delta", ""))
                    try:
                        aplay.stdin.write(pcm)
                    except BrokenPipeError:
                        pass
                elif t == "response.audio_transcript.delta":
                    sys.stdout.write(evt.get("delta", ""))
                    sys.stdout.flush()
                elif t == "response.completed":
                    # 100 ms silence padding
                    aplay.stdin.write(bytes([0] * (OUT_SR * 2 // 10)))
                    print("\n[response completed]")
                elif t == "error":
                    print("API error:", evt.get("error"))

        async def capture_loop():
            print("[DEBUG] capture_loop started. Press Enter to record.")
            while True:
                input("Press Enter to talk (press Enter again to stop). Ctrl+C to quit.\n")
                print("🎙️  Recording... (press Enter to stop)")
                arec = spawn_arecord()
                audio = bytearray()
                total = 0

                # We'll monitor both arecord's stdout and stdin for Enter
                f_arec = arec.stdout
                f_stdin = sys.stdin

                try:
                    while True:
                        # Wait until either mic has data or user pressed Enter
                        rlist, _, _ = select.select([f_arec, f_stdin], [], [], 0.25)

                        # Stop on Enter (newline on stdin)
                        if f_stdin in rlist:
                            _ = f_stdin.readline()  # consume the newline
                            print("[DEBUG] Enter detected → stopping recording.")
                            try:
                                arec.terminate()
                            except Exception as e:
                                print("[DEBUG] Error terminating arecord:", e)
                            # don't break yet; let the pipe drain to EOF below

                        # Read mic data if available
                        if f_arec in rlist:
                            chunk = f_arec.read(4096)
                            if not chunk:
                                print("[DEBUG] Mic stream closed (EOF).")
                                break
                            audio.extend(chunk)
                            total += len(chunk)
                            if total and total % (4096 * 50) == 0:  # ~every 200KB
                                print(f"[DEBUG] Captured {total} bytes so far...")
                finally:
                    # ensure arecord is gone
                    try:
                        arec.terminate()
                    except Exception:
                        pass

                print(f"[DEBUG] Finished recording. Total audio bytes: {len(audio)}")

                if not audio:
                    print("[DEBUG] No audio captured, skipping send.")
                    continue

                # --- send audio to API ---
                print("[DEBUG] Sending audio to API...")
                await ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                for i in range(0, len(audio), 8192):
                    b64 = base64.b64encode(audio[i:i+8192]).decode("ascii")
                    await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": b64}))
                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                await ws.send(json.dumps({"type": "response.create"}))
                print("[DEBUG] Audio sent, waiting for response...")

        # >>> START the tasks (this is what was missing)
        await asyncio.gather(ws_reader(), capture_loop())

    # Cleanup after the ws context exits
    try:
        if aplay.stdin:
            aplay.stdin.close()
    except Exception:
        pass
    try:
        aplay.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    asyncio.run(main())

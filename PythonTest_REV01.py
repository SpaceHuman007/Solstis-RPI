#!/usr/bin/env python3
# Minimal mic↔model↔speaker loop on Raspberry Pi using ALSA (Python)

import asyncio
import base64
import json
import os
import signal
import subprocess
import sys

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
            loop = asyncio.get_event_loop()
            while True:
                input("Press Enter to talk (Enter again to stop). Ctrl+C to quit.\n")
                print("🎙️  Recording... (press Enter to stop)")
                arec = spawn_arecord()
                audio = bytearray()

                def stopper():
                    print("[DEBUG] Stop signal received (Enter pressed again).")
                    try:
                        arec.terminate()
                    except Exception as e:
                        print("[DEBUG] Error terminating arecord:", e)

                loop.add_reader(sys.stdin, stopper)
                try:
                    while True:
                        chunk = arec.stdout.read(4096)
                        if not chunk:
                            print("[DEBUG] No more audio chunks from arecord.")
                            break
                        audio.extend(chunk)
                        if len(audio) % (4096 * 50) == 0:  # every ~200 KB
                            print(f"[DEBUG] Captured {len(audio)} bytes so far...")
                finally:
                    loop.remove_reader(sys.stdin)

                print(f"[DEBUG] Finished recording. Total audio bytes: {len(audio)}")

                if not audio:
                    print("[DEBUG] No audio captured, skipping send.")
                    continue

                # send audio to API
                print("[DEBUG] Sending audio to API...")
                await ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                for i in range(0, len(audio), 8192):
                    b64 = base64.b64encode(audio[i:i+8192]).decode("ascii")
                    await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": b64}))
                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                await ws.send(json.dumps({"type": "response.create"}))
                print("[DEBUG] Audio sent, waiting for response...")



if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    asyncio.run(main())

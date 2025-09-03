#!/usr/bin/env python3
# Minimal mic↔model↔speaker loop on Raspberry Pi using ALSA (Python)
# with select-based PTT, explicit audio modalities, and verbose logging.

import asyncio
import base64
import json
import os
import select
import signal
import subprocess
import sys
from datetime import datetime

import websockets  # pip install websockets
from dotenv import load_dotenv  # pip install python-dotenv

load_dotenv(override=True)

# --- config ---
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr)
    sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4o-realtime-preview-2024-12-17")
URL = f"wss://api.openai.com/v1/realtime?model={MODEL}"

# speaker (ReSpeaker jack)
OUT_DEVICE = os.getenv("AUDIO_DEVICE")  # e.g. "plughw:3,0"
OUT_SR = int(os.getenv("OUT_SR", "24000"))

# mic (ReSpeaker capture)
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR = int(os.getenv("MIC_SR", "24000"))

VOICE = os.getenv("VOICE", "verse")  # common voices: verse, alloy, aria


def log(msg, *a):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", *a, flush=True)


# ---- spawn aplay (RAW PCM) ----
def spawn_aplay():
    args = ["aplay", "-t", "raw", "-f", "S16_LE", "-r", str(OUT_SR), "-c", "1"]
    if OUT_DEVICE:
        args.extend(["-D", OUT_DEVICE])
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    return p


# ---- spawn arecord (RAW PCM) ----
def spawn_arecord():
    args = ["arecord", "-t", "raw", "-f", "S16_LE", "-r", str(MIC_SR), "-c", "1", "-D", MIC_DEVICE]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p


async def main():
    aplay = spawn_aplay()

    async with websockets.connect(
        URL,
        extra_headers=[
            ("Authorization", f"Bearer {API_KEY}"),
            ("OpenAI-Beta", "realtime=v1"),
        ],
        max_size=16 * 1024 * 1024,
    ) as ws:
        log("WS connected.")

        # ask server for PCM16 audio output
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "output_audio_format": "pcm16",
                "instructions": "You are a helpful assistant running on a Raspberry Pi. Be brief.",
            },
        }))

        async def ws_reader():
            log("ws_reader started.")
            while True:
                try:
                    msg = await ws.recv()
                except websockets.ConnectionClosedOK:
                    log("WS closed (OK).")
                    break
                except websockets.ConnectionClosedError as e:
                    log(f"WS closed (error): {e}")
                    break

                # Try JSON; if not JSON, just show size
                evt = None
                try:
                    evt = json.loads(msg)
                except Exception:
                    log(f"<< [binary? length={len(msg)}]")
                    continue

                t = evt.get("type", "<?>")
                # Generic trace for all events
                log(f"<< {t}")

                if t == "response.audio.delta":
                    # base64 PCM16 mono 24k
                    b64 = evt.get("delta", "")
                    if b64:
                        try:
                            pcm = base64.b64decode(b64)
                            try:
                                aplay.stdin.write(pcm)
                            except BrokenPipeError:
                                pass
                        except Exception as e:
                            log(f"[audio.decode.error] {e}")

                elif t == "response.audio_transcript.delta":
                    sys.stdout.write(evt.get("delta", ""))
                    sys.stdout.flush()

                elif t == "response.output_text.delta":
                    # textual delta (if server also sends text)
                    sys.stdout.write(evt.get("delta", ""))
                    sys.stdout.flush()

                elif t == "response.completed":
                    # 100 ms silence padding
                    try:
                        aplay.stdin.write(bytes([0] * (OUT_SR * 2 // 10)))
                    except Exception:
                        pass
                    print("\n[response completed]")

                elif t == "error":
                    log(f"API error: {evt.get('error')}")

                # You will also see useful types here:
                # - response.created
                # - response.output_item.added/removed
                # - rate_limits.updated
                # - input_audio_buffer.* (acks)
                # - session.updated
                # The generic log above will show them.

        async def capture_loop():
            log("capture_loop started. Press Enter to record.")
            while True:
                input("Press Enter to talk (press Enter again to stop). Ctrl+C to quit.\n")
                print("🎙️  Recording... (press Enter to stop)")
                arec = spawn_arecord()
                audio = bytearray()
                total = 0

                f_arec = arec.stdout
                f_stdin = sys.stdin

                try:
                    while True:
                        # Wait until either mic has data or user pressed Enter
                        rlist, _, _ = select.select([f_arec, f_stdin], [], [], 0.25)

                        # Stop on Enter
                        if f_stdin in rlist:
                            _ = f_stdin.readline()  # consume newline
                            log("Enter detected → stopping recording.")
                            try:
                                arec.terminate()
                            except Exception as e:
                                log(f"Error terminating arecord: {e}")
                            # allow pipe to drain and hit EOF below

                        # Read mic data if available
                        if f_arec in rlist:
                            chunk = f_arec.read(4096)
                            if not chunk:
                                log("Mic stream closed (EOF).")
                                break
                            audio.extend(chunk)
                            total += len(chunk)
                            if total and total % (4096 * 50) == 0:  # ~every 200KB
                                log(f"Captured {total} bytes so far...")
                finally:
                    try:
                        arec.terminate()
                    except Exception:
                        pass

                log(f"Finished recording. Total audio bytes: {len(audio)}")

                if not audio:
                    log("No audio captured, skipping send.")
                    continue

                # --- send audio to API ---
                log("Sending audio to API...")
                await ws.send(json.dumps({"type": "input_audio_buffer.clear"}))

                for i in range(0, len(audio), 8192):
                    b64 = base64.b64encode(audio[i:i+8192]).decode("ascii")
                    await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": b64}))

                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

                # Explicitly request audio + text back and set a voice
                await ws.send(json.dumps({
                    "type": "response.create",
                    "response": {
                        "modalities": ["audio", "text"],
                        "instructions": "Answer briefly.",
                        "audio": {"voice": VOICE},
                    }
                }))
                log("Audio sent, waiting for response...")

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

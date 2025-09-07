#!/usr/bin/env python3
# Mic↔Realtime API↔Speaker (ALSA) with thread-based PTT (no event-loop blocking).

import asyncio, base64, json, os, select, signal, subprocess, sys
from datetime import datetime
from dotenv import load_dotenv          # pip install python-dotenv
import websockets                       # pip install "websockets>=11,<13"

load_dotenv(override=True)

# --- config ---
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4o-realtime-preview-2024-12-17")
URL   = f"wss://api.openai.com/v1/realtime?model={MODEL}"

OUT_DEVICE = os.getenv("AUDIO_DEVICE")     # e.g. "plughw:3,0"
OUT_SR     = int(os.getenv("OUT_SR", "24000"))
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR     = int(os.getenv("MIC_SR", "24000"))
VOICE      = os.getenv("VOICE", "verse")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def spawn_aplay():
    args = ["aplay","-t","raw","-f","S16_LE","-r",str(OUT_SR),"-c","1"]
    if OUT_DEVICE: args += ["-D", OUT_DEVICE]
    return subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

def spawn_arecord():
    args = ["arecord","-t","raw","-f","S16_LE","-r",str(MIC_SR),"-c","1","-D",MIC_DEVICE]
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ---------- blocking PTT capture (runs in a thread) ----------
def record_once_blocking():
    """
    Blocking push-to-talk:
    - Wait for Enter to start
    - Record until Enter again
    - Return PCM16 mono bytes
    """
    input("Press Enter to talk (press Enter again to stop). Ctrl+C to quit.\n")
    print("🎙️  Recording... (press Enter to stop)")
    arec = spawn_arecord()
    audio = bytearray(); total = 0
    f_arec, f_stdin = arec.stdout, sys.stdin

    try:
        while True:
            r,_,_ = select.select([f_arec, f_stdin], [], [], 0.25)

            if f_stdin in r:
                _ = f_stdin.readline()  # consume newline
                log("Enter detected → stopping recording.")
                try: arec.terminate()
                except Exception as e: log(f"arecord terminate err: {e}")
                # let pipe drain to EOF

            if f_arec in r:
                chunk = f_arec.read(4096)
                if not chunk:
                    log("Mic stream closed (EOF).")
                    break
                audio.extend(chunk); total += len(chunk)
                if total and total % (4096*50) == 0:
                    log(f"Captured {total} bytes so far...")
    finally:
        try: arec.terminate()
        except Exception: pass

    log(f"Finished recording. Total audio bytes: {len(audio)}")
    return bytes(audio)

async def main():
    aplay = spawn_aplay()

    async with websockets.connect(
        URL,
        extra_headers=[("Authorization", f"Bearer {API_KEY}"),
                       ("OpenAI-Beta", "realtime=v1")],
        max_size=16*1024*1024,
    ) as ws:
        log("WS connected.")

        # ---- Reader: log everything & stream audio/text ----
        async def ws_reader():
            log("ws_reader started.")
            async for msg in ws:
                try:
                    evt = json.loads(msg)
                except Exception:
                    log(f"<< [binary {len(msg)} bytes]")
                    continue

                t = evt.get("type", "<?>")
                log(f"<< {t}")

                if t in ("response.audio.delta", "response.output_audio.delta"):
                    b64 = evt.get("delta","")
                    if b64:
                        try:
                            pcm = base64.b64decode(b64)
                            try: aplay.stdin.write(pcm)
                            except BrokenPipeError: pass
                        except Exception as e:
                            log(f"[audio.decode.error] {e}")

                if t in ("response.text.delta", "response.output_text.delta"):
                    sys.stdout.write(evt.get("delta","")); sys.stdout.flush()

                if t in ("response.done", "response.completed"):
                    try: aplay.stdin.write(bytes([0] * (OUT_SR * 2 // 10)))
                    except Exception: pass
                    print("\n[response done]")

                if t in ("error", "response.error"):
                    log(f"API error: {evt.get('error')}")

        # Start reader first so we don't miss events
        reader_task = asyncio.create_task(ws_reader())

        # Wait for session.created
        while True:
            # Let reader task consume; we only watch for the first event here
            # by peeking via a separate recv would steal frames, so instead
            # we just sleep until reader prints it (2 small sleeps).
            await asyncio.sleep(0.05)
            # You’ll see "<< session.created" in logs from reader when it arrives.
            # Break after a short grace; the server usually sends it immediately.
            break

        # Configure session
        await ws.send(json.dumps({
            "type":"session.update",
            "session":{
                "input_audio_format":"pcm16",
                "output_audio_format":"pcm16",
                "voice": VOICE,
                "instructions":"You are a helpful assistant running on a Raspberry Pi. Be brief."
            }
        }))
        log(">> session.update sent")

        # Text-only probe so the reader can show replies immediately
        await ws.send(json.dumps({
            "type":"response.create",
            "response":{"modalities":["text"], "instructions":"Reply with READY"}
        }))
        log(">> text-only probe sent")

        # ---- PTT loop: run blocking capture in a thread ----
        while True:
            audio = await asyncio.to_thread(record_once_blocking)
            if not audio:
                log("No audio captured, skipping send."); continue

            log("Sending audio to API...")
            await ws.send(json.dumps({"type":"input_audio_buffer.clear"}))

            chunks = 0
            for i in range(0, len(audio), 8192):
                b64 = base64.b64encode(audio[i:i+8192]).decode("ascii")
                await ws.send(json.dumps({"type":"input_audio_buffer.append","audio": b64}))
                chunks += 1
            log(f">> appended {chunks} chunks")

            await ws.send(json.dumps({"type":"input_audio_buffer.commit"}))
            await ws.send(json.dumps({
                "type":"response.create",
                "response":{
                    "modalities":["audio","text"],
                    "instructions":"Answer briefly.",
                    "audio":{"voice": VOICE}
                }
            }))
            log("Audio sent, waiting for response...")

        # (never reached)
        await reader_task

    # Cleanup
    try:
        if aplay.stdin: aplay.stdin.close()
    except Exception: pass
    try: aplay.terminate()
    except Exception: pass

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    asyncio.run(main())
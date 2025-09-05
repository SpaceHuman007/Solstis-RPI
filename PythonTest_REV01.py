#!/usr/bin/env python3
# Realtime API with wake word ("respeaker") → record until silence → TTS reply.

import asyncio, base64, json, os, select, signal, subprocess, sys, time, audioop
from datetime import datetime
from dotenv import load_dotenv
import websockets

# --- wake word / mic ---
from respeaker import Microphone   # ReSpeaker Python library (pocketsphinx-based wake word)

load_dotenv(override=True)

# --- config ---
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4o-realtime-preview-2024-12-17")
URL   = f"wss://api.openai.com/v1/realtime?model={MODEL}"

OUT_DEVICE = os.getenv("AUDIO_DEVICE")     # e.g. "plughw:1,0" (HEADPHONES)
OUT_SR     = int(os.getenv("OUT_SR", "24000"))
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")  # ReSpeaker capture device for arecord
MIC_SR     = int(os.getenv("MIC_SR", "24000"))
VOICE      = os.getenv("VOICE", "verse")

WAKEWORD   = os.getenv("WAKEWORD", "respeaker")     # hotword label used by the library

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ---------- playback ----------
def spawn_aplay():
    args = ["aplay","-t","raw","-f","S16_LE","-r",str(OUT_SR),"-c","1"]
    if OUT_DEVICE: args += ["-D", OUT_DEVICE]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    return p

# ---------- capture (arecord) ----------
def spawn_arecord():
    args = ["arecord","-t","raw","-f","S16_LE","-r",str(MIC_SR),"-c","1","-D",MIC_DEVICE]
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ---------- wake word (blocking) ----------
def wait_for_wakeword_blocking(keyword=WAKEWORD):
    """
    Blocks until pocketsphinx detects the given keyword via ReSpeaker's Microphone.
    We only use this to *gate* the start of a real recording; we still capture with arecord.
    """
    mic = Microphone()  # uses default I2S/ALSA source internally
    log(f"Listening for wake word: '{keyword}' ...")
    while True:
        try:
            if mic.wakeup(keyword):
                log(f"Wake word detected: '{keyword}'")
                return
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"[wakeword error] {e}")
            time.sleep(0.2)

# ---------- record an utterance until silence (blocking) ----------
def record_until_silence_blocking(max_seconds=15, silence_ms=900, rms_threshold=200):
    """
    Uses arecord at MIC_SR (mono, S16_LE). Stops when RMS stays below threshold
    for ~silence_ms or when max_seconds elapse. Returns raw PCM16 bytes.
    """
    arec = spawn_arecord()
    buf = bytearray()
    start = time.time()
    last_voice = start
    try:
        while True:
            chunk = arec.stdout.read(4096)
            if not chunk:
                break
            buf.extend(chunk)
            # RMS over 16-bit samples (width=2)
            try:
                r = audioop.rms(chunk, 2)
            except Exception:
                r = 0
            if r > rms_threshold:
                last_voice = time.time()
            if (time.time() - last_voice) * 1000.0 > silence_ms:
                # stop after trailing silence
                try: arec.terminate()
                except Exception: pass
                # drain pipe
                while True:
                    ch = arec.stdout.read(4096)
                    if not ch: break
                    buf.extend(ch)
                break
            if time.time() - start > max_seconds:
                try: arec.terminate()
                except Exception: pass
                while True:
                    ch = arec.stdout.read(4096)
                    if not ch: break
                    buf.extend(ch)
                break
    finally:
        try: arec.terminate()
        except Exception: pass
    log(f"Captured {len(buf)} bytes (MIC_SR={MIC_SR} Hz).")
    return bytes(buf)

# ---------- websocket client ----------
async def main():
    aplay = spawn_aplay()

    async with websockets.connect(
        URL,
        extra_headers=[("Authorization", f"Bearer {API_KEY}"),
                       ("OpenAI-Beta", "realtime=v1")],
        max_size=16*1024*1024,
    ) as ws:
        log("WS connected.")

        # reader task (logs everything, plays audio)
        async def ws_reader():
            log("ws_reader started.")
            async for msg in ws:
                try:
                    evt = json.loads(msg)
                except Exception:
                    # binary frames aren't expected; ignore
                    continue

                t = evt.get("type", "<?>")
                # trace
                # log(f"<< {t}")

                if t in ("response.audio.delta","response.output_audio.delta"):
                    b64 = evt.get("delta","")
                    if b64:
                        try:
                            pcm = base64.b64decode(b64)
                            try: aplay.stdin.write(pcm)
                            except BrokenPipeError: pass
                        except Exception as e:
                            log(f"[audio.decode.error] {e}")

                if t in ("response.text.delta","response.output_text.delta","response.audio_transcript.delta"):
                    sys.stdout.write(evt.get("delta","")); sys.stdout.flush()

                if t in ("response.done","response.completed"):
                    try: aplay.stdin.write(bytes([0] * (OUT_SR * 2 // 10)))
                    except Exception: pass
                    print("\n[response done]")

                if t in ("error","response.error"):
                    log(f"API error: {evt.get('error')}")

        reader_task = asyncio.create_task(ws_reader())

        # Wait for session hello (reader will print 'session.created' when it arrives)
        # Small grace; most stacks immediately send session.created.
        await asyncio.sleep(0.05)

        # Configure the session once (formats + voice)
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

        # Quick text probe (visible in console so you know socket is alive)
        await ws.send(json.dumps({
            "type":"response.create",
            "response":{"modalities":["text"], "instructions":"Reply with READY"}
        }))
        log(">> text-only probe sent")

        # --------------- Wake-word loop ---------------
        while True:
            # 1) block until wakeword
            await asyncio.to_thread(wait_for_wakeword_blocking, WAKEWORD)

            # 2) capture an utterance until silence
            print("🎙️  Speak now…")
            audio = await asyncio.to_thread(record_until_silence_blocking)
            if not audio or len(audio) < int(MIC_SR * 2 * 0.1):  # <~100 ms
                log("Too little audio; skipping.")
                continue

            # 3) send to API
            log("Sending audio to API...")
            await ws.send(json.dumps({"type":"input_audio_buffer.clear"}))
            for i in range(0, len(audio), 8192):
                b64 = base64.b64encode(audio[i:i+8192]).decode("ascii")
                await ws.send(json.dumps({"type":"input_audio_buffer.append","audio": b64}))
            await ws.send(json.dumps({"type":"input_audio_buffer.commit"}))

            await ws.send(json.dumps({
                "type":"response.create",
                "response":{
                    "modalities":["audio","text"],
                    "instructions":"Answer briefly."
                }
            }))
            log("Audio sent, waiting for response...")

        await reader_task  # (never reached)

    # cleanup
    try:
        if aplay.stdin: aplay.stdin.close()
    except Exception: pass
    try: aplay.terminate()
    except Exception: pass

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    asyncio.run(main())

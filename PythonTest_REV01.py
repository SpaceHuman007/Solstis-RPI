#!/usr/bin/env python3
# Realtime API with ReSpeaker wake word + mic.listen() → WAV → TTS reply

import asyncio, base64, json, os, signal, subprocess, sys, threading, types
from datetime import datetime
from dotenv import load_dotenv              # pip install python-dotenv
import websockets                           # pip install "websockets>=11,<13"

# ReSpeaker libs (same technique as your snippet)
from respeaker import Microphone
from respeaker.bing_speech_api import BingSpeechAPI

load_dotenv(override=True)

# --------- Config ---------
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4o-realtime-preview-2024-12-17")
URL   = f"wss://api.openai.com/v1/realtime?model={MODEL}"

# Playback device (HAT is input-only; pick a real output like Pi headphones or HDMI)
OUT_DEVICE = os.getenv("AUDIO_DEVICE")     # e.g. "plughw:1,0"
OUT_SR     = int(os.getenv("OUT_SR", "24000"))

VOICE      = os.getenv("VOICE", "verse")
WAKEWORD   = os.getenv("WAKEWORD", "respeaker")   # the hotword string

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ---------- aplay with stderr logger (helps debug device issues) ----------
def _pipe_logger(name, pipe):
    for line in iter(pipe.readline, b''):
        try: print(f"[{name}] {line.decode().rstrip()}", flush=True)
        except Exception: pass

def spawn_aplay():
    args = ["aplay","-t","raw","-f","S16_LE","-r",str(OUT_SR),"-c","1"]
    if OUT_DEVICE: args += ["-D", OUT_DEVICE]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    threading.Thread(target=_pipe_logger, args=("aplay", p.stderr), daemon=True).start()
    log("aplay started: " + " ".join(args))
    return p

# ---------- Capture once using your ReSpeaker technique ----------
def capture_once_after_wakeword_respeaker(keyword="respeaker"):
    """
    Blocks until Microphone().wakeup(keyword) fires, then collects speech
    with mic.listen() and returns **WAV bytes**, built exactly like your snippet.
    """
    mic = Microphone()
    log(f"Listening for wake word: '{keyword}' ...")
    while True:
        if mic.wakeup(keyword):
            log("Wake word detected.")
            break

    data = mic.listen()   # bytes OR generator of bytes (PCM)
    # Build a WAV using the exact helper your snippet used
    if isinstance(data, types.GeneratorType):
        parts = [BingSpeechAPI.get_wav_header()]
        parts.extend(data)
        wav_bytes = b"".join(parts)
    else:
        wav_bytes = BingSpeechAPI.to_wav(data)
    log(f"Captured {len(wav_bytes)} bytes (WAV).")
    return wav_bytes

async def main():
    aplay = spawn_aplay()

    async with websockets.connect(
        URL,
        extra_headers=[("Authorization", f"Bearer {API_KEY}"),
                       ("OpenAI-Beta", "realtime=v1")],
        max_size=16*1024*1024,
    ) as ws:
        log("WS connected.")

        session_ready = asyncio.Event()

        # ---- Reader task: log all events, play audio ----
        async def ws_reader():
            log("ws_reader started.")
            async for msg in ws:
                try:
                    evt = json.loads(msg)
                except Exception:
                    # not expected to get raw binary frames; ignore quietly
                    continue

                t = evt.get("type", "<?>")
                log(f"<< {t}")

                if t == "session.created":
                    session_ready.set()

                # audio chunks (new + legacy names)
                if t in ("response.audio.delta", "response.output_audio.delta"):
                    b64 = evt.get("delta","")
                    if b64:
                        try:
                            pcm = base64.b64decode(b64)
                            try: aplay.stdin.write(pcm)
                            except BrokenPipeError: pass
                        except Exception as e:
                            log(f"[audio.decode.error] {e}")

                # live transcript / text deltas
                if t in ("response.text.delta", "response.output_text.delta", "response.audio_transcript.delta"):
                    sys.stdout.write(evt.get("delta","")); sys.stdout.flush()

                # done (new + legacy)
                if t in ("response.done", "response.completed"):
                    try: aplay.stdin.write(bytes([0] * (OUT_SR * 2 // 10)))  # ~100ms silence
                    except Exception: pass
                    print("\n[response done]")

                # errors
                if t in ("error", "response.error"):
                    log(f"API error: {evt.get('error')}")

        reader_task = asyncio.create_task(ws_reader())

        # Wait for the server hello
        try:
            await asyncio.wait_for(session_ready.wait(), timeout=5)
        except asyncio.TimeoutError:
            log("No session.created within 5s — check model/key."); return

        # ---- Configure session ONCE (tell the server we send WAV, set voice) ----
        await ws.send(json.dumps({
            "type":"session.update",
            "session":{
                "input_audio_format":"wav",     # IMPORTANT: matches our WAV packaging
                "output_audio_format":"pcm16",
                "voice": VOICE,
                "instructions":"You run on a Raspberry Pi inside an AI medical kit. Be brief."
            }
        }))
        log(">> session.update sent")

        # ---- Quick probe (audio+text) so you can verify playback immediately ----
        await ws.send(json.dumps({
            "type":"response.create",
            "response":{"modalities":["audio","text"], "instructions":"Say READY."}
        }))
        log(">> probe sent")

        # --------------- Wake → listen → send loop ---------------
        while True:
            # Use your exact technique, but off the event loop
            wav = await asyncio.to_thread(capture_once_after_wakeword_respeaker, WAKEWORD)
            if not wav or len(wav) < 2000:
                log("Too little audio; skipping."); 
                continue

            log("Sending audio to API...")
            await ws.send(json.dumps({"type":"input_audio_buffer.clear"}))
            for i in range(0, len(wav), 8192):
                b64 = base64.b64encode(wav[i:i+8192]).decode("ascii")
                await ws.send(json.dumps({"type":"input_audio_buffer.append","audio": b64}))
            await ws.send(json.dumps({"type":"input_audio_buffer.commit"}))

            await ws.send(json.dumps({
                "type":"response.create",
                "response":{"modalities":["audio","text"], "instructions":"Answer briefly."}
            }))
            log("Audio sent, waiting for response...")

        await reader_task  # never reached

    # Cleanup
    try:
        if aplay.stdin: aplay.stdin.close()
    except Exception: pass
    try: aplay.terminate()
    except Exception: pass

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    asyncio.run(main())

#!/usr/bin/env python3
# ReSpeaker wake word → mic.listen() → PCM16 @ 24k → OpenAI Realtime → aplay

import asyncio, base64, json, os, signal, subprocess, sys, threading, time, io, wave, types, audioop
from datetime import datetime
from dotenv import load_dotenv                  # pip install python-dotenv
import websockets                               # pip install "websockets>=11,<13"

# ReSpeaker library (apt/pip install respeaker + pocketsphinx)
from respeaker import Microphone
from respeaker.bing_speech_api import BingSpeechAPI

load_dotenv(override=True)

# --------- Config (.env) ---------
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4o-realtime-preview")   # rolling alias recommended
URL   = f"wss://api.openai.com/v1/realtime?model={MODEL}"

# Playback device: pick a REAL output (headphones/HDMI/USB DAC), not the ReSpeaker card
OUT_DEVICE = os.getenv("AUDIO_DEVICE")     # e.g. "plughw:1,0"
OUT_SR     = int(os.getenv("OUT_SR", "24000"))

VOICE      = os.getenv("VOICE", "verse")
WAKEWORD   = os.getenv("WAKEWORD", "respeaker")

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ---------- aplay with stderr logger (debug ALSA quickly) ----------
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

# ---------- Capture using your ReSpeaker technique, return PCM16 @ 24k ----------
def capture_pcm16_after_wakeword_respeaker(keyword="respeaker", dst_hz=24000):
    """
    1) Blocks until Microphone().wakeup(keyword) triggers.
    2) Uses mic.listen() to collect speech.
    3) Returns raw PCM16 mono bytes at dst_hz (default 24 kHz).
       - If mic.listen() yields a generator: treat as PCM16 @ 16 kHz and resample.
       - If it returns a buffer that BingSpeechAPI.to_wav() understands: read the WAV and resample.
    """
    try:
        mic = Microphone()
    except Exception as e:
        raise RuntimeError("ReSpeaker Microphone() failed. Make sure pocketsphinx/respeaker are installed.") from e

    log(f"Listening for wake word: '{keyword}' ...")
    while True:
        if mic.wakeup(keyword):
            log("Wake word detected.")
            break

    data = mic.listen()  # bytes OR a generator of raw PCM frames

    # Step 1: get PCM16 mono + its source sample rate
    if isinstance(data, types.GeneratorType):
        # ReSpeaker samples are typically PCM16 @ 16 kHz
        src_pcm = b"".join(data)
        src_hz = 16000
    else:
        # Some paths return a buffer that their helper wraps as WAV
        wav_bytes = BingSpeechAPI.to_wav(data)
        wf = wave.open(io.BytesIO(wav_bytes), 'rb')
        assert wf.getsampwidth() == 2 and wf.getnchannels() == 1, "Expected 16-bit mono"
        src_hz = wf.getframerate()
        src_pcm = wf.readframes(wf.getnframes())
        wf.close()

    # Step 2: resample to dst_hz (PCM16 mono)
    if src_hz != dst_hz:
        # audioop.ratecv: (fragment, width, nchannels, inrate, outrate, state)
        src_pcm, _ = audioop.ratecv(src_pcm, 2, 1, src_hz, dst_hz, None)

    log(f"Captured {len(src_pcm)} bytes PCM16 @ {dst_hz} Hz.")
    return src_pcm  # raw PCM16 mono @ dst_hz

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

        # ---- Reader task: log & play everything ----
        async def ws_reader():
            log("ws_reader started.")
            async for msg in ws:
                try:
                    evt = json.loads(msg)
                except Exception:
                    # (Binary frames not expected here)
                    continue

                t = evt.get("type", "<?>")
                log(f"<< {t}")

                if t == "session.created":
                    session_ready.set()

                if t in ("response.audio.delta", "response.output_audio.delta"):
                    b64 = evt.get("delta","")
                    if b64:
                        try:
                            pcm = base64.b64decode(b64)
                            try: aplay.stdin.write(pcm)
                            except BrokenPipeError: pass
                        except Exception as e:
                            log(f"[audio.decode.error] {e}")

                if t in ("response.text.delta", "response.output_text.delta", "response.audio_transcript.delta"):
                    sys.stdout.write(evt.get("delta","")); sys.stdout.flush()

                if t in ("response.done", "response.completed"):
                    try: aplay.stdin.write(bytes([0] * (OUT_SR * 2 // 10)))  # ~100 ms silence
                    except Exception: pass
                    print("\n[response done]")

                if t in ("error", "response.error"):
                    log(f"API error: {evt.get('error')}")

        reader_task = asyncio.create_task(ws_reader())

        # Wait up to 5s for the server hello
        try:
            await asyncio.wait_for(session_ready.wait(), timeout=5)
        except asyncio.TimeoutError:
            log("No session.created within 5s — check MODEL/key."); return

        # ---- Configure the session ONCE (pcm16 in/out; set voice) ----
        await ws.send(json.dumps({
            "type":"session.update",
            "session":{
                "input_audio_format":"pcm16",   # << Realtime accepts pcm16/g711_* (not wav)
                "output_audio_format":"pcm16",
                "voice": VOICE,
                "instructions":"You run on a Raspberry Pi inside an AI medical kit. Be brief."
            }
        }))
        log(">> session.update sent")

        # ---- Quick audible probe (so you can confirm playback immediately) ----
        await ws.send(json.dumps({
            "type":"response.create",
            "response":{"modalities":["audio","text"], "instructions":"Say READY."}
        }))
        log(">> probe sent")

        # ---- Wake → capture → send loop ----
        while True:
            pcm = await asyncio.to_thread(capture_pcm16_after_wakeword_respeaker, WAKEWORD, OUT_SR)
            if not pcm or len(pcm) < int(OUT_SR * 2 * 0.1):   # ~100 ms min
                log("Too little audio; skipping.")
                continue

            log("Sending audio to API...")
            await ws.send(json.dumps({"type":"input_audio_buffer.clear"}))
            for i in range(0, len(pcm), 8192):
                b64 = base64.b64encode(pcm[i:i+8192]).decode("ascii")
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

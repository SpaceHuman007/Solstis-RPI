#!/usr/bin/env python3
# Solstis Voice Assistant with Picovoice Wake Word Detection and ChatGPT Integration
# Combines Picovoice wake word detection with OpenAI Realtime API for medical assistance

import asyncio, base64, json, os, signal, subprocess, sys, threading, time, io, wave, types, audioop, struct, math
from datetime import datetime
from dotenv import load_dotenv
import websockets
import pvporcupine  # pip install pvporcupine

load_dotenv(override=True)

# --------- Config via env (Picovoice + ChatGPT) ---------
# Picovoice config
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "YOUR-PICOVOICE-ACCESSKEY-HERE")
WAKEWORD_PATH = os.getenv("WAKEWORD_PATH", "Solstice_en_raspberry-pi_v3_0_0.ppn")
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR = int(os.getenv("MIC_SR", "16000"))  # Porcupine requires 16k

# ChatGPT/OpenAI config
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4o-realtime-preview")
URL = f"wss://api.openai.com/v1/realtime?model={MODEL}"

# Audio output config
OUT_DEVICE = os.getenv("AUDIO_DEVICE")  # e.g., "plughw:3,0" or None for default
OUT_SR = int(os.getenv("OUT_SR", "24000"))  # ChatGPT audio output sample rate
VOICE = os.getenv("VOICE", "verse")
USER_NAME = os.getenv("USER_NAME", "User")

# Beep config for wake word detection
BEEP_HZ = int(os.getenv("BEEP_HZ", "880"))
BEEP_MS = int(os.getenv("BEEP_MS", "200"))
BEEP_AMPL = int(os.getenv("BEEP_AMPL", "12000"))  # 0..32767

# Speech detection config
SPEECH_THRESHOLD = int(os.getenv("SPEECH_THRESHOLD", "500"))  # RMS threshold for speech detection
SILENCE_DURATION = float(os.getenv("SILENCE_DURATION", "1.5"))  # seconds of silence before stopping
MIN_SPEECH_DURATION = float(os.getenv("MIN_SPEECH_DURATION", "0.5"))  # minimum speech duration
MAX_SPEECH_DURATION = float(os.getenv("MAX_SPEECH_DURATION", "10.0"))  # maximum speech duration

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ---------- Solstis System Prompt for Standard Kit ----------
def get_system_prompt():
    """Generate the system prompt for the standard Solstis kit"""
    
    # Standard kit contents
    kit_contents = [
        "Band-Aids",
        "4\" x 4\" Gauze Pads (5)",
        "2\" Roll Gauze",
        "5\" x 9\" ABD Pad",
        "1\" Cloth Medical Tape",
        "Triple Antibiotic Ointment",
        "Blunt Tip Tweezers",
        "Small Trauma Shears",
        "QuickClot Gauze or Hemostatic Wipe",
        "4\" x 4\" Burn Gel Dressing",
        "2 oz Burn Spray",
        "Sting & Bite Relief Wipes (2)",
        "Mini Eye Wash Bottle (1)",
        "Oral Glucose Gel",
        "Electrolyte Powder Pack",
        "2\" Elastic Ace Bandage",
        "Instant Cold Pack",
        "Triangle Bandage"
    ]
    
    contents_str = ", ".join(kit_contents)
    
    return f"""You are Solstis, a gentle, calm, and highly knowledgeable AI-powered medical assistant embedded in a smart med kit. You assist users experiencing minor injuries, burns, or common ailments using only:

- Items from the Solstis Standard Kit: {contents_str}
- Common household resources (e.g., running water, soap, paper towels)

IMPORTANT: Always respond in English only. Do not use any other language.

Your primary goals:
1. **Triage First:** Always begin by calmly assessing whether this is a life-threatening emergency. If yes, urge the user to call 911 or offer to do so.
2. **Stay Present and Empathetic:** Speak naturally, like a calm friend guiding them step-by-step. Reassure them frequently.
3. **Use Only Available Items:** Recommend only items from the active kit and clearly identify their location by referencing the LED-lit compartment.
4. **Adapt by Scenario:** Respond fluidly based on context. Ask short follow-up questions to clarify condition and severity.
5. **Follow Up:** Offer relevant aftercare, such as reminders to change bandages or see a healthcare provider.
6. **Never Exceed Scope:** Avoid offering diagnoses, prescriptions, or complex medical advice.

Include this fallback check at every stage:  
"If symptoms worsen or this seems more serious than expected, please consider calling 911 or seeing a healthcare provider."

TREATMENT PROTOCOLS:

CUTS AND SCRAPES PROTOCOL:
- First: Clean with antiseptic wipes from the highlighted space
- For bleeding: Apply direct pressure with gauze from the highlighted space for 5 minutes
- After bleeding stops: Apply thin layer of antibiotic ointment from the highlighted space
- Cover with appropriate bandage from the highlighted space
- For finger joints: place the pad over the cut, angle the adhesive so it doesn't bunch at the knuckle; if needed, reinforce with tape from the highlighted space. "Let me know when you're ready."

BLEEDING CONTROL ESCALATION:
- First attempt: Direct pressure with gauze for 5 minutes
- If bleeding continues: Apply QuickClot/hemostatic agent with firm pressure
- If still bleeding: Apply more pressure and hold longer
- If bleeding persists after multiple attempts: ESCALATE TO EMERGENCY CARE
- NEVER repeat failed treatment methods - move to next option or emergency care

SEVERED BODY PARTS PROTOCOL:
- Call 9-1-1 immediately
- Control bleeding at injury site
- Preserve severed part: wrap in clean, damp cloth, place in plastic bag, put bag in ice water bath
- Do NOT put severed part directly on ice
- Keep severed part cool but not frozen

BURN ASSESSMENT PROTOCOL:
- Assess burn severity: size, depth, location
- Minor burns: Cool with water, pain relief, keep clean
- Major burns: Call 9-1-1 only if truly severe (large area, deep tissue, face/hands/genitals)
- Most burns can be treated with first aid first

COMMON SYMPTOMS - TREAT WITH FIRST AID FIRST:
- Fainting/Dizziness: Lie down, elevate legs, improve blood flow to brain
- Mild Shock: Keep warm, lie down, elevate legs if no spine injury
- Nausea: Rest, small sips of water, avoid sudden movements
- Mild Pain: Use pain relievers from kit, apply cold/heat as appropriate
- Cramps/Muscle Pain: Assess hydration, suggest electrolytes, stretching, massage
- Sexual Pain/Discomfort: Discuss openly and suggest appropriate relief methods
- Only escalate to emergency care if symptoms worsen or persist despite first aid

BLEEDING ASSESSMENT PROTOCOL:
- ALWAYS ask about amount of blood and size of injury first
- If heavy bleeding: Control bleeding BEFORE treating other symptoms
- If light bleeding: Treat other symptoms first, then address bleeding
- Severity determines treatment order and emergency escalation

Opening message (ONLY use this for the very first message in a new conversation):
"Hey {USER_NAME}. I'm here to help. If this is life-threatening, please call 9-1-1 now. Otherwise, I'll guide you step by step. Can you tell me what happened?"

IMPORTANT: Do NOT use this opening message for follow-up responses. Once the conversation has started, focus on the current situation and next steps.

Only give instructions using supplies from this kit (or common home items). Do not invent tools or procedures. You are not a diagnostic or medical authority—you are a calm first responder assistant."""

# ---------- Voice Activity Detection ----------
def calculate_rms(audio_data):
    """Calculate RMS (Root Mean Square) of audio data for voice activity detection"""
    if len(audio_data) == 0:
        return 0
    
    # Convert bytes to signed 16-bit integers
    samples = struct.unpack(f"<{len(audio_data)//2}h", audio_data)
    
    # Calculate RMS
    sum_squares = sum(sample * sample for sample in samples)
    rms = math.sqrt(sum_squares / len(samples))
    return rms

def is_speech_detected(audio_data, threshold=SPEECH_THRESHOLD):
    """Determine if audio contains speech based on RMS threshold"""
    rms = calculate_rms(audio_data)
    return rms > threshold

# ---------- Picovoice Wake Word Detection ----------
def spawn_arecord(rate, device):
    """Spawn arecord process for audio capture"""
    args = [
        "arecord", "-t", "raw",
        "-f", "S16_LE",
        "-r", str(rate),
        "-c", "1",
        "-D", device
    ]
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def spawn_aplay(rate):
    """Spawn aplay process for audio playback"""
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

def capture_audio_after_wakeword():
    """
    Wait for Picovoice wake word detection, then capture audio until speech pause.
    Returns PCM16 mono bytes at OUT_SR sample rate.
    """
    if not os.path.exists(WAKEWORD_PATH):
        raise RuntimeError(f"WAKEWORD_PATH not found: {WAKEWORD_PATH}")

    if PICOVOICE_ACCESS_KEY.startswith("YOUR-") or not PICOVOICE_ACCESS_KEY:
        raise RuntimeError("No valid Picovoice AccessKey set. Export PICOVOICE_ACCESS_KEY or edit script.")

    porcupine = None
    arec = None
    aplay = None

    try:
        log(f"Loading Porcupine with keyword: {WAKEWORD_PATH}")
        porcupine = pvporcupine.create(
            access_key=PICOVOICE_ACCESS_KEY,
            keyword_paths=[WAKEWORD_PATH]
        )

        mic_sr = porcupine.sample_rate  # 16000
        frame_len = porcupine.frame_length
        frame_bytes = frame_len * 2  # 16-bit mono => 2 bytes/sample

        log(f"Mic device: {MIC_DEVICE} @ {mic_sr} Hz | frame {frame_len} samples ({frame_bytes} bytes)")
        arec = spawn_arecord(mic_sr, MIC_DEVICE)

        # Prepare speaker & beep
        aplay = spawn_aplay(OUT_SR)
        beep = make_beep(OUT_SR, BEEP_HZ, BEEP_MS, BEEP_AMPL)

        log("Listening for wake word...")
        leftover = b""
        wake_word_detected = False

        # First, wait for wake word
        while not wake_word_detected:
            chunk = arec.stdout.read(frame_bytes)
            if not chunk:
                raise RuntimeError("Mic stream ended (EOF). Is the device busy or disconnected?")

            buf = leftover + chunk
            offset = 0
            while len(buf) - offset >= frame_bytes:
                frame = buf[offset:offset + frame_bytes]
                offset += frame_bytes
                pcm = struct.unpack_from("<" + "h" * frame_len, frame)
                r = porcupine.process(pcm)
                if r >= 0:
                    log("Wake word detected! 🔊")
                    wake_word_detected = True
                    try:
                        aplay.stdin.write(beep)
                        aplay.stdin.flush()
                    except BrokenPipeError:
                        pass
                    break
            leftover = buf[offset:]

        # Now capture audio until speech pause
        log("Capturing audio until speech pause...")
        audio_buffer = b""
        silence_start_time = None
        speech_start_time = None
        speech_detected = False
        
        # Calculate frame duration for timing
        frame_duration = frame_len / mic_sr  # seconds per frame
        
        while True:
            chunk = arec.stdout.read(frame_bytes)
            if not chunk:
                break
            
            audio_buffer += chunk
            
            # Check for speech in this frame
            current_time = time.time()
            if speech_start_time is None:
                speech_start_time = current_time
            
            if is_speech_detected(chunk, SPEECH_THRESHOLD):
                if not speech_detected:
                    log("Speech detected, continuing capture...")
                    speech_detected = True
                silence_start_time = None  # Reset silence timer
            else:
                # No speech detected
                if speech_detected:
                    # We were detecting speech, now we're in silence
                    if silence_start_time is None:
                        silence_start_time = current_time
                    elif current_time - silence_start_time >= SILENCE_DURATION:
                        # Been silent long enough
                        log(f"Silence detected for {SILENCE_DURATION}s, stopping capture")
                        break
                else:
                    # Haven't detected speech yet, keep waiting
                    if current_time - speech_start_time >= MIN_SPEECH_DURATION:
                        # Been waiting too long without speech, give up
                        log("No speech detected within minimum duration, stopping")
                        break
            
            # Safety check: don't capture too long
            if current_time - speech_start_time >= MAX_SPEECH_DURATION:
                log(f"Maximum speech duration ({MAX_SPEECH_DURATION}s) reached, stopping")
                break

        if len(audio_buffer) == 0:
            log("No audio captured")
            return b""

        # Resample from mic sample rate to output sample rate
        if mic_sr != OUT_SR:
            audio_buffer, _ = audioop.ratecv(audio_buffer, 2, 1, mic_sr, OUT_SR, None)

        log(f"Captured {len(audio_buffer)} bytes PCM16 @ {OUT_SR} Hz.")
        return audio_buffer

    finally:
        try:
            if porcupine: porcupine.delete()
        except: pass
        try:
            if arec: arec.terminate()
        except: pass
        try:
            if aplay and aplay.stdin:
                aplay.stdin.close()
        except: pass
        try:
            if aplay: aplay.terminate()
        except: pass

# ---------- aplay with stderr logger (debug ALSA quickly) ----------
def _pipe_logger(name, pipe):
    for line in iter(pipe.readline, b''):
        try: print(f"[{name}] {line.decode().rstrip()}", flush=True)
        except Exception: pass

def spawn_aplay_for_chatgpt():
    args = ["aplay","-t","raw","-f","S16_LE","-r",str(OUT_SR),"-c","1"]
    if OUT_DEVICE: args += ["-D", OUT_DEVICE]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    threading.Thread(target=_pipe_logger, args=("aplay", p.stderr), daemon=True).start()
    log("aplay started: " + " ".join(args))
    return p

# Global variables for cleanup
aplay_process = None
ws_connection = None

def signal_handler(signum, frame):
    """Handle shutdown gracefully"""
    log("Shutdown signal received, cleaning up...")
    try:
        if aplay_process and aplay_process.stdin:
            aplay_process.stdin.close()
        if aplay_process:
            aplay_process.terminate()
    except Exception:
        pass
    sys.exit(0)

async def main():
    global aplay_process, ws_connection
    
    aplay_process = spawn_aplay_for_chatgpt()
    conversation_started = False

    try:
        # Create headers for the websocket connection
        headers = [
            ("Authorization", f"Bearer {API_KEY}"),
            ("OpenAI-Beta", "realtime=v1")
        ]
        
        # Try different websockets connection methods for compatibility
        try:
            # Method 1: Try with extra_headers (newer websockets versions)
            async with websockets.connect(
                URL,
                extra_headers=headers,
                max_size=16*1024*1024,
            ) as ws:
                ws_connection = ws
                log("WS connected (with extra_headers).")
                await handle_websocket_session(ws)
        except TypeError as e:
            if "extra_headers" in str(e):
                log("extra_headers not supported, trying alternative method...")
                # Method 2: Try with additional_headers (older websockets versions)
                try:
                    async with websockets.connect(
                        URL,
                        additional_headers=headers,
                        max_size=16*1024*1024,
                    ) as ws:
                        ws_connection = ws
                        log("WS connected (with additional_headers).")
                        await handle_websocket_session(ws)
                except TypeError as e2:
                    if "additional_headers" in str(e2):
                        log("Headers not supported, trying basic connection...")
                        # Method 3: Basic connection without headers (will need to send auth in first message)
                        async with websockets.connect(
                            URL,
                            max_size=16*1024*1024,
                        ) as ws:
                            ws_connection = ws
                            log("WS connected (basic).")
                            await handle_websocket_session(ws)
                    else:
                        raise e2
            else:
                raise e

    except Exception as e:
        log(f"Error in main: {e}")
    finally:
        # Cleanup
        try:
            if aplay_process and aplay_process.stdin: 
                aplay_process.stdin.close()
        except Exception: pass
        try: 
            if aplay_process:
                aplay_process.terminate()
        except Exception: pass

async def handle_websocket_session(ws):
    """Handle the websocket session once connected"""
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
                        try: aplay_process.stdin.write(pcm)
                        except BrokenPipeError: pass
                    except Exception as e:
                        log(f"[audio.decode.error] {e}")

            if t in ("response.text.delta", "response.output_text.delta", "response.audio_transcript.delta"):
                sys.stdout.write(evt.get("delta","")); sys.stdout.flush()

            if t in ("response.done", "response.completed"):
                try: aplay_process.stdin.write(bytes([0] * (OUT_SR * 2 // 10)))  # ~100 ms silence
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
            "input_audio_format":"pcm16",
            "output_audio_format":"pcm16",
            "voice": VOICE,
            "instructions": get_system_prompt()
        }
    }))
    log(">> session.update sent")

    # ---- Wait for wake word before sending initial greeting ----
    log("Waiting for wake word before starting conversation...")
    pcm = await asyncio.to_thread(capture_audio_after_wakeword)
    if not pcm or len(pcm) < int(OUT_SR * 2 * 0.1):   # ~100 ms min
        log("Too little audio; skipping.")
        return

    log("Sending audio to API...")
    await ws.send(json.dumps({"type":"input_audio_buffer.clear"}))
    for i in range(0, len(pcm), 8192):
        b64 = base64.b64encode(pcm[i:i+8192]).decode("ascii")
        await ws.send(json.dumps({"type":"input_audio_buffer.append","audio": b64}))
    await ws.send(json.dumps({"type":"input_audio_buffer.commit"}))

    await ws.send(json.dumps({
        "type":"response.create",
        "response":{"modalities":["audio","text"], "instructions":"Give the opening greeting message."}
    }))
    log("Audio sent, waiting for response...")

    # ---- Wake → capture → send loop ----
    while True:
        pcm = await asyncio.to_thread(capture_audio_after_wakeword)
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
            "response":{"modalities":["audio","text"], "instructions":"Answer briefly as Solstis medical assistant."}
        }))
        log("Audio sent, waiting for response...")

    await reader_task  # never reached

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    log(f"🩺 Solstis Voice Assistant with Picovoice starting...")
    log(f"User: {USER_NAME}")
    log(f"Voice: {VOICE}")
    log(f"Wake Word File: {WAKEWORD_PATH}")
    log(f"Speech Detection - Threshold: {SPEECH_THRESHOLD}, Silence Duration: {SILENCE_DURATION}s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Shutdown complete.")

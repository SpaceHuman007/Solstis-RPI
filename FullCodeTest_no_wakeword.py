#!/usr/bin/env python3
# Solstis Voice Assistant - No Wake Word Version
# Continuous listening → OpenAI Realtime → aplay

import asyncio, base64, json, os, signal, subprocess, sys, threading, time, io, wave, types, audioop
from datetime import datetime
from dotenv import load_dotenv
import websockets

load_dotenv(override=True)

# --------- Config (.env) ---------
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4o-realtime-preview")
URL   = f"wss://api.openai.com/v1/realtime?model={MODEL}"

# Playback device: try different options
OUT_DEVICE = os.getenv("AUDIO_DEVICE")     # e.g. "plughw:1,0"
OUT_SR     = int(os.getenv("OUT_SR", "24000"))

VOICE      = os.getenv("VOICE", "verse")
USER_NAME  = os.getenv("USER_NAME", "Shaniqua")

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

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

# ---------- aplay with stderr logger (debug ALSA quickly) ----------
def _pipe_logger(name, pipe):
    for line in iter(pipe.readline, b''):
        try: print(f"[{name}] {line.decode().rstrip()}", flush=True)
        except Exception: pass

def spawn_aplay():
    # Try different audio devices
    devices_to_try = [
        OUT_DEVICE,  # User specified
        "plughw:1,0",  # Common ReSpeaker output
        "plughw:0,0",  # Default device
        None  # System default
    ]
    
    for device in devices_to_try:
        if device is None:
            args = ["aplay","-t","raw","-f","S16_LE","-r",str(OUT_SR),"-c","1"]
        else:
            args = ["aplay","-t","raw","-f","S16_LE","-r",str(OUT_SR),"-c","1","-D", device]
        
        try:
            p = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            threading.Thread(target=_pipe_logger, args=("aplay", p.stderr), daemon=True).start()
            log(f"aplay started successfully with device: {device or 'default'}")
            return p
        except Exception as e:
            log(f"Failed to start aplay with device {device}: {e}")
            continue
    
    raise RuntimeError("Could not start aplay with any audio device")

# ---------- Simple audio capture using arecord ----------
def capture_audio_simple(duration=3, sample_rate=24000):
    """Capture audio using arecord command"""
    try:
        # Try different microphone devices
        devices_to_try = [
            "plughw:CARD=seeed2micvoicec,DEV=0",  # ReSpeaker device
            "plughw:2,0",  # Common ReSpeaker input
            "plughw:1,0",  # Alternative
            "default"  # System default
        ]
        
        for device in devices_to_try:
            try:
                cmd = [
                    "arecord", "-D", device, "-r", str(sample_rate), 
                    "-c", "1", "-f", "S16_LE", "-t", "wav", "-d", str(duration)
                ]
                
                log(f"Trying to record with device: {device}")
                result = subprocess.run(cmd, capture_output=True, timeout=duration+2)
                
                if result.returncode == 0 and len(result.stdout) > 1000:  # Has audio data
                    log(f"Successfully recorded {len(result.stdout)} bytes from {device}")
                    return result.stdout
                else:
                    log(f"Failed to record from {device}: {result.stderr.decode()}")
                    
            except Exception as e:
                log(f"Error with device {device}: {e}")
                continue
                
        raise RuntimeError("Could not record audio from any device")
        
    except Exception as e:
        log(f"Audio capture failed: {e}")
        return None

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
    
    aplay_process = spawn_aplay()
    conversation_started = False

    try:
        async with websockets.connect(
            URL,
            extra_headers=[("Authorization", f"Bearer {API_KEY}"),
                           ("OpenAI-Beta", "realtime=v1")],
            max_size=16*1024*1024,
        ) as ws:
            ws_connection = ws
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

            # ---- Send initial greeting ----
            log("Sending initial greeting...")
            await ws.send(json.dumps({
                "type":"response.create",
                "response":{"modalities":["audio","text"], "instructions":"Give the opening greeting message."}
            }))
            conversation_started = True

            # ---- Continuous listening loop ----
            while True:
                log("Press ENTER to start recording (or type 'quit' to exit)...")
                user_input = input().strip().lower()
                
                if user_input == 'quit':
                    break
                
                log("Recording for 3 seconds...")
                audio_data = await asyncio.to_thread(capture_audio_simple, 3, OUT_SR)
                
                if not audio_data:
                    log("No audio captured, trying again...")
                    continue
                
                # Convert WAV to PCM16
                try:
                    wf = wave.open(io.BytesIO(audio_data), 'rb')
                    if wf.getsampwidth() == 2 and wf.getnchannels() == 1:
                        src_hz = wf.getframerate()
                        src_pcm = wf.readframes(wf.getnframes())
                        wf.close()
                        
                        # Resample to target rate if needed
                        if src_hz != OUT_SR:
                            src_pcm, _ = audioop.ratecv(src_pcm, 2, 1, src_hz, OUT_SR, None)
                        
                        log(f"Sending {len(src_pcm)} bytes of audio to API...")
                        
                        # Send audio to API
                        await ws.send(json.dumps({"type":"input_audio_buffer.clear"}))
                        for i in range(0, len(src_pcm), 8192):
                            b64 = base64.b64encode(src_pcm[i:i+8192]).decode("ascii")
                            await ws.send(json.dumps({"type":"input_audio_buffer.append","audio": b64}))
                        await ws.send(json.dumps({"type":"input_audio_buffer.commit"}))

                        await ws.send(json.dumps({
                            "type":"response.create",
                            "response":{"modalities":["audio","text"], "instructions":"Answer briefly as Solstis medical assistant."}
                        }))
                        log("Audio sent, waiting for response...")
                    else:
                        log("Invalid audio format")
                        
                except Exception as e:
                    log(f"Error processing audio: {e}")

            await reader_task  # never reached

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

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    log(f"🩺 Solstis Voice Assistant (No Wake Word) starting...")
    log(f"User: {USER_NAME}")
    log(f"Voice: {VOICE}")
    log("This version uses manual recording - press ENTER to record")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Shutdown complete.")

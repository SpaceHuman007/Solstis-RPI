#!/usr/bin/env python3
# Solstis Voice Assistant for Raspberry Pi 4
# ReSpeaker wake word → mic.listen() → PCM16 @ 24k → OpenAI Realtime → aplay

import asyncio, base64, json, os, signal, subprocess, sys, threading, time, io, wave, types, audioop
from datetime import datetime
from dotenv import load_dotenv
import websockets

# ReSpeaker library (apt/pip install respeaker + pocketsphinx)
from respeaker import Microphone
from respeaker.bing_speech_api import BingSpeechAPI

load_dotenv(override=True)

# --------- Config (.env) ---------
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4o-realtime-preview")
URL   = f"wss://api.openai.com/v1/realtime?model={MODEL}"

# Playback device: pick a REAL output (headphones/HDMI/USB DAC), not the ReSpeaker card
OUT_DEVICE = os.getenv("AUDIO_DEVICE")     # e.g. "plughw:1,0"
OUT_SR     = int(os.getenv("OUT_SR", "24000"))

VOICE      = os.getenv("VOICE", "verse")
WAKEWORD   = os.getenv("WAKEWORD", "solstis")
USER_NAME  = os.getenv("USER_NAME", "User")

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

Examples:

USER: I cut my finger with a kitchen knife. It's bleeding a lot.
SOLSTIS: First—are you feeling faint, dizzy, or having trouble breathing?

USER: No, just a little shaky.
SOLSTIS: Good. Do you have access to clean, running water?

USER: Yes.
SOLSTIS: Great. Rinse the cut under cool water. Remove any rings first. Let me know when you're done.

USER: Done.
SOLSTIS: From the highlighted space, take the small gauze. Press gently for 5 minutes. Let me know when you're done.

USER: I can't find it.
SOLSTIS: No problem—check the small highlighted section. If it's not there, we can use the large gauze in the highlighted section instead.

USER: Found it.
SOLSTIS: Well done. After the bleeding slows, add a thin layer of antibiotic ointment if you have it, then place a bandage from the highlighted space so the pad covers the cut; smooth the tabs so they don't pinch. Let me know when you're done.

USER: It's been 5 minutes and the bleeding hasn't stopped.
SOLSTIS: Since direct pressure didn't work, let's try the QuickClot gauze from the highlighted space. Apply it directly to the cut and press firmly for 3 minutes. Let me know when you're done.

USER: It still hasn't stopped bleeding.
SOLSTIS: The bleeding is not responding to standard treatment. This requires immediate medical attention. Please call 9-1-1 or go to the nearest emergency room. Keep applying pressure while you get help.

USER: I cut my foot and I'm feeling faint.
SOLSTIS: Feeling faint is common with foot injuries. First, lie down and elevate your legs to improve blood flow to your brain. This should help with the dizziness. Once you're stable, we can address the foot injury. Let me know when you're feeling better.

USER: I'm still feeling dizzy after lying down.
SOLSTIS: Stay lying down and keep your legs elevated. If the dizziness persists for more than 10 minutes or you feel worse, then we should consider medical help. For now, focus on staying calm and breathing normally.

USER: I cut my foot and I'm feeling faint.
SOLSTIS: How much blood is there and how big is the cut? This will help me determine the best approach.

USER: There's a lot of blood and it's a deep cut.
SOLSTIS: Since there's heavy bleeding, we need to control that first. Apply direct pressure with gauze from the highlighted space. Once the bleeding slows, then we can address the faintness by having you lie down and elevate your legs.

USER: I have a really bad cramp in my shoulder.
SOLSTIS: How's your hydration? Cramps are often caused by dehydration. If you're not well-hydrated, try mixing the electrolyte powder from the highlighted space with water and drink it. Also, gentle stretching and massage can help.

USER: I got a burn.
SOLSTIS: How bad is the burn? What size is it and where is it located? This will help me determine if we can treat it here or need emergency care.

Only give instructions using supplies from this kit (or common home items). Do not invent tools or procedures. You are not a diagnostic or medical authority—you are a calm first responder assistant."""

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
def capture_pcm16_after_wakeword_respeaker(keyword="solstis", dst_hz=24000):
    """
    1) Blocks until Microphone().wakeup(keyword) triggers.
    2) Uses mic.listen() to collect speech.
    3) Returns raw PCM16 mono bytes at dst_hz (default 24 kHz).
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
    conversation_started = False

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
                "input_audio_format":"pcm16",
                "output_audio_format":"pcm16",
                "voice": VOICE,
                "instructions": get_system_prompt()
            }
        }))
        log(">> session.update sent")

        # ---- Initial greeting ----
        await ws.send(json.dumps({
            "type":"response.create",
            "response":{"modalities":["audio","text"], "instructions":"Give the opening greeting message."}
        }))
        log(">> initial greeting sent")
        conversation_started = True

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
                "response":{"modalities":["audio","text"], "instructions":"Answer briefly as Solstis medical assistant."}
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
    log(f"🩺 Solstis Voice Assistant starting...")
    log(f"User: {USER_NAME}")
    log(f"Wake Word: '{WAKEWORD}'")
    log(f"Voice: {VOICE}")
    asyncio.run(main())
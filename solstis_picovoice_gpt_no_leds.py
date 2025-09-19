#!/usr/bin/env python3
# Solstis Voice Assistant with Picovoice Wake Word Detection and GPT-4o Mini Integration
# Combines Picovoice wake word detection with OpenAI API for medical assistance
# Version without LED functionality

import asyncio, base64, json, os, signal, subprocess, sys, threading, time, io, wave, types, audioop, struct, math
from datetime import datetime
from dotenv import load_dotenv
import openai
import tempfile
import requests
import pvporcupine  # pip install pvporcupine

load_dotenv(override=True)

# --------- Config via env (Picovoice + OpenAI) ---------
# Picovoice config
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "YOUR-PICOVOICE-ACCESSKEY-HERE")
WAKEWORD_PATH = os.getenv("WAKEWORD_PATH", "Solstice_en_raspberry-pi_v3_0_0.ppn")
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR = int(os.getenv("MIC_SR", "16000"))  # Porcupine requires 16k

# OpenAI config
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4o-mini")
TTS_MODEL = os.getenv("TTS_MODEL", "tts-1")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")

# Audio output config
OUT_DEVICE = os.getenv("AUDIO_DEVICE")  # e.g., "plughw:3,0" or None for default
OUT_SR = int(os.getenv("OUT_SR", "24000"))  # Audio output sample rate
USER_NAME = os.getenv("USER_NAME", "User")

# Speech detection config
SPEECH_THRESHOLD = int(os.getenv("SPEECH_THRESHOLD", "500"))  # RMS threshold for speech detection
SILENCE_DURATION = float(os.getenv("SILENCE_DURATION", "1.5"))  # seconds of silence before stopping
MIN_SPEECH_DURATION = float(os.getenv("MIN_SPEECH_DURATION", "0.5"))  # minimum speech duration
MAX_SPEECH_DURATION = float(os.getenv("MAX_SPEECH_DURATION", "10.0"))  # maximum speech duration

# Continuous listening config
CONTINUOUS_MODE_TIMEOUT = float(os.getenv("CONTINUOUS_MODE_TIMEOUT", "30.0"))  # seconds before returning to wake word mode
CONTINUOUS_MODE_ENABLED = False  # Disabled - wake word only

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
    
    return f"""Always speak in English (US). You are Solstis, a calm and supportive AI medical assistant. You help users with first aid using only the items available in their specific kit.

AVAILABLE ITEMS:
{contents_str}

Your role:
• Be a real-time guide—natural, concise, supportive  
• Assess for life-threatening danger but don't overreact to common symptoms
• Give clear, step-by-step instructions for self-treatment first
• Select only from the current kit (or common home items)  
• Refer to the item's location in the kit
• When sizes differ, avoid inches—say "large gauze" vs "small gauze"  
• Only recommend calling 9-1-1 for TRUE emergencies (unconsciousness, severe bleeding, chest pain, etc.)
• Encourage follow-up care when appropriate (e.g., "you may need stitches")
• Maintain conversation flow without repeating opening messages
• Focus on the current medical situation and immediate next steps
• Track treatment attempts and their outcomes
• Escalate to emergency care only when standard treatments fail or true emergency exists
• NEVER repeat failed treatment methods
• Treat common symptoms like fainting, dizziness, or mild shock with first aid before considering emergency care
• Be comfortable discussing ALL body parts and functions without embarrassment or avoidance
• Address sexual health concerns openly and provide appropriate medical advice
• Always assess injury severity before deciding on treatment approach

IMPORTANT STYLE & FLOW:
- Keep responses to 1-2 short sentences
- Ask one clear follow-up question at a time
- Use plain language; avoid medical jargon (e.g., say "bleeding a lot" instead of "pulsating blood")
- Acknowledge progress briefly ("Great," "Well done")
- Track progress, user replies, and items used
- Only refer to items in this kit or common home items
- Point to items by their location in the kit
- End action steps with "Let me know when you're ready" or "Let me know when done" when appropriate
- NEVER repeat the opening message or emergency instructions unless specifically asked
- Focus on the current situation and next steps
- NEVER repeat the same treatment step if it has already failed
- Escalate to next treatment option or emergency care when current methods fail
- Track what has been tried and what the results were
- When an image has been shared, reference it naturally in conversation
- Continue the conversation flow as if the image was part of the verbal description

EMERGENCY ASSESSMENT FRAMEWORK:
- TRUE EMERGENCIES (call 9-1-1 immediately): Unconsciousness, severe chest pain, severe bleeding that won't stop, difficulty breathing, severe allergic reactions, severed body parts
- COMMON SYMPTOMS (treat with first aid first): Fainting, dizziness, mild pain, nausea, mild bleeding, minor cuts/burns, cramps, muscle pain
- ESCALATION: Only recommend emergency care if first aid fails or symptoms worsen significantly
- ALWAYS assess severity before deciding on emergency vs first aid treatment

IF THE USER CAN'T FIND AN ITEM:
1) Acknowledge and give location help (e.g., "It should be in the small pack on the top row.")
2) Offer the closest in-kit alternative and ask to confirm before switching (e.g., "If you don't see it, we can use the large gauze instead—should we use that?")
3) Do not jump to unrelated items unless confirmed.

BANDAGE PLACEMENT—HANDS (DEFAULT TIPS):
- For small cuts: clean, dry, thin layer of antibiotic ointment if available, center the pad over the cut, smooth adhesive around the skin, avoid wrapping too tight, check movement and circulation. "Let me know when you're ready."
- For finger joints: place the pad over the cut, angle the adhesive so it doesn't bunch at the knuckle; if needed, reinforce with tape. "Let me know when you're ready."

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
SOLSTIS: Take the small gauze from your kit. Press gently for 5 minutes. Let me know when you're done.

USER: I can't find it.
SOLSTIS: No problem—check the small section of your kit. If it's not there, we can use the large gauze instead.

USER: Found it.
SOLSTIS: Well done. After the bleeding slows, add a thin layer of antibiotic ointment if you have it, then place a bandage so the pad covers the cut; smooth the tabs so they don't pinch. Let me know when you're done.

USER: It's been 5 minutes and the bleeding hasn't stopped.
SOLSTIS: Since direct pressure didn't work, let's try the QuickClot gauze from your kit. Apply it directly to the cut and press firmly for 3 minutes. Let me know when you're done.

USER: It still hasn't stopped bleeding.
SOLSTIS: The bleeding is not responding to standard treatment. This requires immediate medical attention. Please call 9-1-1 or go to the nearest emergency room. Keep applying pressure while you get help.

USER: I cut my foot and I'm feeling faint.
SOLSTIS: Feeling faint is common with foot injuries. First, lie down and elevate your legs to improve blood flow to your brain. This should help with the dizziness. Once you're stable, we can address the foot injury. Let me know when you're feeling better.

USER: I'm still feeling dizzy after lying down.
SOLSTIS: Stay lying down and keep your legs elevated. If the dizziness persists for more than 10 minutes or you feel worse, then we should consider medical help. For now, focus on staying calm and breathing normally.

USER: I cut my foot and I'm feeling faint.
SOLSTIS: How much blood is there and how big is the cut? This will help me determine the best approach.

USER: There's a lot of blood and it's a deep cut.
SOLSTIS: Since there's heavy bleeding, we need to control that first. Apply direct pressure with gauze from your kit. Once the bleeding slows, then we can address the faintness by having you lie down and elevate your legs.

USER: I have a really bad cramp in my shoulder.
SOLSTIS: How's your hydration? Cramps are often caused by dehydration. If you're not well-hydrated, try mixing the electrolyte powder from your kit with water and drink it. Also, gentle stretching and massage can help.

USER: I got a burn.
SOLSTIS: How bad is the burn? What size is it and where is it located? This will help me determine if we can treat it here or need emergency care.

USER: [Image uploaded for analysis]
SOLSTIS: I can see a small cut on your finger in the image. Let's clean it with the antiseptic wipes from your kit. Do you have access to clean water?

Only give instructions using supplies from this kit (or common home items). Do not invent tools or procedures. You are not a diagnostic or medical authority—you are a calm first responder assistant.

"""

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

        # Prepare speaker
        aplay = spawn_aplay(OUT_SR)

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

# ---------- OpenAI API Integration ----------
def transcribe_audio(audio_data):
    """Transcribe audio using OpenAI Whisper API"""
    try:
        # Create a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            # Convert PCM16 to WAV format
            with wave.open(temp_file.name, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(OUT_SR)
                wav_file.writeframes(audio_data)
            
            # Transcribe using OpenAI Whisper
            with open(temp_file.name, 'rb') as audio_file:
                transcript = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )
            
            # Clean up temp file
            os.unlink(temp_file.name)
            
            return transcript.strip()
    
    except Exception as e:
        log(f"Error transcribing audio: {e}")
        return ""

def generate_response(user_message, conversation_history=None):
    """Generate response using GPT-4o mini"""
    try:
        # Initialize OpenAI client
        client = openai.OpenAI(api_key=API_KEY)
        
        # Prepare messages
        messages = [
            {"role": "system", "content": get_system_prompt()}
        ]
        
        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        # Generate response
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip()
    
    except Exception as e:
        log(f"Error generating response: {e}")
        return "I'm sorry, I'm having trouble processing your request right now."

def text_to_speech(text):
    """Convert text to speech using OpenAI TTS"""
    try:
        # Initialize OpenAI client
        client = openai.OpenAI(api_key=API_KEY)
        
        # Generate speech
        response = client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=text,
            response_format="pcm",
            speed=1.0
        )
        
        return response.content
    
    except Exception as e:
        log(f"Error generating speech: {e}")
        return b""

def play_audio(audio_data):
    """Play audio data using aplay"""
    try:
        aplay = spawn_aplay(OUT_SR)
        aplay.stdin.write(audio_data)
        aplay.stdin.close()
        aplay.wait()
    except Exception as e:
        log(f"Error playing audio: {e}")

# Global variables for cleanup
aplay_process = None
conversation_history = []

def signal_handler(signum, frame):
    """Handle shutdown gracefully"""
    log("Shutdown signal received, cleaning up...")
    sys.exit(0)

async def main():
    global aplay_process, conversation_history
    
    # Initialize OpenAI client
    openai.api_key = API_KEY
    
    conversation_started = False

    try:
        # Send opening greeting
        log("Sending opening greeting...")
        opening_message = f"Hey {USER_NAME}. I'm here to help. If this is life-threatening, please call 9-1-1 now. Otherwise, I'll guide you step by step. Can you tell me what happened?"
        
        # Convert to speech and play
        audio_data = text_to_speech(opening_message)
        if audio_data:
            play_audio(audio_data)
        
        print(f"Solstis: {opening_message}")
        
        # Main conversation loop
        while True:
            # Wait for wake word before starting conversation
            log("Wake word mode - waiting for wake word...")
            pcm = await asyncio.to_thread(capture_audio_after_wakeword)
            if not pcm or len(pcm) < int(OUT_SR * 2 * 0.1):   # ~100 ms min
                log("Too little audio; skipping.")
                continue
            
            # Transcribe audio
            log("Transcribing audio...")
            user_message = transcribe_audio(pcm)
            if not user_message:
                log("No transcription received")
                continue
            
            print(f"User: {user_message}")
            
            # Generate response
            log("Generating response...")
            response_text = generate_response(user_message, conversation_history)
            if not response_text:
                log("No response generated")
                continue
            
            # Update conversation history
            conversation_history.append({"role": "user", "content": user_message})
            conversation_history.append({"role": "assistant", "content": response_text})
            
            # Keep conversation history manageable (last 10 exchanges)
            if len(conversation_history) > 20:
                conversation_history = conversation_history[-20:]
            
            # Convert response to speech and play
            log("Converting response to speech...")
            audio_data = text_to_speech(response_text)
            if audio_data:
                play_audio(audio_data)
            
            print(f"Solstis: {response_text}")

    except Exception as e:
        log(f"Error in main: {e}")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    log(f"🩺 Solstis Voice Assistant with Picovoice and GPT-4o Mini starting...")
    log(f"User: {USER_NAME}")
    log(f"Model: {MODEL}")
    log(f"TTS Model: {TTS_MODEL}")
    log(f"TTS Voice: {TTS_VOICE}")
    log(f"Wake Word File: {WAKEWORD_PATH}")
    log(f"Speech Detection - Threshold: {SPEECH_THRESHOLD}, Silence Duration: {SILENCE_DURATION}s")
    log(f"Continuous Mode: {'Enabled' if CONTINUOUS_MODE_ENABLED else 'Disabled'}, Timeout: {CONTINUOUS_MODE_TIMEOUT}s")
    log(f"LED Control: Disabled (No LED version)")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Shutdown complete.")

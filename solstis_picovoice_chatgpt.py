#!/usr/bin/env python3
# Solstis Voice Assistant with Picovoice Wake Word Detection and ChatGPT Integration
# Combines Picovoice wake word detection with OpenAI Realtime API for medical assistance

import asyncio, base64, json, os, signal, subprocess, sys, threading, time, io, wave, types, audioop, struct, math
from datetime import datetime
from dotenv import load_dotenv
import websockets
import pvporcupine  # pip install pvporcupine

# LED Control imports
try:
    from rpi_ws281x import *
    LED_CONTROL_AVAILABLE = True
except ImportError:
    LED_CONTROL_AVAILABLE = False
    print("Warning: rpi_ws281x not available. LED control disabled.")

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

# Continuous listening config
CONTINUOUS_MODE_TIMEOUT = float(os.getenv("CONTINUOUS_MODE_TIMEOUT", "30.0"))  # seconds before returning to wake word mode
# CONTINUOUS_MODE_ENABLED = os.getenv("CONTINUOUS_MODE_ENABLED", "true").lower() == "true"
CONTINUOUS_MODE_ENABLED = False  # Disabled - wake word only

# LED Control config
LED_ENABLED = os.getenv("LED_ENABLED", "true").lower() == "true" and LED_CONTROL_AVAILABLE
LED_COUNT = int(os.getenv("LED_COUNT", "788"))  # Number of LED pixels
LED_PIN = int(os.getenv("LED_PIN", "13"))  # GPIO pin connected to the pixels
LED_FREQ_HZ = int(os.getenv("LED_FREQ_HZ", "800000"))  # LED signal frequency
LED_DMA = int(os.getenv("LED_DMA", "10"))  # DMA channel
LED_BRIGHTNESS = int(os.getenv("LED_BRIGHTNESS", "70"))  # LED brightness (0-255)
LED_INVERT = os.getenv("LED_INVERT", "false").lower() == "true"
LED_CHANNEL = int(os.getenv("LED_CHANNEL", "1"))  # LED channel
LED_DURATION = float(os.getenv("LED_DURATION", "5.0"))  # How long to keep LEDs on

# LED pulsing (speaking indicator) config
SPEAK_LEDS_START1 = int(os.getenv("SPEAK_LEDS_START1", "640"))
SPEAK_LEDS_END1   = int(os.getenv("SPEAK_LEDS_END1", "665"))
SPEAK_LEDS_START2 = int(os.getenv("SPEAK_LEDS_START2", "690"))
SPEAK_LEDS_END2   = int(os.getenv("SPEAK_LEDS_END2", "730"))
SPEAK_COLOR_R     = int(os.getenv("SPEAK_COLOR_R", "0"))
SPEAK_COLOR_G     = int(os.getenv("SPEAK_COLOR_G", "180"))
SPEAK_COLOR_B     = int(os.getenv("SPEAK_COLOR_B", "255"))

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ---------- LED Control System ----------
# LED mapping for kit items (you'll need to adjust these ranges based on your physical layout)
LED_MAPPINGS = {
    "band-aids": (0, 25),
    "gauze pads": (26, 50),
    "roll gauze": (51, 75),
    "abd pad": (76, 100),
    "medical tape": (101, 125),
    "antibiotic ointment": (126, 150),
    "tweezers": (151, 175),
    "trauma shears": (176, 200),
    "quickclot gauze": (201, 225),
    "hemostatic wipe": (201, 225), 
    "burn gel dressing": (226, 250),
    "burn spray": (251, 275),
    "sting bite relief": (276, 300),
    "eye wash bottle": (301, 325),
    "glucose gel": (326, 350),
    "electrolyte powder": (351, 375),
    "ace bandage": (376, 400),
    "cold pack": (401, 425),
    "triangle bandage": (426, 450),
}

# Global LED strip object
led_strip = None
speak_pulse_thread = None
speak_pulse_stop = threading.Event()

def init_led_strip():
    """Initialize the LED strip"""
    global led_strip
    if not LED_ENABLED:
        log("LED control disabled")
        return False
    
    try:
        time.sleep(2.0)  # Give LEDs power time before driving DIN
        led_strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA,
                                      LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
        led_strip.begin()
        log(f"LED strip initialized: {LED_COUNT} pixels")
        return True
    except Exception as e:
        log(f"Failed to initialize LED strip: {e}")
        return False

def clear_all_leds():
    """Turn off all LEDs"""
    if not LED_ENABLED or not led_strip:
        return
    
    try:
        for i in range(led_strip.numPixels()):
            led_strip.setPixelColor(i, 0)
        led_strip.show()
    except Exception as e:
        log(f"Error clearing LEDs: {e}")

def _pulse_range_once(start_idx, end_idx, r, g, b, brightness):
    if not LED_ENABLED or not led_strip:
        return
    try:
        for i in range(start_idx, end_idx + 1):
            if i < led_strip.numPixels():
                led_strip.setPixelColor(i, Color(int(r*brightness), int(g*brightness), int(b*brightness)))
        led_strip.show()
    except Exception as e:
        log(f"Error during pulse frame: {e}")

def _speak_pulser_loop():
    # Define two ranges to pulse
    ranges = [
        (max(0, SPEAK_LEDS_START1), max(SPEAK_LEDS_START1, SPEAK_LEDS_END1)),
        (max(0, SPEAK_LEDS_START2), max(SPEAK_LEDS_START2, SPEAK_LEDS_END2))
    ]
    r, g, b = SPEAK_COLOR_R, SPEAK_COLOR_G, SPEAK_COLOR_B
    t = 0.0
    try:
        while not speak_pulse_stop.is_set() and LED_ENABLED and led_strip:
            brightness = 0.6 + 0.4 * (0.5 * (1 + math.sin(t)))
            # Pulse both ranges
            for start_idx, end_idx in ranges:
                _pulse_range_once(start_idx, end_idx, r, g, b, brightness)
            t += 0.25
            speak_pulse_stop.wait(0.08)
    except Exception as e:
        log(f"Speak pulser error: {e}")

def start_speak_pulse():
    global speak_pulse_thread
    if not LED_ENABLED or not led_strip:
        return
    try:
        speak_pulse_stop.clear()
        if speak_pulse_thread and speak_pulse_thread.is_alive():
            return
        speak_pulse_thread = threading.Thread(target=_speak_pulser_loop, daemon=True)
        speak_pulse_thread.start()
    except Exception as e:
        log(f"Failed to start speak pulser: {e}")

def stop_speak_pulse():
    try:
        speak_pulse_stop.set()
    except Exception:
        pass

def light_item_leds(item_name, color=(0, 240, 255)):
    """Light up LEDs for a specific item"""
    if not LED_ENABLED or not led_strip:
        log(f"LED control not available - would light: {item_name}")
        return
    
    # Find the item in mappings (case-insensitive)
    item_key = None
    for key in LED_MAPPINGS.keys():
        if key.lower() in item_name.lower() or item_name.lower() in key.lower():
            item_key = key
            break
    
    if not item_key:
        log(f"No LED mapping found for item: {item_name}")
        return
    
    start, end = LED_MAPPINGS[item_key]
    log(f"Lighting LEDs {start}-{end} for item: {item_name}")
    
    try:
        # Clear all LEDs first
        clear_all_leds()
        
        # Light up the specific range
        for i in range(start, end + 1):
            if i < led_strip.numPixels():
                led_strip.setPixelColor(i, Color(*color))
        
        led_strip.show()
        
        # Schedule to turn off after LED_DURATION seconds
        def turn_off_leds():
            time.sleep(LED_DURATION)
            clear_all_leds()
        
        threading.Thread(target=turn_off_leds, daemon=True).start()
        
    except Exception as e:
        log(f"Error lighting LEDs for {item_name}: {e}")

def parse_response_for_items(response_text):
    """Parse AI response text to identify mentioned items and light appropriate LEDs"""
    if not LED_ENABLED:
        return
    
    # List of items to look for in the response
    items_to_check = [
        "band-aid", "band aid", "bandaid",
        "gauze", "gauze pad", "gauze pads",
        "roll gauze",
        "abd pad", "abd",
        "tape", "medical tape",
        "antibiotic", "ointment",
        "tweezers",
        "shears", "trauma shears",
        "quickclot", "hemostatic",
        "burn gel", "burn dressing",
        "burn spray",
        "sting", "bite relief",
        "eye wash", "eye wash bottle",
        "glucose", "glucose gel",
        "electrolyte", "electrolyte powder",
        "ace bandage", "elastic bandage",
        "cold pack",
        "triangle bandage"
    ]
    
    response_lower = response_text.lower()
    
    for item in items_to_check:
        if item in response_lower:
            log(f"Found item mention: {item}")
            light_item_leds(item)
            break  # Only light one item at a time

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
• Refer to the item's highlighted space (not "LED compartment")  
• When sizes differ, avoid inches—say "large X highlighted in blue" vs "small X highlighted in orange"  
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
- Point to items by color-coded highlight: "from the highlighted space," "the blue one," or "the orange one"
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
1) Acknowledge and give location help (e.g., "It should be in the small pack highlighted in orange on the top row.")
2) Offer the closest in-kit alternative and ask to confirm before switching (e.g., "If you don't see it, we can use the large gauze highlighted in blue instead—should we use that?")
3) Do not jump to unrelated items unless confirmed.

BANDAGE PLACEMENT—HANDS (DEFAULT TIPS):
- For small cuts: clean, dry, thin layer of antibiotic ointment if available, center the pad over the cut, smooth adhesive around the skin, avoid wrapping too tight, check movement and circulation. "Let me know when you're ready."
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

USER: [Image uploaded for analysis]
SOLSTIS: I can see a small cut on your finger in the image. Let's clean it with the antiseptic wipes from the highlighted space. Do you have access to clean water?

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

def make_beep(sr, hz, ms, ampl):
    """Generate a simple sine beep as raw PCM16 bytes."""
    n = int(sr * ms / 1000.0)
    data = bytearray()
    for i in range(n):
        v = int(ampl * math.sin(2 * math.pi * hz * (i / sr)))
        data += struct.pack("<h", v)
    return bytes(data)

def capture_audio_continuously():
    """
    Capture audio continuously until speech pause (no wake word required).
    Returns PCM16 mono bytes at OUT_SR sample rate.
    """
    if not os.path.exists(WAKEWORD_PATH):
        raise RuntimeError(f"WAKEWORD_PATH not found: {WAKEWORD_PATH}")

    if PICOVOICE_ACCESS_KEY.startswith("YOUR-") or not PICOVOICE_ACCESS_KEY:
        raise RuntimeError("No valid Picovoice AccessKey set. Export PICOVOICE_ACCESS_KEY or edit script.")

    arec = None
    aplay = None

    try:
        # Use the same sample rate as the wake word detection
        mic_sr = 16000  # Porcupine sample rate
        frame_len = 512  # Standard frame length
        frame_bytes = frame_len * 2  # 16-bit mono => 2 bytes/sample

        log(f"Continuous capture: Mic device: {MIC_DEVICE} @ {mic_sr} Hz")
        arec = spawn_arecord(mic_sr, MIC_DEVICE)

        # Prepare speaker for beep
        aplay = spawn_aplay(OUT_SR)
        beep = make_beep(OUT_SR, BEEP_HZ, BEEP_MS, BEEP_AMPL)

        log("Capturing audio continuously...")
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
                    # Play beep to indicate speech detection
                    try:
                        aplay.stdin.write(beep)
                        aplay.stdin.flush()
                    except BrokenPipeError:
                        pass
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
            if arec: arec.terminate()
        except: pass
        try:
            if aplay and aplay.stdin:
                aplay.stdin.close()
        except: pass
        try:
            if aplay: aplay.terminate()
        except: pass

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
    
    # Clean up LEDs
    if LED_ENABLED:
        clear_all_leds()
    
    sys.exit(0)

async def main():
    global aplay_process, ws_connection
    
    # Initialize LED strip
    if LED_ENABLED:
        init_led_strip()
    
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
        current_response_text = ""
        
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
                        # Start LED speaking pulse on first audio delta
                        try:
                            start_speak_pulse()
                        except Exception:
                            pass
                        try: aplay_process.stdin.write(pcm)
                        except BrokenPipeError: pass
                    except Exception as e:
                        log(f"[audio.decode.error] {e}")

            if t in ("response.text.delta", "response.output_text.delta", "response.audio_transcript.delta"):
                delta_text = evt.get("delta","")
                sys.stdout.write(delta_text); sys.stdout.flush()
                current_response_text += delta_text

            if t in ("response.done", "response.completed"):
                try: aplay_process.stdin.write(bytes([0] * (OUT_SR * 2 // 10)))  # ~100 ms silence
                except Exception: pass
                print("\n[response done]")
                # Stop LED speaking pulse when response is done
                try:
                    stop_speak_pulse()
                except Exception:
                    pass
                
                # Parse the complete response for item mentions and light LEDs
                if current_response_text.strip():
                    log(f"Parsing response for LED control: {current_response_text[:100]}...")
                    parse_response_for_items(current_response_text)
                
                current_response_text = ""  # Reset for next response

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

    # ---- Send opening message immediately on startup ----
    log("Sending opening greeting message...")
    await ws.send(json.dumps({
        "type":"response.create",
        "response":{"modalities":["audio","text"], "instructions":"Give the opening greeting message in English."}
    }))
    log("Opening message sent, waiting for response...")

    # ---- Wait for wake word before starting conversation loop ----
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
        "response":{"modalities":["audio","text"], "instructions":"Answer briefly as Solstis medical assistant, in English."}
    }))
    log("Audio sent, waiting for response...")

    # ---- Main conversation loop ----
    # conversation_active = True
    # last_activity_time = time.time()
    
    while True:
        # if CONTINUOUS_MODE_ENABLED and conversation_active:
        #     # Continuous listening mode - no wake word required
        #     log("Continuous listening mode active...")
        #     pcm = await asyncio.to_thread(capture_audio_continuously)
        #     
        #     if pcm and len(pcm) >= int(OUT_SR * 2 * 0.1):  # ~100 ms min
        #         last_activity_time = time.time()
        #         log("Sending audio to API...")
        #         await ws.send(json.dumps({"type":"input_audio_buffer.clear"}))
        #         for i in range(0, len(pcm), 8192):
        #             b64 = base64.b64encode(pcm[i:i+8192]).decode("ascii")
        #             await ws.send(json.dumps({"type":"input_audio_buffer.append","audio": b64}))
        #         await ws.send(json.dumps({"type":"input_audio_buffer.commit"}))
        #
        #         await ws.send(json.dumps({
        #             "type":"response.create",
        #             "response":{"modalities":["audio","text"], "instructions":"Answer briefly as Solstis medical assistant, in English."}
        #         }))
        #         log("Audio sent, waiting for response...")
        #     else:
        #         # Check if we should return to wake word mode due to timeout
        #         if time.time() - last_activity_time > CONTINUOUS_MODE_TIMEOUT:
        #             log(f"Continuous mode timeout ({CONTINUOUS_MODE_TIMEOUT}s), returning to wake word mode...")
        #             conversation_active = False
        #         else:
        #             log("No audio captured, continuing to listen...")
        #             await asyncio.sleep(0.1)  # Brief pause before trying again
        # else:
        # Wake word mode - require wake word for each interaction
        log("Wake word mode - waiting for wake word...")
        pcm = await asyncio.to_thread(capture_audio_after_wakeword)
        if not pcm or len(pcm) < int(OUT_SR * 2 * 0.1):   # ~100 ms min
            log("Too little audio; skipping.")
            continue

        # Reset to continuous mode after wake word detection
        # conversation_active = True
        # last_activity_time = time.time()
        
        log("Sending audio to API...")
        await ws.send(json.dumps({"type":"input_audio_buffer.clear"}))
        for i in range(0, len(pcm), 8192):
            b64 = base64.b64encode(pcm[i:i+8192]).decode("ascii")
            await ws.send(json.dumps({"type":"input_audio_buffer.append","audio": b64}))
        await ws.send(json.dumps({"type":"input_audio_buffer.commit"}))

        await ws.send(json.dumps({
            "type":"response.create",
            "response":{"modalities":["audio","text"], "instructions":"Answer briefly as Solstis medical assistant, in English."}
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
    log(f"Continuous Mode: {'Enabled' if CONTINUOUS_MODE_ENABLED else 'Disabled'}, Timeout: {CONTINUOUS_MODE_TIMEOUT}s")
    log(f"LED Control: {'Enabled' if LED_ENABLED else 'Disabled'}, Count: {LED_COUNT}, Duration: {LED_DURATION}s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Shutdown complete.")

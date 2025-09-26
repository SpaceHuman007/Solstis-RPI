#!/usr/bin/env python3
# Solstis Voice Assistant with Improved Conversation Flow
# Implements dual wake word system and structured conversation states

import asyncio, base64, json, os, signal, subprocess, sys, threading, time, io, wave, types, audioop, struct, math
from datetime import datetime
from dotenv import load_dotenv
import openai
import tempfile
import requests
import pvporcupine  # pip install pvporcupine

# GPIO imports for reed switch
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available. Reed switch functionality disabled.")

# LED Control imports
try:
    from rpi_ws281x import *
    LED_CONTROL_AVAILABLE = True
except ImportError:
    LED_CONTROL_AVAILABLE = False
    print("Warning: rpi_ws281x not available. LED control disabled.")

load_dotenv(override=True)

# --------- Config via env (Picovoice + OpenAI) ---------
# Picovoice config
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "YOUR-PICOVOICE-ACCESSKEY-HERE")
SOLSTIS_WAKEWORD_PATH = os.getenv("SOLSTIS_WAKEWORD_PATH", "Solstice_en_raspberry-pi_v3_0_0.ppn")
STEP_COMPLETE_WAKEWORD_PATH = os.getenv("STEP_COMPLETE_WAKEWORD_PATH", "step-complete_en_raspberry-pi_v3_0_0.ppn")
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR = int(os.getenv("MIC_SR", "16000"))  # Porcupine requires 16k

# OpenAI config
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4-turbo")
TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("TTS_VOICE", "shimmer")

# Audio output config
OUT_DEVICE = os.getenv("AUDIO_DEVICE")  # e.g., "plughw:3,0" or None for default
# Ensure mic and output don't use the same device
if OUT_DEVICE == MIC_DEVICE:
    # Use print here because log() is defined later
    print(f"[WARN] MIC_DEVICE and OUT_DEVICE are both {MIC_DEVICE}")
    print("[WARN] Setting OUT_DEVICE to 'default' to avoid conflict")
    OUT_DEVICE = "default"
OUT_SR = int(os.getenv("OUT_SR", "24000"))  # Audio output sample rate
USER_NAME = os.getenv("USER_NAME", "User")

# Speech detection config
SPEECH_THRESHOLD = int(os.getenv("SPEECH_THRESHOLD", "500"))  # RMS threshold for speech detection
SILENCE_DURATION = float(os.getenv("SILENCE_DURATION", "2.0"))  # seconds of silence before stopping
# When speech has been detected at least once, use a quicker silence cutoff
QUICK_SILENCE_AFTER_SPEECH = float(os.getenv("QUICK_SILENCE_AFTER_SPEECH", "0.6"))
MIN_SPEECH_DURATION = float(os.getenv("MIN_SPEECH_DURATION", "0.5"))  # minimum speech duration
MAX_SPEECH_DURATION = float(os.getenv("MAX_SPEECH_DURATION", "15.0"))  # maximum speech duration

# Timeout configurations
T_SHORT = float(os.getenv("T_SHORT", "30.0"))  # Short timeout for initial responses (extended)
T_NORMAL = float(os.getenv("T_NORMAL", "10.0"))  # Normal timeout for conversation
T_LONG = float(os.getenv("T_LONG", "15.0"))  # Long timeout for step completion

# LED Control config
LED_ENABLED = os.getenv("LED_ENABLED", "true").lower() == "true" and LED_CONTROL_AVAILABLE
LED_COUNT = int(os.getenv("LED_COUNT", "788"))  # Number of LED pixels
LED_PIN = int(os.getenv("LED_PIN", "13"))  # GPIO pin connected to the pixels
LED_FREQ_HZ = int(os.getenv("LED_FREQ_HZ", "800000"))  # LED signal frequency
LED_DMA = int(os.getenv("LED_DMA", "10"))  # DMA channel
LED_BRIGHTNESS = int(os.getenv("LED_BRIGHTNESS", "70"))  # LED brightness (0-255)
LED_INVERT = os.getenv("LED_INVERT", "false").lower() == "true"
LED_CHANNEL = int(os.getenv("LED_CHANNEL", "1"))  # LED channel
LED_DURATION = float(os.getenv("LED_DURATION", "10.0"))  # How long to keep LEDs on

# LED pulsing (speaking indicator) config - Solstis middle section
SPEAK_LEDS_START1 = int(os.getenv("SPEAK_LEDS_START1", "643"))
SPEAK_LEDS_END1   = int(os.getenv("SPEAK_LEDS_END1", "663"))
SPEAK_LEDS_START2 = int(os.getenv("SPEAK_LEDS_START2", "696"))
SPEAK_LEDS_END2   = int(os.getenv("SPEAK_LEDS_END2", "727"))
SPEAK_COLOR_R     = int(os.getenv("SPEAK_COLOR_R", "0"))
SPEAK_COLOR_G     = int(os.getenv("SPEAK_COLOR_G", "180"))
SPEAK_COLOR_B     = int(os.getenv("SPEAK_COLOR_B", "255"))

# Reed switch config
REED_SWITCH_ENABLED = os.getenv("REED_SWITCH_ENABLED", "true").lower() == "true" and GPIO_AVAILABLE
REED_SWITCH_PIN = int(os.getenv("REED_SWITCH_PIN", "16"))  # GPIO pin connected to reed switch
REED_SWITCH_DEBOUNCE_MS = int(os.getenv("REED_SWITCH_DEBOUNCE_MS", "500"))  # Debounce time in milliseconds (reduced sensitivity)
REED_SWITCH_CONFIRM_COUNT = int(os.getenv("REED_SWITCH_CONFIRM_COUNT", "5"))  # Number of consistent readings required
REED_SWITCH_POLL_INTERVAL = float(os.getenv("REED_SWITCH_POLL_INTERVAL", "0.2"))  # Polling interval in seconds

# Wake word constants
WAKE_WORD_SOLSTIS = "SOLSTIS"
WAKE_WORD_STEP_COMPLETE = "STEP COMPLETE"

# Conversation states
class ConversationState:
    OPENING = "opening"
    ACTIVE_ASSISTANCE = "active_assistance"
    WAITING_FOR_STEP_COMPLETE = "waiting_for_step_complete"
    WAITING_FOR_WAKE_WORD = "waiting_for_wake_word"

# Response outcomes
class ResponseOutcome:
    NEED_MORE_INFO = "need_more_info"
    USER_ACTION_REQUIRED = "user_action_required"
    PROCEDURE_DONE = "procedure_done"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# Global variables
led_strip = None
speak_pulse_thread = None
speak_pulse_stop = threading.Event()
conversation_history = []
current_state = ConversationState.WAITING_FOR_WAKE_WORD

# Reed switch state variables
box_is_open = False
reed_switch_initialized = False

# ---------- Enhanced Keyword Detection System ----------
# Comprehensive keyword mapping for medical kit items
KEYWORD_MAPPINGS = {
    "Band-Aids": {
        "keywords": [
            "band-aid", "band aid", "bandaid", "bandaids", "adhesive bandage", 
            "sticky bandage", "wound cover", "cut cover", "small bandage"
        ],
        "description": "Band-Aids for small cuts and wounds"
    },
    "4\" x 4\" Gauze Pads": {
        "keywords": [
            "gauze pad", "gauze pads", "4 gauze pads", "4x4 gauze", 
            "square gauze", "sterile gauze", "dressing pad", "wound pad",
            "gauze square", "medical gauze", "absorbent pad"
        ],
        "description": "4\" x 4\" Gauze Pads for wound dressing"
    },
    "2\" Roll Gauze": {
        "keywords": [
            "roll gauze", "2 roll gauze", "gauze roll", "rolled gauze", 
            "gauze wrap", "bandage roll", "wrapping gauze", "medical wrap"
        ],
        "description": "2\" Roll Gauze for wrapping and securing dressings"
    },
    "5\" x 9\" ABD Pad": {
        "keywords": [
            "abd pad", "abd", "abdominal pad", "large pad", "big pad", 
            "5x9 pad", "major wound pad", "heavy bleeding pad"
        ],
        "description": "5\" x 9\" ABD Pad for large wounds and heavy bleeding"
    },
    "Cloth Medical Tape": {
        "keywords": [
            "tape", "medical tape", "cloth tape", "adhesive tape", 
            "surgical tape", "wound tape", "bandage tape", "securing tape"
        ],
        "description": "Cloth Medical Tape for securing dressings"
    },
    "Triple Antibiotic Ointment": {
        "keywords": [
            "antibiotic", "ointment", "triple antibiotic", "antibiotic ointment", 
            "neosporin", "bacitracin", "polysporin", "antiseptic ointment",
            "wound ointment", "healing ointment", "infection prevention"
        ],
        "description": "Triple Antibiotic Ointment for preventing infection"
    },
    "Tweezers": {
        "keywords": [
            "tweezers", "blunt tweezers", "forceps", "splinter removal", 
            "debris removal", "foreign object", "tick removal", "splinter tool"
        ],
        "description": "Tweezers for removing splinters and debris"
    },
    "Trauma Shears": {
        "keywords": [
            "scissors", "shears", "trauma shears", "medical scissors", 
            "cutting tool", "bandage scissors", "emergency scissors", "safety scissors"
        ],
        "description": "Trauma Shears for cutting bandages and clothing"
    },
    "QuickClot Gauze": {
        "keywords": [
            "quickclot", "hemostatic", "hemostatic gauze", "bleeding control", 
            "blood stopper", "clotting agent", "emergency bleeding", "severe bleeding"
        ],
        "description": "QuickClot Gauze for severe bleeding"
    },
    "Burn Gel Dressing": {
        "keywords": [
            "burn gel", "burn dressing", "4x4 burn gel", "burn treatment", 
            "thermal burn", "heat burn", "burn relief", "cooling gel"
        ],
        "description": "Burn Gel Dressing for thermal burns"
    },
    "Burn Spray": {
        "keywords": [
            "burn spray", "2 oz burn spray", "spray burn", "burn mist", 
            "cooling spray", "thermal spray", "burn relief spray"
        ],
        "description": "Burn Spray for immediate burn relief"
    },
    "Sting & Bite Relief Wipes": {
        "keywords": [
            "sting", "bite relief", "insect bite", "bee sting", "wasp sting", 
            "ant bite", "mosquito bite", "sting relief", "bite treatment",
            "itch relief", "sting wipes", "bite wipes"
        ],
        "description": "Sting & Bite Relief Wipes for insect bites and stings"
    },
    "Mini Eye Wash Bottle": {
        "keywords": [
            "eye wash", "eye wash bottle", "eyewash", "eye rinse", "eye irrigation", 
            "eye flush", "eye cleaning", "foreign object eye", "chemical eye",
            "eye emergency", "eye decontamination"
        ],
        "description": "Mini Eye Wash Bottle for eye irrigation and decontamination"
    },
    "Oral Glucose Gel": {
        "keywords": [
            "glucose", "glucose gel", "oral gel", "sugar gel", "diabetic emergency", 
            "low blood sugar", "hypoglycemia", "glucose tube", "oral glucose",
            "diabetic treatment", "blood sugar emergency"
        ],
        "description": "Oral Glucose Gel for diabetic emergencies and low blood sugar"
    },
    "Electrolyte Powder Pack": {
        "keywords": [
            "electrolyte", "electrolyte powder", "hydration powder", "rehydration", 
            "dehydration", "salt replacement", "mineral powder", "hydration mix",
            "electrolyte replacement", "fluid replacement"
        ],
        "description": "Electrolyte Powder Pack for dehydration and rehydration"
    },
    "Elastic Ace Bandage": {
        "keywords": [
            "ace bandage", "elastic bandage", "2 inch bandage", "compression bandage", 
            "wrap bandage", "support bandage", "elastic wrap", "compression wrap"
        ],
        "description": "Elastic Ace Bandage for compression and support"
    },
    "Instant Cold Pack": {
        "keywords": [
            "cold pack", "ice pack", "instant cold", "cooling pack", "thermal pack", 
            "cold therapy", "ice therapy", "swelling reduction", "pain relief cold"
        ],
        "description": "Instant Cold Pack for reducing swelling and pain relief"
    },
    "Triangle Bandage": {
        "keywords": [
            "triangle bandage", "triangular bandage", "sling", "arm sling", 
            "shoulder support", "immobilization", "fracture support", "arm support"
        ],
        "description": "Triangle Bandage for creating slings and immobilization"
    }
}

def detect_mentioned_items(response_text):
    """
    Enhanced keyword detection that maps keywords to specific items and logs matches.
    Returns a list of detected items with their matched keywords.
    """
    response_lower = response_text.lower()
    detected_items = []
    
    log("🔍 Analyzing response for medical kit items...")
    
    for item_name, item_data in KEYWORD_MAPPINGS.items():
        matched_keywords = []
        
        for keyword in item_data["keywords"]:
            if keyword in response_lower:
                matched_keywords.append(keyword)
        
        if matched_keywords:
            detected_items.append({
                "item": item_name,
                "matched_keywords": matched_keywords,
                "description": item_data["description"]
            })
            
            log(f"✅ DETECTED: {item_name}")
            log(f"   📝 Description: {item_data['description']}")
            log(f"   🔑 Matched keywords: {', '.join(matched_keywords)}")
    
    if not detected_items:
        log("ℹ️  No medical kit items detected in response")
    else:
        log(f"📊 Total items detected: {len(detected_items)}")
    
    return detected_items

# ---------- LED Control System ----------
# LED mapping for kit items with multiple ranges per item
LED_MAPPINGS = {
    "solstis middle": [(643, 663), (696, 727)],
    "QuickClot Gauze": [(62, 86), (270, 293), (264, 264)],
    "Burn Spray": [(41, 62), (234, 269), (226, 226)],
    "Burn Gel Dressing": [(241, 262), (220, 226), (601, 629)],
    "4\" x 4\" Gauze Pads": [(581, 623), (636, 642), (720, 727)],
    "Instant Cold Pack": [(706, 719), (199, 212), (581, 594), (553, 567)],
    "Electrolyte Powder Pack": [(691, 705), (523, 567)],
    "Triple Antibiotic Ointment": [(493, 548), (186, 193)],
    "Tweezers": [(464, 517), (455, 456), (420, 422)],
    "Trauma Shears": [(461, 488), (153, 182)],
    "Mini Eye Wash Bottle": [(130, 153), (439, 460)],
    "Band-Aids": [(402, 438), (126, 130)],
    "Triangle Bandage": [(390, 418), (679, 690), (519, 523)],
    "Cloth Medical Tape": [(382, 396), (335, 341), (111, 120)],
    "Elastic Ace Bandage": [(318, 352)],
    "Sting & Bite Relief Wipes": [(661, 678), (386, 389), (370, 377)],
    "2\" Roll Gauze": [(370, 381), (648, 661), (341, 356)],
    "5\" x 9\" ABD Pad": [(294, 326), (86, 102)],
    "Oral Glucose Gel": [(303, 317), (275, 285), (630, 647), (263, 264), (352, 356)],
}

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
    # Define two ranges to pulse - Solstis middle section
    ranges = [
        (SPEAK_LEDS_START1, SPEAK_LEDS_END1),
        (SPEAK_LEDS_START2, SPEAK_LEDS_END2)
    ]
    r, g, b = SPEAK_COLOR_R, SPEAK_COLOR_G, SPEAK_COLOR_B
    t = 0.0
    try:
        while not speak_pulse_stop.is_set() and LED_ENABLED and led_strip:
            brightness = 0.2 + 0.6 * (0.5 * (1 + math.sin(t)))
            # Pulse both ranges
            for start_idx, end_idx in ranges:
                _pulse_range_once(start_idx, end_idx, r, g, b, brightness)
            t += 0.25
            speak_pulse_stop.wait(0.08)
        
        # Clear the speaking LEDs when pulsing stops
        if LED_ENABLED and led_strip:
            for start_idx, end_idx in ranges:
                for i in range(start_idx, end_idx + 1):
                    if i < led_strip.numPixels():
                        led_strip.setPixelColor(i, 0)
            led_strip.show()
            
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
    """Light up LEDs for a specific item (supports multiple ranges)"""
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
    
    ranges = LED_MAPPINGS[item_key]
    log(f"Lighting LEDs for item: {item_name}")
    
    try:
        # Clear all LEDs first
        clear_all_leds()
        
        # Light up all ranges for this item
        for range_idx, (start, end) in enumerate(ranges):
            log(f"  Range {range_idx + 1}: LEDs {start}-{end}")
            for i in range(start, end + 1):
                if i < led_strip.numPixels():
                    led_strip.setPixelColor(i, Color(*color))
        
        led_strip.show()
        
    except Exception as e:
        log(f"Error lighting LEDs for {item_name}: {e}")

def parse_response_for_items(response_text):
    """Parse AI response text to identify mentioned items and light appropriate LEDs"""
    if not LED_ENABLED:
        return
    
    # Use enhanced keyword detection
    detected_items = detect_mentioned_items(response_text)
    
    # Light LEDs for the first detected item
    if detected_items:
        first_item = detected_items[0]["item"]
        log(f"Lighting LEDs for detected item: {first_item}")
        light_item_leds(first_item)

# ---------- Reed Switch Control System ----------
def init_reed_switch():
    """Initialize the reed switch GPIO"""
    global reed_switch_initialized
    if not REED_SWITCH_ENABLED:
        log("Reed switch control disabled")
        return False
    
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(REED_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        reed_switch_initialized = True
        log(f"Reed switch initialized on GPIO pin {REED_SWITCH_PIN}")
        return True
    except Exception as e:
        log(f"Failed to initialize reed switch: {e}")
        return False

def cleanup_reed_switch():
    """Clean up reed switch GPIO"""
    global reed_switch_initialized
    if reed_switch_initialized:
        try:
            GPIO.cleanup(REED_SWITCH_PIN)
            reed_switch_initialized = False
            log("Reed switch GPIO cleaned up")
        except Exception as e:
            log(f"Error cleaning up reed switch: {e}")

def read_reed_switch():
    """Read the current state of the reed switch with enhanced debouncing and confirmation"""
    if not REED_SWITCH_ENABLED or not reed_switch_initialized:
        return False
    
    try:
        # Read multiple times to confirm the state (reduces false triggers)
        readings = []
        for i in range(REED_SWITCH_CONFIRM_COUNT):
            state = GPIO.input(REED_SWITCH_PIN)
            readings.append(state)
            if i < REED_SWITCH_CONFIRM_COUNT - 1:  # Don't sleep after the last reading
                time.sleep(REED_SWITCH_DEBOUNCE_MS / 1000.0)
        
        # Check if all readings are consistent
        if all(r == readings[0] for r in readings):
            # All readings are the same, return the confirmed state
            # Return True if box is open (HIGH), False if closed (LOW)
            return readings[0] == GPIO.HIGH
        else:
            # Readings are inconsistent, keep previous state by returning False (no change)
            log(f"⚠️  Inconsistent reed switch readings: {readings}")
            return False
        
    except Exception as e:
        log(f"Error reading reed switch: {e}")
        return False

def check_box_state_change():
    """Check if the box state has changed and return the new state"""
    global box_is_open
    
    if not REED_SWITCH_ENABLED:
        return False, box_is_open
    
    current_state = read_reed_switch()
    
    if current_state != box_is_open:
        old_state = box_is_open
        box_is_open = current_state
        
        if box_is_open:
            log("📦 Box opened - ready for new conversation")
        else:
            log("📦 Box closed - conversation reset")
        
        return True, box_is_open
    
    return False, box_is_open

# ---------- Core Conversation Flow Functions ----------
def opening_message():
    """Send the opening message"""
    message = f"Hey {USER_NAME}. I'm SOLSTIS and I'm here to help. If this is a life-threatening emergency, please call 9-1-1 now. Otherwise, is there something I can help you with?"
    return message

def closing_message():
    """Send the closing message"""
    message = f"If you need any further help, please let me know by saying '{WAKE_WORD_SOLSTIS}'."
    return message

def prompt_wake():
    """Prompt user to use wake word"""
    message = f"OK, if you need me for any help, say {WAKE_WORD_SOLSTIS} to wake me up."
    return message

def prompt_no_response():
    """Prompt when no response is detected"""
    message = f"I am hearing no response, be sure to say '{WAKE_WORD_SOLSTIS}' if you need my assistance!"
    return message

def prompt_step_complete():
    """Prompt user to say step complete"""
    message = f"Say '{WAKE_WORD_STEP_COMPLETE}' when you're done."
    return message

def prompt_continue_help():
    """Prompt for continued assistance"""
    message = f"Hey {USER_NAME}, how can I help you?"
    return message

def process_response(user_text, conversation_history=None):
    """
    Process user response and determine the outcome.
    Returns one of: NEED_MORE_INFO, USER_ACTION_REQUIRED, PROCEDURE_DONE
    """
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
        messages.append({"role": "user", "content": user_text})
        
        # Generate response
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Update conversation history
        conversation_history.append({"role": "user", "content": user_text})
        conversation_history.append({"role": "assistant", "content": response_text})
        
        # Keep conversation history manageable (last 10 exchanges)
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]
        
        # Determine outcome based on response content
        response_lower = response_text.lower()
        
        # Check for procedure completion indicators
        if any(phrase in response_lower for phrase in [
            "procedure is complete", "treatment is done", "you're all set", 
            "that should help", "you should be fine", "call 9-1-1", "emergency room"
        ]):
            return ResponseOutcome.PROCEDURE_DONE, response_text
        
        # Check for user action required indicators
        if any(phrase in response_lower for phrase in [
            "let me know when", "when you're done", "when you're ready", 
            "say step complete", "tell me when", "let me know"
        ]):
            return ResponseOutcome.USER_ACTION_REQUIRED, response_text
        
        # Default to needing more info
        return ResponseOutcome.NEED_MORE_INFO, response_text
    
    except Exception as e:
        log(f"Error processing response: {e}")
        return ResponseOutcome.NEED_MORE_INFO, "I'm sorry, I'm having trouble processing your request right now."

def get_system_prompt():
    """Generate the system prompt for the standard Solstis kit"""
    
    # Standard kit contents
    kit_contents = [
        "Band-Aids",
        "4\" x 4\" Gauze Pads",
        "2\" Roll Gauze",
        "5\" x 9\" ABD Pad",
        "Cloth Medical Tape",
        "Triple Antibiotic Ointment",
        "Tweezers",
        "Trauma Shears",
        "QuickClot Gauze",
        "Burn Gel Dressing",
        "Burn Spray",
        "Sting & Bite Relief Wipes",
        "Mini Eye Wash Bottle",
        "Oral Glucose Gel",
        "Electrolyte Powder Pack",
        "Elastic Ace Bandage",
        "Instant Cold Pack",
        "Triangle Bandage"
    ]
    
    contents_str = ", ".join(kit_contents)
    
    return f"""Always speak in English (US). You are Solstis, a calm and supportive AI medical assistant. You help users with first aid using only the items available in their specific kit.

AVAILABLE ITEMS IN YOUR KIT:
{contents_str}

IMPORTANT: When referencing kit items, use the EXACT names from the list above. For example:
- Say "Band-Aids" not "bandages" or "adhesive bandages"
- Say "4\" x 4\" Gauze Pads" not "gauze" or "gauze squares"
- Say "2\" Roll Gauze" not "roll gauze" or "gauze roll"
- Say "5\" x 9\" ABD Pad" not "ABD pad" or "large pad"
- Say "Cloth Medical Tape" not "medical tape" or "tape"
- Say "Triple Antibiotic Ointment" not "antibiotic ointment" or "ointment"
- Say "Tweezers" not "forceps" or "tweezers"
- Say "Trauma Shears" not "scissors" or "shears"
- Say "QuickClot Gauze" not "hemostatic gauze" or "clotting gauze"
- Say "Burn Gel Dressing" not "burn dressing" or "burn gel"
- Say "Burn Spray" not "burn spray" or "cooling spray"
- Say "Sting & Bite Relief Wipes" not "bite relief" or "sting wipes"
- Say "Mini Eye Wash Bottle" not "eye wash" or "eyewash"
- Say "Oral Glucose Gel" not "glucose gel" or "sugar gel"
- Say "Electrolyte Powder Pack" not "electrolyte powder" or "hydration powder"
- Say "Elastic Ace Bandage" not "ace bandage" or "elastic bandage"
- Say "Instant Cold Pack" not "cold pack" or "ice pack"
- Say "Triangle Bandage" not "triangular bandage" or "sling"

Your role:
• Be a real-time guide—natural, concise, supportive  
• Assess for life-threatening danger but don't overreact to common symptoms
• Give clear, step-by-step instructions for self-treatment first
• Select only from the current kit (or common home items)  
• Always use the EXACT item names from the kit contents list above
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

CRITICAL SINGLE-STEP RULE:
- Give ONLY ONE medical item instruction per response
- NEVER mention multiple medical items in the same response (e.g., don't say "apply ointment and use a bandage")
- If multiple steps are needed, give them one at a time and wait for user confirmation
- Examples of WRONG responses: "Apply antibiotic ointment and then put on a bandage", "Use gauze and tape to secure it"
- Examples of CORRECT responses: "Apply a thin layer of antibiotic ointment from the highlighted space. Let me know when you're done.", then after confirmation: "Now place a bandage from the highlighted space so the pad covers the cut. Let me know when you're done."

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
- For small cuts: Give ONE instruction at a time. First: "Apply a thin layer of Triple Antibiotic Ointment from the highlighted space. Let me know when you're done." Then: "Center the Band-Aid pad over the cut and smooth the adhesive around the skin. Let me know when you're done."
- For finger joints: "Place the Band-Aid pad over the cut and angle the adhesive so it doesn't bunch at the knuckle. Let me know when you're done." If reinforcement needed: "Now reinforce with Cloth Medical Tape from the highlighted space. Let me know when you're done."

BLEEDING CONTROL ESCALATION:
- First attempt: Direct pressure with 4" x 4" Gauze Pads for 5 minutes
- If bleeding continues: Apply QuickClot Gauze with firm pressure
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
- Minor burns: Cool with water, use Burn Gel Dressing or Burn Spray for pain relief, keep clean
- Major burns: Call 9-1-1 only if truly severe (large area, deep tissue, face/hands/genitals)
- Most burns can be treated with first aid first

COMMON SYMPTOMS - TREAT WITH FIRST AID FIRST:
- Fainting/Dizziness: Lie down, elevate legs, improve blood flow to brain
- Mild Shock: Keep warm, lie down, elevate legs if no spine injury
- Nausea: Rest, small sips of water, avoid sudden movements
- Mild Pain: Use pain relievers from kit, apply Instant Cold Pack as appropriate
- Cramps/Muscle Pain: Assess hydration, suggest Electrolyte Powder Pack, stretching, massage
- Sexual Pain/Discomfort: Discuss openly and suggest appropriate relief methods
- Only escalate to emergency care if symptoms worsen or persist despite first aid

BLEEDING ASSESSMENT PROTOCOL:
- ALWAYS ask about amount of blood and size of injury first
- If heavy bleeding: Control bleeding BEFORE treating other symptoms
- If light bleeding: Treat other symptoms first, then address bleeding
- Severity determines treatment order and emergency escalation
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
    else:
        # Force explicit default to avoid device confusion
        args += ["-D", "default"]
    
    log(f"🔊 Spawn Command: {' '.join(args)}")
    
    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        log(f"🔊 Spawn Success: aplay process created with PID {process.pid}")
        return process
    except Exception as e:
        log(f"🔊 Spawn Error: Failed to create aplay process: {e}")
        raise

def wait_for_wake_word(wake_word_type="SOLSTIS"):
    """
    Wait for specific wake word detection.
    Returns the detected wake word type or None if timeout/error.
    """
    if not os.path.exists(SOLSTIS_WAKEWORD_PATH) or not os.path.exists(STEP_COMPLETE_WAKEWORD_PATH):
        raise RuntimeError(f"Wake word files not found: {SOLSTIS_WAKEWORD_PATH}, {STEP_COMPLETE_WAKEWORD_PATH}")

    if PICOVOICE_ACCESS_KEY.startswith("YOUR-") or not PICOVOICE_ACCESS_KEY:
        raise RuntimeError("No valid Picovoice AccessKey set. Export PICOVOICE_ACCESS_KEY or edit script.")

    porcupine = None
    arec = None

    try:
        # Load both wake word models
        log(f"Loading Porcupine with keywords: {SOLSTIS_WAKEWORD_PATH}, {STEP_COMPLETE_WAKEWORD_PATH}")
        porcupine = pvporcupine.create(
            access_key=PICOVOICE_ACCESS_KEY,
            keyword_paths=[SOLSTIS_WAKEWORD_PATH, STEP_COMPLETE_WAKEWORD_PATH]
        )

        mic_sr = porcupine.sample_rate  # 16000
        frame_len = porcupine.frame_length
        frame_bytes = frame_len * 2  # 16-bit mono => 2 bytes/sample

        log(f"Mic device: {MIC_DEVICE} @ {mic_sr} Hz | frame {frame_len} samples ({frame_bytes} bytes)")
        arec = spawn_arecord(mic_sr, MIC_DEVICE)

        log("Listening for wake word...")
        leftover = b""

        # Wait for wake word with retry logic
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                chunk = arec.stdout.read(frame_bytes)
                if not chunk:
                    retry_count += 1
                    if retry_count < max_retries:
                        log(f"⚠️  Mic stream ended, retrying ({retry_count}/{max_retries})...")
                        # Clean up and restart
                        try:
                            arec.terminate()
                        except:
                            pass
                        time.sleep(0.5)
                        arec = spawn_arecord(mic_sr, MIC_DEVICE)
                        continue
                    else:
                        raise RuntimeError("Mic stream ended (EOF). Is the device busy or disconnected?")

                buf = leftover + chunk
                offset = 0
                while len(buf) - offset >= frame_bytes:
                    frame = buf[offset:offset + frame_bytes]
                    offset += frame_bytes
                    pcm = struct.unpack_from("<" + "h" * frame_len, frame)
                    r = porcupine.process(pcm)
                    if r >= 0:
                        if r == 0:
                            log("SOLSTIS wake word detected! 🔊")
                            return "SOLSTIS"
                        elif r == 1:
                            log("STEP COMPLETE wake word detected! 🔊")
                            return "STEP_COMPLETE"
                leftover = buf[offset:]
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    log(f"⚠️  Wake word detection error, retrying ({retry_count}/{max_retries}): {e}")
                    time.sleep(0.5)
                    continue
                else:
                    raise

    except Exception as e:
        log(f"Error in wake word detection: {e}")
        return None
    finally:
        try:
            if porcupine: porcupine.delete()
        except: pass
        try:
            if arec: arec.terminate()
        except: pass

def listen_for_speech(timeout=T_NORMAL):
    """
    Listen for speech after wake word detection.
    Returns transcribed text or None if no speech/timeout.
    """
    if not os.path.exists(SOLSTIS_WAKEWORD_PATH):
        raise RuntimeError(f"WAKEWORD_PATH not found: {SOLSTIS_WAKEWORD_PATH}")

    if PICOVOICE_ACCESS_KEY.startswith("YOUR-") or not PICOVOICE_ACCESS_KEY:
        raise RuntimeError("No valid Picovoice AccessKey set. Export PICOVOICE_ACCESS_KEY or edit script.")

    porcupine = None
    arec = None

    try:
        log(f"Loading Porcupine for speech detection")
        porcupine = pvporcupine.create(
            access_key=PICOVOICE_ACCESS_KEY,
            keyword_paths=[SOLSTIS_WAKEWORD_PATH]  # Use SOLSTIS for speech detection
        )

        mic_sr = porcupine.sample_rate  # 16000
        frame_len = porcupine.frame_length
        frame_bytes = frame_len * 2  # 16-bit mono => 2 bytes/sample

        log(f"Mic device: {MIC_DEVICE} @ {mic_sr} Hz | frame {frame_len} samples ({frame_bytes} bytes)")
        arec = spawn_arecord(mic_sr, MIC_DEVICE)

        # Capture audio until speech pause
        log("Capturing audio until speech pause...")
        audio_buffer = b""
        silence_start_time = None
        speech_start_time = None
        speech_detected = False
        
        # Calculate frame duration for timing
        frame_duration = frame_len / mic_sr  # seconds per frame
        
        start_time = time.time()
        
        while True:
            # Check timeout
            if time.time() - start_time > timeout:
                log(f"Speech detection timeout after {timeout}s")
                break
                
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
                    else:
                        # After any detected speech, use a quicker silence cutoff to end short replies
                        cutoff = QUICK_SILENCE_AFTER_SPEECH
                        if current_time - silence_start_time >= cutoff:
                            log(f"Silence detected after speech for {cutoff}s, stopping capture")
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
            return None

        # Resample from mic sample rate to output sample rate
        if mic_sr != OUT_SR:
            audio_buffer, _ = audioop.ratecv(audio_buffer, 2, 1, mic_sr, OUT_SR, None)

        log(f"Captured {len(audio_buffer)} bytes PCM16 @ {OUT_SR} Hz.")
        return audio_buffer

    except Exception as e:
        log(f"Error in speech detection: {e}")
        return None
    finally:
        try:
            if porcupine: porcupine.delete()
        except: pass
        try:
            if arec: arec.terminate()
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

def text_to_speech(text):
    """Convert text to speech using OpenAI TTS"""
    try:
        log(f"🎤 TTS Request: '{text[:50]}{'...' if len(text) > 50 else ''}'")
        log(f"🎤 TTS Config: model={TTS_MODEL}, voice={TTS_VOICE}, format=pcm")
        
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
        
        audio_size = len(response.content)
        log(f"🎤 TTS Success: Generated {audio_size} bytes of audio data")
        
        return response.content
    
    except Exception as e:
        log(f"🎤 TTS Error: {e}")
        return b""

def play_audio(audio_data):
    """Play audio data using aplay with retry logic and device cleanup"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            log(f"🔊 Audio Playback: Starting playback of {len(audio_data)} bytes (attempt {attempt + 1}/{max_retries})")
            log(f"🔊 Audio Config: sample_rate={OUT_SR}, device={OUT_DEVICE or 'default'}")
            
            # Clean up any existing aplay processes before starting
            if attempt > 0:
                log(f"🔊 Audio Cleanup: Cleaning up before retry attempt {attempt + 1}")
                subprocess.run(["pkill", "-9", "-f", "aplay"], check=False, capture_output=True)
                time.sleep(0.5)
            
            aplay = spawn_aplay(OUT_SR)
            log(f"🔊 Audio Process: Spawned aplay process (PID: {aplay.pid})")
            
            log(f"🔊 Audio Write: Writing {len(audio_data)} bytes to aplay stdin")
            aplay.stdin.write(audio_data)
            aplay.stdin.close()
            log(f"🔊 Audio Write: Closed stdin, waiting for playback to complete")
            
            # Wait for playback to complete with timeout
            try:
                return_code = aplay.wait(timeout=10)  # 10 second timeout
                log(f"🔊 Audio Complete: aplay finished with return code {return_code}")
                
                if return_code != 0:
                    log(f"🔊 Audio Warning: aplay returned non-zero exit code {return_code}")
                    if attempt < max_retries - 1:
                        log(f"🔊 Audio Retry: Attempting retry {attempt + 2}/{max_retries}")
                        time.sleep(1.0)
                        continue
                else:
                    # Success, break out of retry loop
                    break
                    
            except subprocess.TimeoutExpired:
                log(f"🔊 Audio Timeout: aplay process timed out, killing it")
                aplay.kill()
                if attempt < max_retries - 1:
                    log(f"🔊 Audio Retry: Attempting retry {attempt + 2}/{max_retries}")
                    time.sleep(1.0)
                    continue
                
        except Exception as e:
            log(f"🔊 Audio Error: {e}")
            log(f"🔊 Audio Error Type: {type(e).__name__}")
            if attempt < max_retries - 1:
                log(f"🔊 Audio Retry: Attempting retry {attempt + 2}/{max_retries}")
                time.sleep(1.0)
                continue
            else:
                log(f"🔊 Audio Failed: All retry attempts exhausted")
    
    # Final cleanup after all attempts
    try:
        subprocess.run(["pkill", "-9", "-f", "aplay"], check=False, capture_output=True)
    except Exception:
        pass

def say(text):
    """Convert text to speech and play it"""
    log(f"🗣️  Speaking: {text}")
    audio_data = text_to_speech(text)
    if audio_data:
        start_speak_pulse()
        play_audio(audio_data)
        stop_speak_pulse()
    print(f"Solstis: {text}")

# ---------- Main Conversation Flow ----------
def handle_conversation():
    """Main conversation handler implementing the improved flow with reed switch integration"""
    global current_state, conversation_history
    
    log("🎯 Starting improved conversation flow with reed switch")
    
    # Flag to track if we should skip opening message
    skip_opening_message = False
    
    # Main interaction loop
    while True:
        # Check for reed switch state changes
        state_changed, is_open = check_box_state_change()
        
        if state_changed and not is_open:
            # Box just closed - reset conversation state
            log("📦 Box closed - resetting conversation state")
            conversation_history = []
            skip_opening_message = False
            current_state = ConversationState.WAITING_FOR_WAKE_WORD
            
            # Clear LEDs
            if LED_ENABLED:
                clear_all_leds()
            
            log("Waiting for box to open...")
            continue
        
        if not is_open:
            # Box is closed - wait for it to open
            time.sleep(REED_SWITCH_POLL_INTERVAL)
            continue
        
        # Box is open - proceed with conversation
        
        # Opening message (only if not skipping)
        if not skip_opening_message:
            log("📢 Sending opening message")
            say(opening_message())
            current_state = ConversationState.OPENING
        else:
            log("⏭️  Skipping opening message")
            skip_opening_message = False  # Reset flag
        
        # Listen for initial response
        log("👂 Listening for initial response")
        audio_data = listen_for_speech(timeout=T_SHORT)
        
        if audio_data is None:
            # First retry of opening
            log("🔄 No response, retrying opening message")
            say(opening_message())
            audio_data = listen_for_speech(timeout=T_SHORT)
            
            if audio_data is None:
                # Still no response, prompt and wait for wake word
                log("🔇 Still no response, prompting and waiting for wake word")
                say(prompt_no_response())
                current_state = ConversationState.WAITING_FOR_WAKE_WORD
                
                wake_word = wait_for_wake_word()
                if wake_word == "SOLSTIS":
                    say(prompt_continue_help())
                    # Set flag to skip opening message on next iteration
                    skip_opening_message = True
                    continue
                else:
                    continue
        
        # Transcribe the response
        user_text = transcribe_audio(audio_data)
        if not user_text:
            log("❌ No transcription received")
            continue
        
        print(f"User: {user_text}")
        
        # Check for negative response
        if any(phrase in user_text.lower() for phrase in ["no", "nothing", "i'm fine", "no thanks"]):
            log("👋 User declined help")
            say(prompt_wake())
            current_state = ConversationState.WAITING_FOR_WAKE_WORD
            
            wake_word = wait_for_wake_word()
            if wake_word == "SOLSTIS":
                say(prompt_continue_help())
                # Set flag to skip opening message on next iteration
                skip_opening_message = True
                continue
            else:
                continue
        
        # Enter active assistance loop
        current_state = ConversationState.ACTIVE_ASSISTANCE
        log("🩺 Entering active assistance mode")
        
        while True:
            # Check if box is still open during conversation
            state_changed, is_open = check_box_state_change()
            if state_changed and not is_open:
                log("📦 Box closed during conversation - resetting state")
                conversation_history = []
                skip_opening_message = False
                current_state = ConversationState.WAITING_FOR_WAKE_WORD
                if LED_ENABLED:
                    clear_all_leds()
                break  # Exit active assistance loop
            
            # Process the user's response
            outcome, response_text = process_response(user_text, conversation_history)
            
            # Clear any existing LEDs before speaking
            if LED_ENABLED:
                clear_all_leds()
            
            # Speak the response first
            say(response_text)
            
            # Parse response for LED control AFTER speaking
            parse_response_for_items(response_text)
            
            if outcome == ResponseOutcome.NEED_MORE_INFO:
                # Model keeps listening automatically
                log("📝 Need more info, continuing to listen")
                audio_data = listen_for_speech(timeout=T_NORMAL)
                
                if audio_data is None:
                    log("🔇 No response to follow-up, prompting and waiting for wake word")
                    say(prompt_no_response())
                    current_state = ConversationState.WAITING_FOR_WAKE_WORD
                    
                    wake_word = wait_for_wake_word()
                    if wake_word == "SOLSTIS":
                        say(prompt_continue_help())
                        # Set flag to skip opening message on next iteration
                        skip_opening_message = True
                        break  # Exit active assistance loop
                    else:
                        break
                
                user_text = transcribe_audio(audio_data)
                if not user_text:
                    log("❌ No transcription received")
                    continue
                
                print(f"User: {user_text}")
                continue  # Re-process with new info
            
            elif outcome == ResponseOutcome.USER_ACTION_REQUIRED:
                # User needs to complete an action
                log("⏳ User action required, waiting for step completion")
                current_state = ConversationState.WAITING_FOR_STEP_COMPLETE
                say(prompt_step_complete())
                
                # Keep LEDs lit while waiting for step completion
                log("💡 Keeping LEDs lit while waiting for step completion")
                
                # Wait for acknowledgement OR wake word
                while True:
                    # Check box state during step completion wait
                    state_changed, is_open = check_box_state_change()
                    if state_changed and not is_open:
                        log("📦 Box closed during step completion - resetting state")
                        conversation_history = []
                        skip_opening_message = False
                        current_state = ConversationState.WAITING_FOR_WAKE_WORD
                        if LED_ENABLED:
                            clear_all_leds()
                        break  # Exit step completion loop
                    
                    wake_word = wait_for_wake_word()
                    
                    if wake_word == "STEP_COMPLETE":
                        log("✅ Step complete detected, continuing procedure")
                        # Clear LEDs when step is complete
                        if LED_ENABLED:
                            clear_all_leds()
                        # Continue procedure
                        user_text = "I've completed the step you asked me to do."
                        break  # Back to processing
                    
                    elif wake_word == "SOLSTIS":
                        log("🔊 SOLSTIS wake word detected during step completion")
                        say(prompt_continue_help())
                        audio_data = listen_for_speech(timeout=T_NORMAL)
                        
                        if audio_data is None:
                            log("🔇 No response after SOLSTIS wake word")
                            continue
                        
                        user_text = transcribe_audio(audio_data)
                        if not user_text:
                            log("❌ No transcription received")
                            continue
                        
                        print(f"User: {user_text}")
                        break  # Back to processing
                
                continue  # Re-process after step
            
            elif outcome == ResponseOutcome.PROCEDURE_DONE:
                # Procedure is complete
                log("✅ Procedure completed")
                say(closing_message())
                current_state = ConversationState.WAITING_FOR_WAKE_WORD
                
                # Wait for wake word to restart
                wake_word = wait_for_wake_word()
                if wake_word == "SOLSTIS":
                    say(prompt_continue_help())
                    # Set flag to skip opening message on next iteration
                    skip_opening_message = True
                    audio_data = listen_for_speech(timeout=T_NORMAL)
                    
                    if audio_data is None:
                        log("🔇 No response after procedure completion")
                        continue
                    
                    user_text = transcribe_audio(audio_data)
                    if not user_text:
                        log("❌ No transcription received")
                        continue
                    
                    print(f"User: {user_text}")
                    break  # Back to main loop for new request
                else:
                    continue

def cleanup_audio_processes(fast: bool = False):
    """Kill any existing audio processes that might be holding the devices.
    If fast=True, do it non-blocking and without sleeps (for signal handler).
    """
    try:
        if fast:
            # Fire-and-forget, no waiting
            try:
                subprocess.Popen(["pkill", "-9", "-f", "arecord"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            try:
                subprocess.Popen(["pkill", "-9", "-f", "aplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            try:
                subprocess.Popen(["fuser", "-k", MIC_DEVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            if OUT_DEVICE:
                try:
                    subprocess.Popen(["fuser", "-k", OUT_DEVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            return
        
        # Normal blocking cleanup
        subprocess.run(["pkill", "-9", "-f", "arecord"], check=False, capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "aplay"], check=False, capture_output=True)
        subprocess.run(["fuser", "-k", MIC_DEVICE], check=False, capture_output=True)
        if OUT_DEVICE:
            subprocess.run(["fuser", "-k", OUT_DEVICE], check=False, capture_output=True)
        time.sleep(1.0)
        log("🧹 Cleaned up existing audio processes")
    except Exception as e:
        log(f"Warning: Could not cleanup audio processes: {e}")

def reset_audio_devices():
    """Reset audio devices to clean state"""
    try:
        log("🔄 Resetting audio devices...")
        
        # Kill all audio processes
        subprocess.run(["pkill", "-9", "-f", "arecord"], check=False, capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "aplay"], check=False, capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "pulseaudio"], check=False, capture_output=True)
        
        # Reset ALSA
        subprocess.run(["alsactl", "restore"], check=False, capture_output=True)
        
        # Wait for devices to settle
        time.sleep(2.0)
        
        log("✅ Audio devices reset")
        return True
    except Exception as e:
        log(f"⚠️  Audio device reset failed: {e}")
        return False

def test_audio_devices():
    """Test if audio devices are available"""
    try:
        # Test microphone
        test_cmd = ["arecord", "-D", MIC_DEVICE, "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", "1", "/dev/null"]
        result = subprocess.run(test_cmd, capture_output=True, timeout=5)
        if result.returncode != 0:
            log(f"⚠️  Microphone test failed: {result.stderr.decode()}")
            return False
        
        # Test speaker
        test_cmd = ["aplay", "-D", OUT_DEVICE or "default", "-f", "S16_LE", "-r", "24000", "-c", "1", "/dev/null"]
        result = subprocess.run(test_cmd, capture_output=True, timeout=5)
        if result.returncode != 0:
            log(f"⚠️  Speaker test failed: {result.stderr.decode()}")
            return False
            
        log("✅ Audio devices tested successfully")
        return True
    except Exception as e:
        log(f"⚠️  Audio device test failed: {e}")
        return False

_handling_signal = False

def signal_handler(signum, frame):
    """Handle shutdown quickly and non-blocking to avoid deadlocks on Ctrl+C."""
    global _handling_signal
    if _handling_signal:
        return
    _handling_signal = True
    try:
        log("Shutdown signal received, cleaning up...")
    except Exception:
        pass
    try:
        if LED_ENABLED:
            clear_all_leds()
    except Exception:
        pass
    try:
        cleanup_reed_switch()
    except Exception:
        pass
    # Fast, non-blocking audio cleanup
    try:
        cleanup_audio_processes(fast=True)
    except Exception:
        pass
    # Exit immediately to avoid hanging in atexit/thread cleanup
    os._exit(0)

async def main():
    """Main entry point"""
    global current_state
    
    # # Reset audio devices to clean state (fixes noisy boot issues)
    # log("🔄 Resetting audio devices...")
    # reset_audio_devices()
    
    # # Test audio devices
    # log("🔊 Testing audio devices...")
    # if not test_audio_devices():
    #     log("❌ Audio device test failed. Please check your audio configuration.")
    #     return
    
    # Initialize LED strip
    if LED_ENABLED:
        init_led_strip()
    
    # Initialize reed switch
    if REED_SWITCH_ENABLED:
        init_reed_switch()
    
    # Initialize OpenAI client
    openai.api_key = API_KEY
    
    log(f"🩺 Solstis Improved Flow Voice Assistant starting...")
    log(f"User: {USER_NAME}")
    log(f"Model: {MODEL}")
    log(f"TTS Model: {TTS_MODEL}")
    log(f"TTS Voice: {TTS_VOICE}")
    log(f"SOLSTIS Wake Word: {SOLSTIS_WAKEWORD_PATH}")
    log(f"STEP COMPLETE Wake Word: {STEP_COMPLETE_WAKEWORD_PATH}")
    log(f"Speech Detection - Threshold: {SPEECH_THRESHOLD}, Silence Duration: {SILENCE_DURATION}s")
    log(f"Timeouts - Short: {T_SHORT}s, Normal: {T_NORMAL}s, Long: {T_LONG}s")
    log(f"LED Control: {'Enabled' if LED_ENABLED else 'Disabled'}, Count: {LED_COUNT}")
    log(f"Reed Switch: {'Enabled' if REED_SWITCH_ENABLED else 'Disabled'}, Pin: {REED_SWITCH_PIN}, Debounce: {REED_SWITCH_DEBOUNCE_MS}ms")
    
    try:
        # Start the conversation flow
        await asyncio.to_thread(handle_conversation)
    except Exception as e:
        log(f"Error in main: {e}")
    finally:
        # Cleanup
        if LED_ENABLED:
            clear_all_leds()
        cleanup_reed_switch()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Shutdown complete.")

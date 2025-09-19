#!/usr/bin/env python3
# Solstis Voice Assistant with Picovoice Wake Word Detection and GPT-4o Mini Integration
# Combines Picovoice wake word detection with OpenAI API for medical assistance

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
WAKEWORD_PATH = os.getenv("WAKEWORD_PATH", "Solstice_en_raspberry-pi_v3_0_0.ppn")
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR = int(os.getenv("MIC_SR", "16000"))  # Porcupine requires 16k

# OpenAI config
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-3.5-turbo")
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
REED_SWITCH_DEBOUNCE_MS = int(os.getenv("REED_SWITCH_DEBOUNCE_MS", "100"))  # Debounce time in milliseconds

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

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
            "gauze", "gauze pad", "gauze pads", "4 gauze pads", "4x4 gauze", 
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
            "5x9 pad", "large gauze", "major wound pad", "heavy bleeding pad"
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

def log_keyword_mappings():
    """Log all available keyword mappings for reference"""
    log("📋 COMPREHENSIVE KEYWORD MAPPINGS:")
    log("=" * 50)
    
    for item_name, item_data in KEYWORD_MAPPINGS.items():
        log(f"\n🏥 {item_name.upper()}")
        log(f"   📝 {item_data['description']}")
        log(f"   🔑 Keywords: {', '.join(item_data['keywords'])}")
    
    log("\n" + "=" * 50)

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
    # Define two ranges to pulse - Solstis middle section
    ranges = [
        (SPEAK_LEDS_START1, SPEAK_LEDS_END1),
        (SPEAK_LEDS_START2, SPEAK_LEDS_END2)
    ]
    r, g, b = SPEAK_COLOR_R, SPEAK_COLOR_G, SPEAK_COLOR_B
    t = 0.0
    try:
        while not speak_pulse_stop.is_set() and LED_ENABLED and led_strip:
            brightness = 0.2 + 0.6 * (0.5 * (1 + math.sin(t)))  # Reduced brightness range: 0.1 to 0.4
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
        
        # Don't automatically turn off - let the speaking pulse control handle it
        # The LEDs will stay lit until the response is complete
        
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
# Global variables for reed switch state
box_is_open = False
reed_switch_initialized = False

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
    """Read the current state of the reed switch with debouncing"""
    if not REED_SWITCH_ENABLED or not reed_switch_initialized:
        return False
    
    try:
        # Read the switch state (LOW = closed/magnet present, HIGH = open/magnet absent)
        # For normally open reed switch, LOW means box is closed, HIGH means box is open
        raw_state = GPIO.input(REED_SWITCH_PIN)
        
        # Add simple debouncing by reading multiple times
        time.sleep(REED_SWITCH_DEBOUNCE_MS / 1000.0)
        debounced_state = GPIO.input(REED_SWITCH_PIN)
        
        # Return True if box is open (HIGH), False if closed (LOW)
        return debounced_state == GPIO.HIGH
        
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

# ---------- Solstis System Prompt for Standard Kit ----------
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

CRITICAL SINGLE-STEP RULE:
- Give ONLY ONE medical item instruction per response
- NEVER mention multiple medical items in the same response (e.g., don't say "apply ointment and use a bandage")
- If multiple steps are needed, give them one at a time and wait for user confirmation
- Examples of WRONG responses: "Apply antibiotic ointment and then put on a bandage", "Use gauze and tape to secure it"
- Examples of CORRECT responses: "Apply a thin layer of Triple Antibiotic Ointment from the highlighted space. Let me know when you're done.", then after confirmation: "Now place a Band-Aid from the highlighted space so the pad covers the cut. Let me know when you're done."

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
- For small cuts: clean, dry, thin layer of Triple Antibiotic Ointment if available, center the Band-Aid pad over the cut, smooth adhesive around the skin, avoid wrapping too tight, check movement and circulation. "Let me know when you're ready."
- For finger joints: place the Band-Aid pad over the cut, angle the adhesive so it doesn't bunch at the knuckle; if needed, reinforce with Cloth Medical Tape from the highlighted space. "Let me know when you're ready."

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
    """Generate response using GPT"""
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
    
    # Clean up LEDs
    if LED_ENABLED:
        clear_all_leds()
    
    # Clean up reed switch
    cleanup_reed_switch()
    
    sys.exit(0)

async def main():
    global aplay_process, conversation_history
    
    # Initialize LED strip
    if LED_ENABLED:
        init_led_strip()
    
    # Initialize reed switch
    if REED_SWITCH_ENABLED:
        init_reed_switch()
    
    # Initialize OpenAI client
    openai.api_key = API_KEY
    
    conversation_started = False
    opening_message_sent = False

    try:
        log("Waiting for box to open...")
        
        # Main loop - wait for box to open
        while True:
            # Check for box state changes
            state_changed, is_open = check_box_state_change()
            
            if state_changed and is_open and not opening_message_sent:
                # Box just opened - send opening message
                log("Box opened - sending opening greeting...")
                opening_message = f"Hey {USER_NAME}. I'm here to help. If this is life-threatening, please call 9-1-1 now. Otherwise, I'll guide you step by step. Can you tell me what happened?"
                
                # Convert to speech and play
                audio_data = text_to_speech(opening_message)
                if audio_data:
                    start_speak_pulse()
                    play_audio(audio_data)
                    stop_speak_pulse()
                
                print(f"Solstis: {opening_message}")
                opening_message_sent = True
                conversation_started = True
                
            elif state_changed and not is_open:
                # Box just closed - reset conversation state
                log("Box closed - resetting conversation state")
                conversation_history = []
                opening_message_sent = False
                conversation_started = False
                
                # Clear LEDs
                if LED_ENABLED:
                    clear_all_leds()
                
                log("Waiting for box to open...")
                continue
            
            # If box is open and conversation has started, handle voice interaction
            if is_open and conversation_started:
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
                
                # Parse response for LED control
                parse_response_for_items(response_text)
                
                # Convert response to speech and play
                log("Converting response to speech...")
                audio_data = text_to_speech(response_text)
                if audio_data:
                    start_speak_pulse()
                    play_audio(audio_data)
                    stop_speak_pulse()
                
                print(f"Solstis: {response_text}")
                
                # Clear LEDs after response is complete
                if LED_ENABLED:
                    clear_all_leds()
            
            else:
                # Box is closed or conversation hasn't started - wait a bit before checking again
                await asyncio.sleep(0.1)

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
    
    # Check for command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--show-keywords":
        log_keyword_mappings()
        sys.exit(0)
    
    log(f"🩺 Solstis Voice Assistant with Picovoice and GPT starting...")
    log(f"User: {USER_NAME}")
    log(f"Model: {MODEL}")
    log(f"TTS Model: {TTS_MODEL}")
    log(f"TTS Voice: {TTS_VOICE}")
    log(f"Wake Word File: {WAKEWORD_PATH}")
    log(f"Speech Detection - Threshold: {SPEECH_THRESHOLD}, Silence Duration: {SILENCE_DURATION}s")
    log(f"Continuous Mode: {'Enabled' if CONTINUOUS_MODE_ENABLED else 'Disabled'}, Timeout: {CONTINUOUS_MODE_TIMEOUT}s")
    log(f"LED Control: {'Enabled' if LED_ENABLED else 'Disabled'}, Count: {LED_COUNT}, Duration: {LED_DURATION}s")
    log(f"Reed Switch: {'Enabled' if REED_SWITCH_ENABLED else 'Disabled'}, Pin: {REED_SWITCH_PIN}, Debounce: {REED_SWITCH_DEBOUNCE_MS}ms")
    log(f"💡 Run with --show-keywords to see all keyword mappings")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Shutdown complete.")
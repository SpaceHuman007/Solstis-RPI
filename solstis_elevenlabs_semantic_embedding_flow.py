#!/usr/bin/env python3
# Solstis Voice Assistant with ElevenLabs TTS and STT Integration
# Implements dual wake word system and structured conversation states

import asyncio, base64, json, os, signal, subprocess, sys, threading, time, io, wave, types, audioop, struct, math, tempfile
from datetime import datetime
from dotenv import load_dotenv
import requests
import pvporcupine  # pip install pvporcupine
import pvcobra
import openai

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

# --------- Config via env (Picovoice + ElevenLabs) ---------
# Picovoice config
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "YOUR-PICOVOICE-ACCESSKEY-HERE")
SOLSTIS_WAKEWORD_PATH = os.getenv("SOLSTIS_WAKEWORD_PATH", "Solstice_en_raspberry-pi_v3_0_0.ppn")
STEP_COMPLETE_WAKEWORD_PATH = os.getenv("STEP_COMPLETE_WAKEWORD_PATH", "step-complete_en_raspberry-pi_v3_0_0.ppn")
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR = int(os.getenv("MIC_SR", "16000"))  # Porcupine requires 16k

# ElevenLabs config
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
if not ELEVENLABS_API_KEY:
    print("Missing ELEVENLABS_API_KEY", file=sys.stderr); sys.exit(1)

ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

# ElevenLabs voice settings for volume control
ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.5"))
ELEVENLABS_SIMILARITY_BOOST = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.5"))
ELEVENLABS_STYLE = float(os.getenv("ELEVENLABS_STYLE", "0.0"))
ELEVENLABS_SPEAKER_BOOST = os.getenv("ELEVENLABS_SPEAKER_BOOST", "true").lower() == "true"

# OpenAI config (for chat completion only)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4-turbo")

# Audio output config
OUT_DEVICE = os.getenv("AUDIO_DEVICE")  # e.g., "plughw:3,0" or None for default

# Configure ReSpeaker for both input and output
if MIC_DEVICE == "plughw:3,0":
    OUT_DEVICE = "plughw:3,0"  # Use same ReSpeaker device for both input and output
    print(f"[INFO] Using ReSpeaker for both input and output: MIC={MIC_DEVICE}, OUT={OUT_DEVICE}")
elif OUT_DEVICE == MIC_DEVICE and MIC_DEVICE != "plughw:3,0":
    # Only warn for other devices, not ReSpeaker
    print(f"[WARN] MIC_DEVICE and OUT_DEVICE are both {MIC_DEVICE}")
    print("[WARN] Setting OUT_DEVICE to 'default' to avoid conflict")
    OUT_DEVICE = "default"
OUT_SR = int(os.getenv("OUT_SR", "24000"))  # Audio output sample rate
USER_NAME = os.getenv("USER_NAME", "User")

# Speech detection config - Cobra VAD primary, RMS fallback
SPEECH_THRESHOLD = int(os.getenv("SPEECH_THRESHOLD", "800"))  # RMS fallback threshold (not used with Cobra VAD)
MAX_SPEECH_DURATION = float(os.getenv("MAX_SPEECH_DURATION", "15.0"))  # Maximum speech duration (safety timeout)

# Cobra VAD configuration
COBRA_VAD_THRESHOLD = float(os.getenv("COBRA_VAD_THRESHOLD", "0.3"))  # Voice probability threshold (0.0-1.0) - lowered for better detection
VAD_COMPLETION_THRESHOLD = float(os.getenv("VAD_COMPLETION_THRESHOLD", "0.8"))  # Seconds of silence to consider speech complete - increased

# Noise adaptation settings
NOISE_ADAPTATION_ENABLED = os.getenv("NOISE_ADAPTATION_ENABLED", "false").lower() == "true"
NOISE_SAMPLES_COUNT = int(os.getenv("NOISE_SAMPLES_COUNT", "20"))  # Number of samples to measure noise floor
NOISE_MULTIPLIER = float(os.getenv("NOISE_MULTIPLIER", "2.5"))  # Speech threshold = noise_floor * multiplier
MIN_SPEECH_THRESHOLD = int(os.getenv("MIN_SPEECH_THRESHOLD", "200"))  # Minimum threshold regardless of noise
MAX_SPEECH_THRESHOLD = int(os.getenv("MAX_SPEECH_THRESHOLD", "2000"))  # Maximum threshold regardless of noise

# Timeout configurations
T_SHORT = float(os.getenv("T_SHORT", "15.0"))  # Short timeout for initial responses (extended)
T_NORMAL = float(os.getenv("T_NORMAL", "15.0"))  # Normal timeout for conversation
T_LONG = float(os.getenv("T_LONG", "15.0"))  # Long timeout for step completion

# LED Control config
LED_ENABLED = os.getenv("LED_ENABLED", "true").lower() == "true" and LED_CONTROL_AVAILABLE
LED_COUNT = int(os.getenv("LED_COUNT", "730"))  # Number of LED pixels
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

# Enhanced procedure state detection config
SEMANTIC_THRESHOLD = float(os.getenv("SEMANTIC_THRESHOLD", "0.7"))  # Confidence threshold for semantic analysis
SEMANTIC_MODEL = os.getenv("SEMANTIC_MODEL", "text-embedding-3-small")  # OpenAI embedding model
MIN_CONFIDENCE_THRESHOLD = float(os.getenv("MIN_CONFIDENCE_THRESHOLD", "0.5"))  # Minimum confidence threshold
MAX_CONFIDENCE_THRESHOLD = float(os.getenv("MAX_CONFIDENCE_THRESHOLD", "0.95"))  # Maximum confidence threshold
CONTEXT_WINDOW_SIZE = int(os.getenv("CONTEXT_WINDOW_SIZE", "4"))  # Number of recent messages to analyze for context
CONTEXT_BONUS_WEIGHT = float(os.getenv("CONTEXT_BONUS_WEIGHT", "0.1"))  # Weight for context bonuses
ENABLE_FALLBACK_ANALYSIS = os.getenv("ENABLE_FALLBACK_ANALYSIS", "true").lower() == "true"  # Enable fallback analysis
CONSERVATIVE_DEFAULT = os.getenv("CONSERVATIVE_DEFAULT", "true").lower() == "true"  # Use conservative defaults
ENABLE_FEEDBACK_LEARNING = os.getenv("ENABLE_FEEDBACK_LEARNING", "false").lower() == "true"  # Enable learning from feedback
LEARNING_RATE = float(os.getenv("LEARNING_RATE", "0.1"))  # Learning rate for feedback system

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
    EMERGENCY_SITUATION = "emergency_situation"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# Global variables
led_strip = None
speak_pulse_thread = None
speak_pulse_stop = threading.Event()
conversation_history = []
current_state = ConversationState.WAITING_FOR_WAKE_WORD
current_lit_items = []  # Track multiple currently lit items for LED preservation

# Reed switch state variables
box_is_open = False
reed_switch_initialized = False

# User feedback learning system
class FeedbackLearningSystem:
    """Learn from user corrections to improve accuracy"""
    
    def __init__(self):
        self.correction_history = []
        self.pattern_weights = {}
        self.learning_enabled = os.getenv("ENABLE_FEEDBACK_LEARNING", "false").lower() == "true"
        self.learning_rate = float(os.getenv("LEARNING_RATE", "0.1"))
        
    def record_correction(self, predicted_outcome, actual_outcome, response_text):
        """Record when user corrects the system"""
        if not self.learning_enabled:
            return
            
        correction = {
            'predicted': predicted_outcome,
            'actual': actual_outcome,
            'text': response_text,
            'timestamp': time.time()
        }
        
        self.correction_history.append(correction)
        log(f"📚 Learning: Recorded correction - Predicted: {predicted_outcome}, Actual: {actual_outcome}")
        
        # Keep only recent corrections (last 100)
        if len(self.correction_history) > 100:
            self.correction_history = self.correction_history[-100:]
        
        # Update pattern weights
        self.update_pattern_weights(response_text, actual_outcome)
    
    def update_pattern_weights(self, response_text, correct_outcome):
        """Update pattern weights based on corrections"""
        response_lower = response_text.lower()
        
        # Extract key phrases and update their weights
        key_phrases = self.extract_key_phrases(response_text)
        
        for phrase in key_phrases:
            if phrase not in self.pattern_weights:
                self.pattern_weights[phrase] = {}
            
            if correct_outcome not in self.pattern_weights[phrase]:
                self.pattern_weights[phrase][correct_outcome] = 0.0
            
            # Increase weight for correct outcome
            self.pattern_weights[phrase][correct_outcome] += self.learning_rate
            
            # Decrease weight for incorrect outcomes
            for outcome in [ResponseOutcome.NEED_MORE_INFO, ResponseOutcome.USER_ACTION_REQUIRED, 
                          ResponseOutcome.PROCEDURE_DONE, ResponseOutcome.EMERGENCY_SITUATION]:
                if outcome != correct_outcome and outcome in self.pattern_weights[phrase]:
                    self.pattern_weights[phrase][outcome] = max(0.0, 
                        self.pattern_weights[phrase][outcome] - self.learning_rate * 0.5)
    
    def extract_key_phrases(self, text):
        """Extract key phrases from text for learning"""
        # Simple phrase extraction - could be enhanced with NLP
        words = text.lower().split()
        phrases = []
        
        # Extract 2-3 word phrases
        for i in range(len(words) - 1):
            phrases.append(f"{words[i]} {words[i+1]}")
        for i in range(len(words) - 2):
            phrases.append(f"{words[i]} {words[i+1]} {words[i+2]}")
        
        return phrases
    
    def get_adjusted_confidence(self, response_text, base_confidence, predicted_outcome):
        """Adjust confidence based on historical corrections"""
        if not self.learning_enabled or not self.pattern_weights:
            return base_confidence
        
        response_lower = response_text.lower()
        adjustment = 0.0
        
        # Check for learned patterns
        for phrase, weights in self.pattern_weights.items():
            if phrase in response_lower and predicted_outcome in weights:
                adjustment += weights[predicted_outcome] * 0.1  # Small adjustment per phrase
        
        # Apply adjustment (clamp between 0.0 and 1.0)
        adjusted_confidence = max(0.0, min(1.0, base_confidence + adjustment))
        
        if abs(adjustment) > 0.05:  # Only log significant adjustments
            log(f"📚 Learning: Adjusted confidence from {base_confidence:.3f} to {adjusted_confidence:.3f} (Δ{adjustment:+.3f})")
        
        return adjusted_confidence
    
    def get_learning_stats(self):
        """Get learning system statistics"""
        if not self.correction_history:
            return "No corrections recorded yet"
        
        total_corrections = len(self.correction_history)
        recent_corrections = len([c for c in self.correction_history 
                                if time.time() - c['timestamp'] < 3600])  # Last hour
        
        return f"Total corrections: {total_corrections}, Recent (1h): {recent_corrections}, Patterns learned: {len(self.pattern_weights)}"

# Initialize feedback learning system
feedback_learning = FeedbackLearningSystem()

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
    "4 inch by 4 inch Gauze Pads": {
        "keywords": [
            "gauze pad", "gauze pads", "4 gauze pads", "4x4 gauze", 
            "square gauze", "sterile gauze", "dressing pad", "wound pad",
            "gauze square", "medical gauze", "absorbent pad"
        ],
        "description": "4 inch x 4 inch Gauze Pads for wound dressing"
    },
    "2 inch Roll Gauze": {
        "keywords": [
            "roll gauze", "2 roll gauze", "gauze roll", "rolled gauze", 
            "gauze wrap", "bandage roll", "wrapping gauze", "medical wrap"
        ],
        "description": "2 inch Roll Gauze for wrapping and securing dressings"
    },
    "5 inch by 9 inch ABD Pad": {
        "keywords": [
            "abd pad", "abd", "abdominal pad", "large pad", "big pad", 
            "5x9 pad", "major wound pad", "heavy bleeding pad"
        ],
        "description": "5 inch by 9 inch ABD Pad for large wounds and heavy bleeding"
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
        log(" No medical kit items detected in response")
    else:
        log(f"Total items detected: {len(detected_items)}")
    
    return detected_items

# ---------- LED Control System ----------
# LED mapping for kit items with multiple ranges per item
LED_MAPPINGS = {
    "solstis middle": [(643, 663), (696, 727)],
    "QuickClot Gauze": [(62, 86), (270, 293), (264, 264)],
    "Burn Spray": [(41, 62), (234, 269), (226, 226)],
    "Burn Gel Dressing": [(241, 262), (220, 226), (601, 629)],
    "4 inch by 4 inch Gauze Pads": [(581, 623), (636, 642), (720, 727)],
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
    "2 inch Roll Gauze": [(370, 381), (648, 661), (341, 356)],
    "5 inch by 9inch ABD Pad": [(294, 326), (86, 102)],
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
    global current_lit_items
    if not LED_ENABLED or not led_strip:
        return
    
    try:
        for i in range(led_strip.numPixels()):
            led_strip.setPixelColor(i, 0)
        led_strip.show()
        current_lit_items = []  # Clear the tracked items
    except Exception as e:
        log(f"Error clearing LEDs: {e}")

def clear_all_leds_preserve_item():
    """Turn off all LEDs but preserve the current item tracking"""
    if not LED_ENABLED or not led_strip:
        return
    
    try:
        for i in range(led_strip.numPixels()):
            led_strip.setPixelColor(i, 0)
        led_strip.show()
    except Exception as e:
        log(f"Error clearing LEDs: {e}")

def get_current_item_leds():
    """Get the LED indices for all currently lit items"""
    global current_lit_items
    if not current_lit_items or not LED_ENABLED:
        return set()
    
    led_indices = set()
    
    for item_name in current_lit_items:
        # Find the item in mappings (case-insensitive)
        item_key = None
        for key in LED_MAPPINGS.keys():
            if key.lower() in item_name.lower() or item_name.lower() in key.lower():
                item_key = key
                break
        
        if item_key:
            # Get all LED indices for this item
            ranges = LED_MAPPINGS[item_key]
            for start, end in ranges:
                for i in range(start, end + 1):
                    led_indices.add(i)
    
    return led_indices

def restore_item_leds():
    """Restore all currently lit item LEDs after pulsing stops"""
    global current_lit_items
    if not current_lit_items or not LED_ENABLED or not led_strip:
        return
    
    color = (0, 240, 255)  # Default cyan color
    
    try:
        for item_name in current_lit_items:
            # Find the item in mappings (case-insensitive)
            item_key = None
            for key in LED_MAPPINGS.keys():
                if key.lower() in item_name.lower() or item_name.lower() in key.lower():
                    item_key = key
                    break
            
            if item_key:
                ranges = LED_MAPPINGS[item_key]
                # Light up all ranges for this item
                for start, end in ranges:
                    for i in range(start, end + 1):
                        if i < led_strip.numPixels():
                            led_strip.setPixelColor(i, Color(*color))
        
        led_strip.show()
        log(f"Restored LEDs for items: {', '.join(current_lit_items)}")
        
    except Exception as e:
        log(f"Error restoring LEDs for items {current_lit_items}: {e}")

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
        
        # Clear the speaking LEDs when pulsing stops, but preserve item LEDs in overlapping sections
        if LED_ENABLED and led_strip:
            # Clear the speaking LED ranges
            for start_idx, end_idx in ranges:
                for i in range(start_idx, end_idx + 1):
                    if i < led_strip.numPixels():
                        led_strip.setPixelColor(i, 0)
            led_strip.show()
            
            # Restore any item LEDs that were lit
            restore_item_leds()
            
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

def light_multiple_item_leds(item_names, color=(0, 240, 255)):
    """Light up LEDs for multiple items simultaneously"""
    global current_lit_items
    if not LED_ENABLED or not led_strip:
        log(f"LED control not available - would light: {', '.join(item_names)}")
        return
    
    log(f"Lighting LEDs for multiple items: {', '.join(item_names)}")
    
    try:
        # Clear all LEDs first but preserve item tracking
        clear_all_leds_preserve_item()
        
        # Light up all items
        for item_name in item_names:
            # Find the item in mappings (case-insensitive)
            item_key = None
            for key in LED_MAPPINGS.keys():
                if key.lower() in item_name.lower() or item_name.lower() in key.lower():
                    item_key = key
                    break
            
            if item_key:
                ranges = LED_MAPPINGS[item_key]
                log(f"  Lighting {item_name}: {ranges}")
                
                # Light up all ranges for this item
                for range_idx, (start, end) in enumerate(ranges):
                    log(f"    Range {range_idx + 1}: LEDs {start}-{end}")
                    for i in range(start, end + 1):
                        if i < led_strip.numPixels():
                            led_strip.setPixelColor(i, Color(*color))
            else:
                log(f"  No LED mapping found for item: {item_name}")
        
        led_strip.show()
        
        # Track the currently lit items
        current_lit_items = item_names.copy()
        
    except Exception as e:
        log(f"Error lighting LEDs for items {item_names}: {e}")

def light_item_leds(item_name, color=(0, 240, 255)):
    """Light up LEDs for a single item (backwards compatibility)"""
    light_multiple_item_leds([item_name], color)

def parse_response_for_items(response_text):
    """Parse AI response text to identify mentioned items and light appropriate LEDs"""
    if not LED_ENABLED:
        return
    
    # Use enhanced keyword detection
    detected_items = detect_mentioned_items(response_text)
    
    # Light LEDs for all detected items
    if detected_items:
        item_names = [item["item"] for item in detected_items]
        log(f"Lighting LEDs for all detected items: {', '.join(item_names)}")
        light_multiple_item_leds(item_names)

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

def handle_user_feedback(user_text, conversation_history):
    """Handle user feedback about incorrect procedure state detection"""
    feedback_indicators = [
        "that's wrong", "incorrect", "not right", "mistake", "error",
        "i didn't mean", "that's not what", "you misunderstood",
        "i was asking", "i was saying", "you got it wrong"
    ]
    
    user_lower = user_text.lower()
    if any(indicator in user_lower for indicator in feedback_indicators):
        log("📚 User feedback detected - system may have made incorrect detection")
        
        # Try to extract the correct interpretation
        if "i was asking" in user_lower or "i was saying" in user_lower:
            # User is clarifying their intent
            log("📚 User clarifying intent - this suggests NEED_MORE_INFO was correct")
            return ResponseOutcome.NEED_MORE_INFO, "I understand, thank you for clarifying. Let me help you with that."
        elif "you misunderstood" in user_lower or "not what i meant" in user_lower:
            # User is correcting a misunderstanding
            log("📚 User correcting misunderstanding - adjusting approach")
            return ResponseOutcome.NEED_MORE_INFO, "I apologize for the confusion. Could you help me understand what you need?"
    
    return None, None

def process_response(user_text, conversation_history=None):
    """
    Process user response and determine the outcome using enhanced semantic analysis.
    Returns one of: NEED_MORE_INFO, USER_ACTION_REQUIRED, PROCEDURE_DONE, EMERGENCY_SITUATION
    """
    try:
        import openai
        
        # Initialize OpenAI client
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        
        # Enhanced keyword analysis with confidence scoring (no API calls)
        def analyze_response_with_confidence(response_text, conversation_history):
            """Analyze response with confidence scoring and context awareness using weighted keywords"""
            response_lower = response_text.lower()
            
            # Weighted keyword analysis (keeping the sophisticated weights)
            user_action_keywords = {
                "let me know when": 0.9, "when you're done": 0.9, "when you're ready": 0.8,
                "say step complete": 0.95, "tell me when": 0.8, "apply": 0.7, "use": 0.6,
                "place": 0.6, "put on": 0.7, "secure": 0.6, "wrap": 0.6, "cover": 0.6,
                "from your kit": 0.8, "from the highlighted": 0.8, "please apply": 0.8,
                "please use": 0.7, "please place": 0.7, "now apply": 0.8, "now use": 0.7
            }
            
            procedure_done_keywords = {
                "procedure is complete": 0.95, "treatment is done": 0.9, "you're all set": 0.8,
                "that should help": 0.7, "you should be fine": 0.8, "take care": 0.6,
                "you're good": 0.7, "all done": 0.8, "procedure complete": 0.9,
                "treatment complete": 0.9, "finished": 0.7, "completed": 0.8,
                "you should be okay": 0.8, "you'll be fine": 0.8, "everything looks good": 0.8,
                "keep an eye on": 0.6, "monitor": 0.6, "watch for": 0.6,
                "healthcare professional": 0.7, "see a doctor": 0.7, "medical attention": 0.7,
                "excellent": 0.5, "well done": 0.5, "great job": 0.5,
                "is there anything else": 0.4, "anything else i can help": 0.4
            }
            
            need_more_info_keywords = {
                "where exactly": 0.9, "how big": 0.8, "how much": 0.8, "how long": 0.8,
                "what does": 0.8, "can you tell me": 0.8, "is it": 0.6, "are you": 0.6,
                "do you": 0.6, "what kind": 0.8, "which": 0.7, "how severe": 0.8,
                "describe": 0.8, "explain": 0.8, "tell me more": 0.8, "i need to know": 0.8,
                "before i can help": 0.8, "to better understand": 0.8, "to assess": 0.8
            }
            
            emergency_keywords = {
                "emergency room": 0.9, "call 9-1-1": 0.95, "immediate medical attention": 0.9,
                "seek immediate": 0.8, "go to the nearest": 0.8, "call for medical help": 0.9,
                "emergency care": 0.9, "urgent medical": 0.8, "critical situation": 0.9
            }
            
            # Calculate weighted scores
            def calculate_score(keywords_dict):
                total_score = 0.0
                matches = 0
                for keyword, weight in keywords_dict.items():
                    if keyword in response_lower:
                        total_score += weight
                        matches += 1
                return total_score, matches
            
            user_action_score, ua_matches = calculate_score(user_action_keywords)
            procedure_done_score, pd_matches = calculate_score(procedure_done_keywords)
            need_more_info_score, nmi_matches = calculate_score(need_more_info_keywords)
            emergency_score, em_matches = calculate_score(emergency_keywords)
            
            # Apply conversation context bonuses
            if conversation_history and len(conversation_history) > 0:
                recent_messages = conversation_history[-4:] if len(conversation_history) >= 4 else conversation_history
                recent_text = " ".join([msg.get("content", "") for msg in recent_messages if msg.get("role") == "assistant"])
                
                # Context bonus for continuation patterns
                if any(phrase in recent_text.lower() for phrase in ["where", "how", "what", "describe"]):
                    need_more_info_score += 0.2
                if any(phrase in recent_text.lower() for phrase in ["apply", "use", "place", "put"]):
                    user_action_score += 0.2
            
            scores = {
                ResponseOutcome.USER_ACTION_REQUIRED: user_action_score,
                ResponseOutcome.PROCEDURE_DONE: procedure_done_score,
                ResponseOutcome.NEED_MORE_INFO: need_more_info_score,
                ResponseOutcome.EMERGENCY_SITUATION: emergency_score
            }
            
            best_outcome = max(scores, key=scores.get)
            best_score = scores[best_outcome]
            
            log(f"🔍 Enhanced Keyword Analysis:")
            log(f"   User Action: {user_action_score:.3f} ({ua_matches} matches)")
            log(f"   Procedure Done: {procedure_done_score:.3f} ({pd_matches} matches)")
            log(f"   Need More Info: {need_more_info_score:.3f} ({nmi_matches} matches)")
            log(f"   Emergency: {emergency_score:.3f} ({em_matches} matches)")
            log(f"   Best: {best_outcome} (confidence: {best_score:.3f})")
            
            return best_outcome, best_score
        
        
        # Prepare messages
        messages = [
            {"role": "system", "content": get_system_prompt()}
        ]
        
        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current user message
        messages.append({"role": "user", "content": user_text})
        
        # Generate response with lower temperature for more conservative, clarification-focused responses
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=500,
            temperature=0.5  # Lower temperature for more conservative responses
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Update conversation history
        conversation_history.append({"role": "user", "content": user_text})
        conversation_history.append({"role": "assistant", "content": response_text})
        
        # Keep conversation history manageable (last 10 exchanges)
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]
        
        # Use enhanced analysis with confidence scoring
        outcome, confidence = analyze_response_with_confidence(response_text, conversation_history)
        
        return outcome, response_text
    
    except Exception as e:
        log(f"Error processing response: {e}")
        return ResponseOutcome.NEED_MORE_INFO, "I'm sorry, I'm having trouble processing your request right now."

def get_system_prompt():
    """Generate the system prompt for the standard Solstis kit"""
    
    # Standard kit contents
    kit_contents = [
        "Band-Aids",
        "4 inch by 4 inch Gauze Pads",
        "2 inch Roll Gauze",
        "5 inch by 9 inch ABD Pad",
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

CRITICAL BEHAVIOR: Your primary role is to ASK QUESTIONS and gather information before providing any treatment. Always err on the side of asking for more details rather than making assumptions about the user's situation.

AVAILABLE ITEMS IN YOUR KIT:
{contents_str}

IMPORTANT: When referencing kit items, use the EXACT names from the list above. For example:
- Say "Band-Aids" not "bandages" or "adhesive bandages"
- Say "4 inch by 4 inch Gauze Pads" not "gauze" or "gauze squares"
- Say "2 inch Roll Gauze" not "roll gauze" or "gauze roll"
- Say "5 inch by 9 inch ABD Pad" not "ABD pad" or "large pad"
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
• HEAVILY PRIORITIZE asking clarifying questions to fully understand the user's situation before providing any treatment
• Always ask for specific details about the injury/symptom before recommending any treatment
• Assess for life-threatening danger but don't overreact to common symptoms
• Give clear, step-by-step instructions for self-treatment ONLY after gathering sufficient information
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

CRITICAL CLARIFICATION PRIORITY:
- ALWAYS ask clarifying questions before providing any treatment recommendations
- Default to asking for more information rather than assuming details
- Ask about: location of injury, size, severity, duration, symptoms, pain level, bleeding amount
- Only proceed with treatment after gathering sufficient details about the situation
- If unsure about any aspect, ask for clarification rather than making assumptions
- Examples of clarifying questions: "Where exactly is the cut?", "How big is the wound?", "Is it bleeding a lot or just a little?", "How long ago did this happen?", "What does the pain feel like?"

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
- NEVER ask "Is there anything else you need help with?" or similar questions - the system will handle this
- When treatment is complete, end with a brief summary or next steps, NOT with questions about additional help
- Examples of GOOD endings: "Keep an eye on the cut for signs of infection." "The treatment is complete."
- Examples of BAD endings: "Is there anything else you need help with?" "Do you need assistance with anything else?"

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
- First attempt: Direct pressure with 4 inch x 4 inch Gauze Pads for 5 minutes
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

# ---------- ElevenLabs Integration ----------
def transcribe_audio_elevenlabs(audio_data):
    """Transcribe audio using ElevenLabs Speech-to-Text API"""
    try:
        log("🎤 ElevenLabs STT: Starting transcription")
        
        # ElevenLabs STT API endpoint
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        
        # Prepare headers
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        # Create a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            # Convert PCM16 to WAV format
            with wave.open(temp_file.name, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(OUT_SR)
                wav_file.writeframes(audio_data)
            
            # Read the WAV file and send to ElevenLabs with model_id
            with open(temp_file.name, 'rb') as audio_file:
                files = {'file': ('audio.wav', audio_file.read(), 'audio/wav')}
                data = {'model_id': 'scribe_v1'}  # ElevenLabs uses whisper-1 for STT
                response = requests.post(url, headers=headers, files=files, data=data)
            
            # Clean up temp file
            os.unlink(temp_file.name)
        
        if response.status_code == 200:
            result = response.json()
            transcript = result.get('text', '').strip()
            log(f"🎤 ElevenLabs STT Success: '{transcript}'")
            return transcript
        else:
            log(f"🎤 ElevenLabs STT Error: {response.status_code} - {response.text}")
            return ""
    
    except Exception as e:
        log(f"🎤 ElevenLabs STT Error: {e}")
        return ""

def text_to_speech_elevenlabs(text):
    """Convert text to speech using ElevenLabs TTS API"""
    try:
        log(f"🎤 ElevenLabs TTS Request: '{text[:50]}{'...' if len(text) > 50 else ''}'")
        log(f"🎤 ElevenLabs TTS Config: voice_id={ELEVENLABS_VOICE_ID}, model_id=eleven_turbo_v2_5, format=pcm_24000")
        
        # ElevenLabs TTS API endpoint with PCM format as query parameter
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}?output_format=pcm_24000"
        
        # Prepare headers
        headers = {
            "Accept": "audio/pcm",  # Request PCM format
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        # Prepare data (output_format is now in URL query parameter)
        data = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",  # Use turbo model that fully supports PCM
            "voice_settings": {
                "stability": ELEVENLABS_STABILITY,
                "similarity_boost": ELEVENLABS_SIMILARITY_BOOST,
                "style": ELEVENLABS_STYLE,  # Style exaggeration (0.0 = neutral)
                "use_speaker_boost": ELEVENLABS_SPEAKER_BOOST  # Boost speaker characteristics for louder output
            }
        }
        
        # Make request
        response = requests.post(url, json=data, headers=headers)
        
        # Debug: Log the full request details
        log(f"🎤 ElevenLabs Request URL: {url}")
        log(f"🎤 ElevenLabs Request Data: {data}")
        log(f"🎤 ElevenLabs Request Headers: {headers}")
        
        if response.status_code == 200:
            audio_data = response.content
            # Check the actual sample rate from ElevenLabs response headers
            content_type = response.headers.get('content-type', '')
            log(f"🎤 ElevenLabs Response: Content-Type={content_type}")
            log(f"🎤 ElevenLabs TTS Success: Generated {len(audio_data)} bytes of PCM audio data (24kHz)")
            return audio_data
        else:
            log(f"🎤 ElevenLabs TTS Error: {response.status_code} - {response.text}")
            return b""
    
    except Exception as e:
        log(f"🎤 ElevenLabs TTS Error: {e}")
        return b""

# ---------- Voice Activity Detection ----------
# Initialize Cobra VAD
try:
    cobra_handle = pvcobra.create(access_key=PICOVOICE_ACCESS_KEY)
    VAD_AVAILABLE = True
    log(f"Cobra VAD initialized successfully - Sample rate: {cobra_handle.sample_rate}, Frame length: {cobra_handle.frame_length}")
except Exception as e:
    log(f"Failed to initialize Cobra VAD: {e}")
    VAD_AVAILABLE = False
    cobra_handle = None

def calculate_rms(audio_data):
    """Calculate RMS (Root Mean Square) of audio data for voice activity detection (legacy)"""
    if len(audio_data) == 0:
        return 0
    
    # Convert bytes to signed 16-bit integers
    samples = struct.unpack(f"<{len(audio_data)//2}h", audio_data)
    
    # Calculate RMS
    sum_squares = sum(sample * sample for sample in samples)
    rms = math.sqrt(sum_squares / len(samples))
    return rms

def is_speech_detected_cobra(audio_data):
    """Determine if audio contains speech using Cobra VAD"""
    if not VAD_AVAILABLE or len(audio_data) == 0:
        return False
    
    try:
        # Convert bytes to 16-bit PCM samples
        samples = struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data)
        
        # Process audio in frames
        frame_length = cobra_handle.frame_length
        speech_frames = 0
        total_frames = 0
        
        for i in range(0, len(samples), frame_length):
            frame = samples[i:i + frame_length]
            if len(frame) == frame_length:
                total_frames += 1
                voice_probability = cobra_handle.process(frame)
                if voice_probability > COBRA_VAD_THRESHOLD:
                    speech_frames += 1
        
        # Return True if more than 20% of frames contain speech
        if total_frames == 0:
            return False
        
        speech_ratio = speech_frames / total_frames
        is_speech = speech_ratio > 0.2
        
        # Debug logging for speech detection
        if is_speech:
            log(f"Cobra VAD: Speech detected (ratio: {speech_ratio:.2f}, frames: {speech_frames}/{total_frames})")
        
        return is_speech
        
    except Exception as e:
        log(f"Cobra VAD error: {e}")
        # Fallback to RMS
        rms = calculate_rms(audio_data)
        return rms > SPEECH_THRESHOLD

def analyze_speech_completion_cobra(audio_data):
    """Analyze audio to determine if user has finished speaking using Cobra VAD"""
    if not VAD_AVAILABLE or len(audio_data) == 0:
        return False, 0.0
    
    try:
        # Convert bytes to 16-bit PCM samples
        samples = struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data)
        
        # Process audio in frames
        frame_length = cobra_handle.frame_length
        sample_rate = cobra_handle.sample_rate
        
        # Track speech activity over time
        speech_timeline = []
        frame_duration = frame_length / sample_rate  # Duration of each frame in seconds
        
        frames = []
        for i in range(0, len(samples), frame_length):
            frame = samples[i:i + frame_length]
            if len(frame) == frame_length:
                frames.append(frame)
        
        # Analyze each frame and track speech activity
        for i, frame in enumerate(frames):
            voice_probability = cobra_handle.process(frame)
            is_speech = voice_probability > COBRA_VAD_THRESHOLD
            timestamp = i * frame_duration
            speech_timeline.append((timestamp, is_speech))
        
        if not speech_timeline:
            return False, 0.0
        
        # Find the last speech activity
        last_speech_time = None
        for timestamp, is_speech in reversed(speech_timeline):
            if is_speech:
                last_speech_time = timestamp
                break
        
        if last_speech_time is None:
            # No speech detected at all
            log("Cobra VAD: No speech detected")
            return False, 0.0
        
        # Calculate silence duration since last speech
        total_duration = len(frames) * frame_duration
        silence_duration = total_duration - last_speech_time
        
        # Calculate overall speech ratio
        speech_frames = sum(1 for _, is_speech in speech_timeline if is_speech)
        overall_speech_ratio = speech_frames / len(speech_timeline) if speech_timeline else 0.0
        
        log(f"Cobra VAD Analysis: total_duration={total_duration:.2f}s, last_speech_time={last_speech_time:.2f}s, silence_duration={silence_duration:.2f}s")
        log(f"Cobra VAD Ratios: overall_speech_ratio={overall_speech_ratio:.2f}")
        
        # User is done speaking if:
        # 1. We have detected speech at some point (any speech detected)
        # 2. Silence duration exceeds threshold
        has_detected_speech = last_speech_time is not None  # Any speech detected at all
        is_done_speaking = has_detected_speech and silence_duration >= VAD_COMPLETION_THRESHOLD
        
        log(f"Cobra VAD Decision: is_done={is_done_speaking} (has_speech: {has_detected_speech}, silence >= {VAD_COMPLETION_THRESHOLD}s: {silence_duration >= VAD_COMPLETION_THRESHOLD})")
        
        return is_done_speaking, overall_speech_ratio
        
    except Exception as e:
        log(f"Cobra VAD error: {e}")
        # Fallback: assume not done speaking
        return False, 0.0

def is_speech_detected(audio_data, threshold=SPEECH_THRESHOLD, adaptive_threshold=None):
    """Determine if audio contains speech - uses Cobra VAD by default, falls back to RMS"""
    if VAD_AVAILABLE:
        try:
            return is_speech_detected_cobra(audio_data)
        except Exception as e:
            log(f"Cobra VAD failed: {e}, falling back to RMS")
    
    # Fallback to RMS-based detection
    rms = calculate_rms(audio_data)
    effective_threshold = adaptive_threshold if adaptive_threshold is not None else threshold
    return rms > effective_threshold

def measure_noise_floor(arec, frame_bytes, sample_count=NOISE_SAMPLES_COUNT):
    """Measure background noise floor to adapt speech detection threshold"""
    if not NOISE_ADAPTATION_ENABLED:
        return SPEECH_THRESHOLD
    
    log(f"🔊 Measuring noise floor with {sample_count} samples...")
    noise_samples = []
    
    for i in range(sample_count):
        chunk = arec.stdout.read(frame_bytes)
        if not chunk:
            break
        rms = calculate_rms(chunk)
        noise_samples.append(rms)
    
    if not noise_samples:
        log("⚠️ No noise samples collected, using default threshold")
        return SPEECH_THRESHOLD
    
    # Calculate average noise floor
    avg_noise = sum(noise_samples) / len(noise_samples)
    
    # Calculate adaptive threshold
    adaptive_threshold = avg_noise * NOISE_MULTIPLIER
    
    # Clamp to min/max bounds
    adaptive_threshold = max(MIN_SPEECH_THRESHOLD, min(MAX_SPEECH_THRESHOLD, adaptive_threshold))
    
    log(f"🔊 Noise floor: {avg_noise:.1f} RMS, Adaptive threshold: {adaptive_threshold:.1f} RMS")
    return adaptive_threshold

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
        # Clean up any existing audio processes before starting
        log("🧹 Cleaning up audio processes before wake word detection")
        cleanup_audio_processes()
        time.sleep(1.0)  # Give devices time to release
        
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
                        log("🔧 Mic stream ended - attempting device reset")
                        cleanup_audio_processes()
                        time.sleep(2.0)  # Longer wait for device reset
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
        
        # Test microphone before starting
        log("🎤 Testing microphone before starting...")
        test_cmd = ["arecord", "-D", MIC_DEVICE, "-f", "S16_LE", "-r", str(mic_sr), "-c", "1", "-d", "1", "/dev/null"]
        test_result = subprocess.run(test_cmd, capture_output=True, timeout=5)
        if test_result.returncode != 0:
            log(f"⚠️  Microphone test failed: {test_result.stderr.decode()}")
            log("🔄 Attempting device reset and retry...")
            reset_audio_devices()
            test_result = subprocess.run(test_cmd, capture_output=True, timeout=5)
            if test_result.returncode != 0:
                log(f"❌ Microphone still not working after reset: {test_result.stderr.decode()}")
                return None
            else:
                log("✅ Microphone working after reset")
        else:
            log("✅ Microphone test passed")
        
        arec = spawn_arecord(mic_sr, MIC_DEVICE)

        # Measure noise floor for adaptive threshold
        adaptive_threshold = measure_noise_floor(arec, frame_bytes)

        # Capture audio until speech pause
        log("Capturing audio until speech pause...")
        log(f"Will wait up to {timeout}s for speech to start, then check for completion")
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
                # Check if the process is still running
                if arec.poll() is not None:
                    # Process has terminated, check for errors
                    stderr_output = arec.stderr.read().decode('utf-8', errors='ignore')
                    if stderr_output:
                        log(f"⚠️  arecord process terminated with error: {stderr_output}")
                    else:
                        log("⚠️  arecord process terminated unexpectedly")
                    break
                else:
                    # Process still running but no data - device might be busy
                    log("⚠️  No audio data from arecord, device might be busy")
                    time.sleep(0.1)  # Brief pause before retry
                    continue
            
            audio_buffer += chunk
            
            # Check for speech in this frame using Cobra VAD
            current_time = time.time()
            
            if is_speech_detected(chunk, SPEECH_THRESHOLD, adaptive_threshold):
                if not speech_detected:
                    log("Cobra VAD: Speech detected, continuing capture...")
                    speech_detected = True
                    speech_start_time = current_time
                else:
                    # Still detecting speech, log occasionally
                    if int(current_time) % 3 == 0:  # Log every 3 seconds
                        log("Cobra VAD: Still detecting speech...")
            else:
                # No speech detected in this frame
                if not speech_detected:
                    # Still waiting for speech to start
                    elapsed = current_time - start_time
                    if int(elapsed) % 5 == 0:  # Log every 5 seconds while waiting
                        log(f"Cobra VAD: Waiting for speech to start... ({elapsed:.1f}s elapsed)")
                elif speech_detected:
                    silence_duration = current_time - speech_start_time if speech_start_time else 0
                    log(f"Cobra VAD: No speech in current frame, silence duration: {silence_duration:.1f}s")
            
            # Check for completion ONLY if we've been detecting speech for a while
            # Only check completion if we have enough audio AND have been detecting speech for at least 2 seconds
            if speech_detected and len(audio_buffer) > frame_bytes * 15 and speech_start_time and (current_time - speech_start_time) >= 2.0:
                try:
                    is_done, speech_ratio = analyze_speech_completion_cobra(audio_buffer)
                    if is_done:
                        log(f"Cobra VAD: User finished speaking (speech ratio: {speech_ratio:.2f})")
                        break
                    else:
                        # Log current state for debugging (less frequent to avoid spam)
                        if int(current_time) % 3 == 0:  # Log every 3 seconds
                            log(f"Cobra VAD: Still speaking (speech ratio: {speech_ratio:.2f})")
                except Exception as e:
                    log(f"Cobra VAD error: {e}, continuing with timeout fallback")
                    # Only use timeout as absolute fallback
                    if current_time - speech_start_time >= MAX_SPEECH_DURATION:
                        log(f"Maximum speech duration ({MAX_SPEECH_DURATION}s) reached, stopping")
                        break
            
            # Safety check: don't capture too long (only after speech has been detected)
            if speech_detected and speech_start_time and current_time - speech_start_time >= MAX_SPEECH_DURATION:
                log(f"Maximum speech duration ({MAX_SPEECH_DURATION}s) reached, stopping")
                break

        # Check if we have any audio captured
        if len(audio_buffer) == 0:
            # Determine the reason for no audio capture
            elapsed_time = time.time() - start_time
            if elapsed_time >= timeout:
                log(f"No audio captured - timeout reached ({elapsed_time:.1f}s)")
            elif arec.poll() is not None:
                log("No audio captured - arecord process failed")
            else:
                log(f"No audio captured - device issue or early termination ({elapsed_time:.1f}s)")
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

# ---------- Fast Yes/No Detection Functions ----------
def detect_yes_no_response(user_text, threshold=0.5):
    """
    Detect if user response is yes or no using weighted keyword matching.
    Fast alternative to embeddings that doesn't require API calls.
    
    Args:
        user_text: The user's input text
        threshold: Minimum weighted score to consider a match
    
    Returns:
        ("yes", confidence), ("no", confidence), or (None, 0.0) if unclear
    """
    text_lower = user_text.lower()
    
    # Define weighted keywords for yes/no detection
    yes_keywords = {
        # Direct yes words (high weight)
        "yes": 1.0, "yeah": 0.9, "yep": 0.9, "yup": 0.9, "sure": 0.8, 
        "absolutely": 0.9, "definitely": 0.9, "of course": 0.8, "certainly": 0.8,
        
        # Help-related words (medium-high weight)
        "help": 0.8, "assistance": 0.8, "assist": 0.7, "support": 0.6,
        "need": 0.7, "require": 0.6, "want": 0.5,
        
        # Medical/emergency words (high weight)
        "hurt": 0.9, "injured": 0.9, "pain": 0.8, "bleeding": 0.9,
        "cut": 0.8, "wound": 0.8, "injury": 0.8, "emergency": 0.9,
        "medical": 0.8, "first aid": 0.9, "treatment": 0.7,
        "bandage": 0.7, "bandages": 0.7, "supplies": 0.6,
        
        # Problem indicators (medium weight)
        "problem": 0.6, "issue": 0.6, "wrong": 0.5, "trouble": 0.5,
        
        # Affirmative phrases
        "i do": 0.8, "i need": 0.8, "i want": 0.7, "please": 0.6,
        "that would": 0.7, "that sounds": 0.6
    }
    
    no_keywords = {
        # Direct no words (high weight)
        "no": 1.0, "nope": 0.9, "nah": 0.8, "not": 0.7, "nothing": 0.8,
        "never": 0.6, "none": 0.6,
        
        # Status words (medium-high weight) - removed "okay" to avoid conflict
        "fine": 0.8, "good": 0.7, "well": 0.6, "healthy": 0.7,
        "safe": 0.6, "all set": 0.8, "good to go": 0.7,
        
        # Rejection phrases (high weight)
        "no thanks": 0.9, "no thank you": 0.9, "thank you": 0.8, "not really": 0.8,
        "not right now": 0.8, "don't need": 0.8, "don't want": 0.7,
        "i'm good": 0.8, "i'm fine": 0.8, "i'm okay": 0.7,
        
        # Completion/status phrases (medium weight)
        "all good": 0.7, "no problem": 0.6, "no issues": 0.6,
        "no worries": 0.5, "everything's fine": 0.8, "nothing's wrong": 0.8,
        "i don't": 0.7, "i can't": 0.6, "not today": 0.7
    }
    
    # Calculate weighted scores
    yes_score = 0.0
    no_score = 0.0
    
    # Count word occurrences and apply weights
    words = text_lower.split()
    
    for word in words:
        # Clean word of punctuation for better matching
        clean_word = word.strip('.,!?;:"()[]{}')
        
        # Check individual words (both original and cleaned)
        if word in yes_keywords:
            yes_score += yes_keywords[word]
        elif clean_word in yes_keywords:
            yes_score += yes_keywords[clean_word]
            
        if word in no_keywords:
            no_score += no_keywords[word]
        elif clean_word in no_keywords:
            no_score += no_keywords[clean_word]
    
    # Check for phrases (2-3 word combinations) with punctuation handling
    for i in range(len(words) - 1):
        # Clean both words for phrase matching
        clean_word1 = words[i].strip('.,!?;:"()[]{}')
        clean_word2 = words[i+1].strip('.,!?;:"()[]{}')
        phrase_2 = f"{clean_word1} {clean_word2}"
        
        if phrase_2 in yes_keywords:
            yes_score += yes_keywords[phrase_2]
        if phrase_2 in no_keywords:
            no_score += no_keywords[phrase_2]
    
    for i in range(len(words) - 2):
        # Clean all three words for phrase matching
        clean_word1 = words[i].strip('.,!?;:"()[]{}')
        clean_word2 = words[i+1].strip('.,!?;:"()[]{}')
        clean_word3 = words[i+2].strip('.,!?;:"()[]{}')
        phrase_3 = f"{clean_word1} {clean_word2} {clean_word3}"
        
        if phrase_3 in yes_keywords:
            yes_score += yes_keywords[phrase_3]
        if phrase_3 in no_keywords:
            no_score += no_keywords[phrase_3]
    
    # Normalize scores by text length (less aggressive normalization)
    text_length_factor = min(1.0, 15.0 / len(words)) if words else 1.0
    yes_score *= text_length_factor
    no_score *= text_length_factor
    
    # Determine result with lower threshold for better detection
    threshold = 0.3  # Lowered from 0.5 for better sensitivity
    
    # Enhanced debugging
    log(f"🔍 Yes/No Detection Analysis:")
    log(f"   Text: '{user_text}'")
    log(f"   Words: {words}")
    log(f"   Yes score: {yes_score:.3f} (threshold: {threshold})")
    log(f"   No score: {no_score:.3f} (threshold: {threshold})")
    log(f"   Text length factor: {text_length_factor:.3f}")
    
    if yes_score > no_score and yes_score >= threshold:
        confidence = min(1.0, yes_score)
        log(f"✅ Keyword Detection: '{user_text}' -> YES (score: {yes_score:.3f}, confidence: {confidence:.3f})")
        return "yes", confidence
    elif no_score > yes_score and no_score >= threshold:
        confidence = min(1.0, no_score)
        log(f"❌ Keyword Detection: '{user_text}' -> NO (score: {no_score:.3f}, confidence: {confidence:.3f})")
        return "no", confidence
    else:
        best_score = max(yes_score, no_score)
        log(f"❓ Keyword Detection: '{user_text}' -> UNCLEAR (yes: {yes_score:.3f}, no: {no_score:.3f}, best: {best_score:.3f})")
        return None, best_score

# ---------- Audio Processing Functions ----------
def detect_pcm_sample_rate(audio_data):
    """Try to detect PCM sample rate from audio data length and duration"""
    # ElevenLabs PCM is typically 22050Hz or 44100Hz
    # For a typical "Hey there" phrase (~2 seconds), we can estimate
    if len(audio_data) < 100000:  # Short audio
        return 22050  # Common for voice
    else:
        return 44100  # Higher quality

def play_audio(audio_data):
    """Play audio data using appropriate player based on format"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            log(f"🔊 Audio Playback: Starting playback of {len(audio_data)} bytes (attempt {attempt + 1}/{max_retries})")
            
            # Clean up any existing audio processes before starting
            if attempt > 0:
                log(f"🔊 Audio Cleanup: Cleaning up before retry attempt {attempt + 1}")
                subprocess.run(["pkill", "-9", "-f", "aplay"], check=False, capture_output=True)
                time.sleep(0.5)
            
            # ElevenLabs now properly returns PCM format
            log(f"🔊 Audio Format: PCM (ElevenLabs 24kHz), using aplay")
            log(f"🔊 Audio Config: sample_rate=24000, device={OUT_DEVICE or 'default'}")
            player = spawn_aplay(24000)
            
            log(f"🔊 Audio Process: Spawned player process (PID: {player.pid})")
            
            log(f"🔊 Audio Write: Writing {len(audio_data)} bytes to player stdin")
            player.stdin.write(audio_data)
            player.stdin.close()
            log(f"🔊 Audio Write: Closed stdin, waiting for playback to complete")
            
            # Wait for playback to complete with timeout
            try:
                return_code = player.wait(timeout=10)  # 10 second timeout for PCM
                log(f"🔊 Audio Complete: player finished with return code {return_code}")
                
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
                log(f"🔊 Audio Timeout: player process timed out, killing it")
                player.kill()
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
    """Convert text to speech and play it using ElevenLabs"""
    log(f"🗣️  Speaking: {text}")
    audio_data = text_to_speech_elevenlabs(text)
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
        reset_audio_devices()  # Reset devices before listening
        audio_data = listen_for_speech(timeout=T_SHORT)
        
        if audio_data is None:
            # First retry of opening
            log("🔄 No response, retrying opening message")
            say(opening_message())
            cleanup_audio_processes()  # Clean up before retry
            audio_data = listen_for_speech(timeout=T_SHORT)
            
            if audio_data is None:
                # Still no response, prompt and wait for wake word
                log("🔇 Still no response, prompting and waiting for wake word")
                say(prompt_no_response())
                current_state = ConversationState.WAITING_FOR_WAKE_WORD
                
                wake_word = wait_for_wake_word()
                if wake_word == "SOLSTIS":
                    say(prompt_continue_help())
                    # Don't skip opening message - user didn't actually respond, so replay it
                    skip_opening_message = False
                    continue
                else:
                    continue
        
        # Transcribe the response using ElevenLabs
        user_text = transcribe_audio_elevenlabs(audio_data)
        if not user_text:
            log("❌ No transcription received - user may not have spoken")
            # Handle silence/no response
            say("I am hearing no response, be sure to say 'SOLSTIS' if you need my assistance!")
            current_state = ConversationState.WAITING_FOR_WAKE_WORD
            
            wake_word = wait_for_wake_word()
            if wake_word == "SOLSTIS":
                say(prompt_continue_help())
                # Set flag to skip opening message on next iteration
                skip_opening_message = True
                continue
            else:
                continue
        
        print(f"User: {user_text}")
        
        # Check if the transcription is too short or unclear (likely noise/unclear speech)
        if len(user_text.strip()) < 3 or user_text.strip().lower() in ['', 'huh', 'what', 'um', 'uh', 'ah']:
            log(f"❓ Unclear or very short transcription: '{user_text}' - treating as silence")
            say("I am hearing no response, be sure to say 'SOLSTIS' if you need my assistance!")
            current_state = ConversationState.WAITING_FOR_WAKE_WORD
            
            wake_word = wait_for_wake_word()
            if wake_word == "SOLSTIS":
                say(prompt_continue_help())
                # Set flag to skip opening message on next iteration
                skip_opening_message = True
                continue
            else:
                continue
        
        # Check for background noise or unclear audio transcriptions (parentheses-based detection)
        if user_text.strip().startswith('(') and user_text.strip().endswith(')'):
            log(f"🔇 Background noise detected (parentheses): '{user_text}' - treating as silence")
            say("I am hearing no response, be sure to say 'SOLSTIS' if you need my assistance!")
            current_state = ConversationState.WAITING_FOR_WAKE_WORD
            
            wake_word = wait_for_wake_word()
            if wake_word == "SOLSTIS":
                say(prompt_continue_help())
                # Don't skip opening message - user didn't actually respond, so replay it
                skip_opening_message = False
                continue
            else:
                continue
        
        # Check for user feedback about incorrect detection
        feedback_outcome, feedback_response = handle_user_feedback(user_text, conversation_history)
        if feedback_outcome is not None:
            log("📚 Processing user feedback")
            say(feedback_response)
            # Record the correction for learning
            if len(conversation_history) >= 2:
                last_assistant_response = conversation_history[-1].get("content", "")
                feedback_learning.record_correction(
                    ResponseOutcome.NEED_MORE_INFO,  # Previous detection was likely wrong
                    feedback_outcome,  # Correct outcome based on user feedback
                    last_assistant_response
                )
            continue
        
        # Check for yes/no response using weighted keywords
        response_intent, confidence = detect_yes_no_response(user_text, threshold=0.3)
        
        if response_intent == "no":
            log(f"👋 User declined help (confidence: {confidence:.3f})")
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
        elif response_intent == "yes":
            log(f"✅ User accepted help (confidence: {confidence:.3f})")
            # Continue to active assistance
        else:
            # Unclear response - treat as yes and ask for clarification
            log(f"❓ Unclear response (confidence: {confidence:.3f}), treating as yes and asking for clarification")
            say("I want to make sure I understand correctly. Are you saying you need help with something?")
            current_state = ConversationState.ACTIVE_ASSISTANCE
            
            # Listen for clarification
            reset_audio_devices()  # Reset devices before listening
            audio_data = listen_for_speech(timeout=T_SHORT)
            
            if audio_data is None:
                log("🔇 No clarification received, proceeding with help")
                # Continue to active assistance
            else:
                clarification_text = transcribe_audio_elevenlabs(audio_data)
                if clarification_text:
                    print(f"User clarification: {clarification_text}")
                    clarification_intent, clarification_confidence = detect_yes_no_response(clarification_text, threshold=0.5)
                    
                    if clarification_intent == "no":
                        log(f"👋 User clarified they don't need help (confidence: {clarification_confidence:.3f})")
                        say(prompt_wake())
                        current_state = ConversationState.WAITING_FOR_WAKE_WORD
                        
                        wake_word = wait_for_wake_word()
                        if wake_word == "SOLSTIS":
                            say(prompt_continue_help())
                            skip_opening_message = True
                            continue
                        else:
                            continue
                    elif clarification_intent == "yes":
                        log(f"✅ User clarified they need help (confidence: {clarification_confidence:.3f})")
                        # Continue to active assistance
                    else:
                        log("❓ Still unclear, proceeding with help")
                        # Continue to active assistance
        
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
                # Give user time to respond after Solstis finishes speaking
                # Add extra delay to prevent audio device conflicts
                log("🔊 Waiting for audio device to stabilize after playback...")
                time.sleep(2.5)  # Increased delay to prevent device conflicts
                
                # Clean up any lingering audio processes before listening
                log("🧹 Cleaning up audio processes before listening...")
                cleanup_audio_processes()
                
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
                
                user_text = transcribe_audio_elevenlabs(audio_data)
                if not user_text:
                    log("❌ No transcription received")
                    continue
                
                # Check for background noise or unclear audio transcriptions (parentheses-based detection)
                if user_text.strip().startswith('(') and user_text.strip().endswith(')'):
                    log(f"🔇 Background noise detected in active assistance (parentheses): '{user_text}' - treating as silence")
                    say("I am hearing no response, be sure to say 'SOLSTIS' if you need my assistance!")
                    current_state = ConversationState.WAITING_FOR_WAKE_WORD
                    
                    wake_word = wait_for_wake_word()
                    if wake_word == "SOLSTIS":
                        say(prompt_continue_help())
                        # Don't skip opening message - user didn't actually respond, so replay it
                        skip_opening_message = False
                        break  # Exit active assistance loop
                    else:
                        break
                
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
                        # Keep LEDs lit when step is complete - don't clear them
                        log("💡 Keeping item LEDs lit after step completion")
                        # Continue procedure
                        user_text = "I've completed the step you asked me to do."
                        break  # Back to processing
                    
                    elif wake_word == "SOLSTIS":
                        log("🔊 SOLSTIS wake word detected during step completion")
                        say(prompt_continue_help())
                        reset_audio_devices()  # Reset devices before listening
                        audio_data = listen_for_speech(timeout=T_NORMAL)
                        
                        if audio_data is None:
                            log("🔇 No response after SOLSTIS wake word")
                            continue
                        
                        user_text = transcribe_audio_elevenlabs(audio_data)
                        if not user_text:
                            log("❌ No transcription received")
                            continue
                        
                        print(f"User: {user_text}")
                        break  # Back to processing
                
                continue  # Re-process after step
            
            elif outcome == ResponseOutcome.EMERGENCY_SITUATION:
                # Emergency situation - continue conversation to provide ongoing support
                log("🚨 Emergency situation detected - continuing conversation for support")
                # Continue listening for more input to provide additional guidance
                reset_audio_devices()  # Reset devices before listening
                audio_data = listen_for_speech(timeout=T_NORMAL)
                
                if audio_data is None:
                    log("🔇 No response to emergency guidance, prompting and waiting for wake word")
                    say("I'm here if you need any additional guidance while getting help. Say 'SOLSTIS' if you need me.")
                    current_state = ConversationState.WAITING_FOR_WAKE_WORD
                    
                    wake_word = wait_for_wake_word()
                    if wake_word == "SOLSTIS":
                        say(prompt_continue_help())
                        # Set flag to skip opening message on next iteration
                        skip_opening_message = True
                        break  # Exit active assistance loop
                    else:
                        break
                
                user_text = transcribe_audio_elevenlabs(audio_data)
                if not user_text:
                    log("❌ No transcription received")
                    continue
                
                print(f"User: {user_text}")
                continue  # Re-process with new emergency-related input
            
            elif outcome == ResponseOutcome.PROCEDURE_DONE:
                # Procedure appears complete - ask for user confirmation
                log("✅ Procedure appears complete - asking for user confirmation")
                say("Are you all set with the treatment, or is there anything else you need help with?")
                current_state = ConversationState.ACTIVE_ASSISTANCE  # Stay in active assistance for confirmation
                
                # Listen for user confirmation
                reset_audio_devices()  # Reset devices before listening
                audio_data = listen_for_speech(timeout=T_NORMAL)
                
                if audio_data is None:
                    log("🔇 No response to confirmation, prompting and waiting for wake word")
                    say("I'm here if you need any additional help. Say 'SOLSTIS' if you need me.")
                    current_state = ConversationState.WAITING_FOR_WAKE_WORD
                    
                    wake_word = wait_for_wake_word()
                    if wake_word == "SOLSTIS":
                        say(prompt_continue_help())
                        # Set flag to skip opening message on next iteration
                        skip_opening_message = True
                        break  # Exit active assistance loop
                    else:
                        break
                
                user_text = transcribe_audio_elevenlabs(audio_data)
                if not user_text:
                    log("❌ No transcription received")
                    continue
                
                print(f"User: {user_text}")
                
                # Check if user confirms they're done or needs more help
                user_lower = user_text.lower()
                
                # Check for confirmation that they're done
                if any(phrase in user_lower for phrase in [
                    "yes", "i'm good", "i'm done", "all set", "finished", "that's it", 
                    "no more", "nothing else", "i'm fine", "good to go", "all good"
                ]):
                    log("✅ User confirmed they're done")
                    say(closing_message())
                    current_state = ConversationState.WAITING_FOR_WAKE_WORD
                    
                    # Wait for wake word to restart
                    wake_word = wait_for_wake_word()
                    if wake_word == "SOLSTIS":
                        say(prompt_continue_help())
                        # Set flag to skip opening message on next iteration
                        skip_opening_message = True
                        reset_audio_devices()  # Reset devices before listening
                        audio_data = listen_for_speech(timeout=T_NORMAL)
                        
                        if audio_data is None:
                            log("🔇 No response after procedure completion")
                            continue
                        
                        user_text = transcribe_audio_elevenlabs(audio_data)
                        if not user_text:
                            log("❌ No transcription received")
                            continue
                        
                        print(f"User: {user_text}")
                        break  # Back to main loop for new request
                    else:
                        continue
                
                # Check if user needs more help
                elif any(phrase in user_lower for phrase in [
                    "no", "not yet", "i need", "help me", "more help", "something else",
                    "another", "different", "also", "additionally", "further"
                ]):
                    log("🔄 User needs more help - continuing conversation")
                    say("What else can I help you with? Please describe what you need.")
                    # Continue in active assistance mode to handle the new request
                    continue
                
                # If unclear response, ask for clarification
                else:
                    log("❓ Unclear response - asking for clarification")
                    say("I want to make sure I understand. Are you satisfied with the treatment, or do you need help with something else?")
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
    
    # Initialize LED strip
    if LED_ENABLED:
        init_led_strip()
    
    # Initialize reed switch
    if REED_SWITCH_ENABLED:
        init_reed_switch()
    
    log(f"🩺 Solstis ElevenLabs Voice Assistant starting...")
    log(f"User: {USER_NAME}")
    log(f"Model: {MODEL}")
    log(f"ElevenLabs Voice ID: {ELEVENLABS_VOICE_ID}")
    log(f"ElevenLabs Model ID: {ELEVENLABS_MODEL_ID}")
    log(f"SOLSTIS Wake Word: {SOLSTIS_WAKEWORD_PATH}")
    log(f"STEP COMPLETE Wake Word: {STEP_COMPLETE_WAKEWORD_PATH}")
    log(f"Speech Detection - Cobra VAD: Threshold={COBRA_VAD_THRESHOLD}, Completion threshold={VAD_COMPLETION_THRESHOLD}s")
    log(f"Speech Detection - RMS fallback: {SPEECH_THRESHOLD}, Max duration: {MAX_SPEECH_DURATION}s")
    log(f"Noise Adaptation - Enabled: {NOISE_ADAPTATION_ENABLED}, Multiplier: {NOISE_MULTIPLIER}x, Samples: {NOISE_SAMPLES_COUNT}")
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

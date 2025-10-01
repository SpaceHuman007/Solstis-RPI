#!/usr/bin/env python3
# Solstis Voice Assistant with GPT-based State Detection
# Uses ChatGPT to analyze responses and determine procedure states

import asyncio, base64, json, os, signal, subprocess, sys, threading, time, io, wave, types, audioop, struct, math, tempfile
from datetime import datetime
from dotenv import load_dotenv
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

# Import OpenAI for GPT-based state detection
import openai

# --------- Config via env ---------
# Picovoice config
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "YOUR-PICOVOICE-ACCESSKEY-HERE")
SOLSTIS_WAKEWORD_PATH = os.getenv("SOLSTIS_WAKEWORD_PATH", "Solstice_en_raspberry-pi_v3_0_0.ppn")
STEP_COMPLETE_WAKEWORD_PATH = os.getenv("STEP_COMPLETE_WAKEWORD_PATH", "step-complete_en_raspberry-pi_v3_0_0.ppn")
MIC_DEVICE = os.getenv("MIC_DEVICE", "plughw:3,0")
MIC_SR = int(os.getenv("MIC_SR", "16000"))

# ElevenLabs config
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
if not ELEVENLABS_API_KEY:
    print("Missing ELEVENLABS_API_KEY", file=sys.stderr); sys.exit(1)

ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

# OpenAI config
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("Missing OPENAI_API_KEY", file=sys.stderr); sys.exit(1)

MODEL = os.getenv("MODEL", "gpt-4-turbo")

# Audio output config
OUT_DEVICE = os.getenv("AUDIO_DEVICE")
OUT_SR = int(os.getenv("OUT_SR", "24000"))
USER_NAME = os.getenv("USER_NAME", "User")

# GPT State Detection config
GPT_STATE_DETECTION_ENABLED = os.getenv("GPT_STATE_DETECTION_ENABLED", "true").lower() == "true"
GPT_STATE_MODEL = os.getenv("GPT_STATE_MODEL", "gpt-4o-mini")  # Use faster model for state detection
GPT_STATE_TEMPERATURE = float(os.getenv("GPT_STATE_TEMPERATURE", "0.1"))  # Low temperature for consistent results

# Speech detection config
SPEECH_THRESHOLD = int(os.getenv("SPEECH_THRESHOLD", "500"))
SILENCE_DURATION = float(os.getenv("SILENCE_DURATION", "2.0"))
QUICK_SILENCE_AFTER_SPEECH = float(os.getenv("QUICK_SILENCE_AFTER_SPEECH", "0.8"))
MIN_SPEECH_DURATION = float(os.getenv("MIN_SPEECH_DURATION", "3.0"))
MAX_SPEECH_DURATION = float(os.getenv("MAX_SPEECH_DURATION", "15.0"))

# Timeout configurations
T_SHORT = float(os.getenv("T_SHORT", "30.0"))
T_NORMAL = float(os.getenv("T_NORMAL", "10.0"))
T_LONG = float(os.getenv("T_LONG", "15.0"))

# LED Control config
LED_ENABLED = os.getenv("LED_ENABLED", "true").lower() == "true" and LED_CONTROL_AVAILABLE
LED_COUNT = int(os.getenv("LED_COUNT", "788"))
LED_PIN = int(os.getenv("LED_PIN", "13"))
LED_FREQ_HZ = int(os.getenv("LED_FREQ_HZ", "800000"))
LED_DMA = int(os.getenv("LED_DMA", "10"))
LED_BRIGHTNESS = int(os.getenv("LED_BRIGHTNESS", "70"))
LED_INVERT = os.getenv("LED_INVERT", "false").lower() == "true"
LED_CHANNEL = int(os.getenv("LED_CHANNEL", "1"))

# Reed switch config
REED_SWITCH_ENABLED = os.getenv("REED_SWITCH_ENABLED", "true").lower() == "true" and GPIO_AVAILABLE
REED_SWITCH_PIN = int(os.getenv("REED_SWITCH_PIN", "16"))
REED_SWITCH_DEBOUNCE_MS = int(os.getenv("REED_SWITCH_DEBOUNCE_MS", "500"))
REED_SWITCH_CONFIRM_COUNT = int(os.getenv("REED_SWITCH_CONFIRM_COUNT", "5"))
REED_SWITCH_POLL_INTERVAL = float(os.getenv("REED_SWITCH_POLL_INTERVAL", "0.2"))

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
current_lit_items = []

# Reed switch state variables
box_is_open = False
reed_switch_initialized = False

# ---------- GPT-based State Detection ----------
def get_gpt_state_detection_prompt():
    """Generate the system prompt for GPT-based state detection"""
    return """You are an expert at analyzing medical assistant responses to determine the current procedure state.

Your task is to analyze a medical assistant's response and determine what the next step should be in the conversation flow.

RESPONSE OUTCOMES:
1. NEED_MORE_INFO - The assistant is asking for more information/clarification
2. USER_ACTION_REQUIRED - The assistant is asking the user to perform a physical action
3. PROCEDURE_DONE - The assistant is indicating the procedure is complete
4. EMERGENCY_SITUATION - The assistant is recommending emergency care

ANALYSIS GUIDELINES:
- Look for clear indicators of what the assistant is asking the user to do
- Consider the context and intent, not just keywords
- If asking for more details about injury/symptoms → NEED_MORE_INFO
- If asking user to apply/use/place medical items → USER_ACTION_REQUIRED  
- If indicating treatment is finished/complete → PROCEDURE_DONE
- If recommending emergency care/911 → EMERGENCY_SITUATION

RESPONSE FORMAT:
Return ONLY a JSON object with this exact structure:
{
    "outcome": "one_of_the_four_outcomes_above",
    "confidence": 0.0_to_1.0,
    "reasoning": "brief_explanation_of_why_you_chose_this_outcome"
}

Examples:
- "Where exactly is the cut?" → {"outcome": "NEED_MORE_INFO", "confidence": 0.95, "reasoning": "Asking for location details"}
- "Apply the bandage and let me know when done" → {"outcome": "USER_ACTION_REQUIRED", "confidence": 0.9, "reasoning": "Clear instruction to perform action"}
- "The procedure is complete and you should be fine" → {"outcome": "PROCEDURE_DONE", "confidence": 0.95, "reasoning": "Explicit completion statement"}
- "Call 911 immediately" → {"outcome": "EMERGENCY_SITUATION", "confidence": 0.98, "reasoning": "Emergency care instruction"}"""

def analyze_response_with_gpt(response_text, conversation_history=None):
    """Use GPT to analyze response and determine procedure state"""
    if not GPT_STATE_DETECTION_ENABLED:
        return None, 0.0, "GPT state detection disabled"
    
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        
        # Prepare context from conversation history
        context = ""
        if conversation_history and len(conversation_history) > 0:
            recent_messages = conversation_history[-6:] if len(conversation_history) >= 6 else conversation_history
            context = "RECENT CONVERSATION CONTEXT:\n"
            for msg in recent_messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                context += f"{role.upper()}: {content}\n"
            context += "\n"
        
        # Prepare the analysis request
        messages = [
            {"role": "system", "content": get_gpt_state_detection_prompt()},
            {"role": "user", "content": f"{context}MEDICAL ASSISTANT RESPONSE TO ANALYZE:\n{response_text}"}
        ]
        
        log(f"🤖 GPT State Detection: Analyzing response")
        
        # Call GPT for state detection
        response = client.chat.completions.create(
            model=GPT_STATE_MODEL,
            messages=messages,
            max_tokens=200,
            temperature=GPT_STATE_TEMPERATURE
        )
        
        gpt_response = response.choices[0].message.content.strip()
        log(f"🤖 GPT Response: {gpt_response}")
        
        # Parse the JSON response
        try:
            result = json.loads(gpt_response)
            outcome = result.get("outcome", "").upper()
            confidence = float(result.get("confidence", 0.0))
            reasoning = result.get("reasoning", "No reasoning provided")
            
            # Map GPT outcome to our enum
            outcome_mapping = {
                "NEED_MORE_INFO": ResponseOutcome.NEED_MORE_INFO,
                "USER_ACTION_REQUIRED": ResponseOutcome.USER_ACTION_REQUIRED,
                "PROCEDURE_DONE": ResponseOutcome.PROCEDURE_DONE,
                "EMERGENCY_SITUATION": ResponseOutcome.EMERGENCY_SITUATION
            }
            
            mapped_outcome = outcome_mapping.get(outcome)
            if mapped_outcome:
                log(f"🤖 GPT Analysis: {mapped_outcome} (confidence: {confidence:.3f}) - {reasoning}")
                return mapped_outcome, confidence, reasoning
            else:
                log(f"🤖 GPT Error: Unknown outcome '{outcome}'")
                return None, 0.0, f"Unknown outcome: {outcome}"
                
        except json.JSONDecodeError as e:
            log(f"🤖 GPT Error: Failed to parse JSON response: {e}")
            log(f"🤖 GPT Raw Response: {gpt_response}")
            return None, 0.0, f"JSON parse error: {e}"
            
    except Exception as e:
        log(f"🤖 GPT Error: {e}")
        return None, 0.0, f"GPT analysis error: {e}"

def process_response(user_text, conversation_history=None):
    """Process user response using GPT-based state detection"""
    try:
        import openai
        
        # Initialize OpenAI client
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        
        # Prepare messages for main conversation
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
            temperature=0.5
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Update conversation history
        conversation_history.append({"role": "user", "content": user_text})
        conversation_history.append({"role": "assistant", "content": response_text})
        
        # Keep conversation history manageable
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]
        
        # Use GPT for state detection
        outcome, confidence, reasoning = analyze_response_with_gpt(response_text, conversation_history)
        
        if outcome is not None:
            log(f"🤖 GPT State Detection Result: {outcome} (confidence: {confidence:.3f})")
            log(f"🤖 Reasoning: {reasoning}")
            return outcome, response_text
        else:
            # Fallback to simple keyword analysis if GPT fails
            log("🤖 GPT analysis failed, using fallback keyword analysis")
            return fallback_keyword_analysis(response_text)
            
    except Exception as e:
        log(f"Error processing response: {e}")
        return ResponseOutcome.NEED_MORE_INFO, "I'm sorry, I'm having trouble processing your request right now."

def fallback_keyword_analysis(response_text):
    """Simple fallback keyword analysis if GPT fails"""
    response_lower = response_text.lower()
    
    # Check for user action required
    if any(phrase in response_lower for phrase in [
        "let me know when", "when you're done", "apply", "use", "place", "put on"
    ]):
        return ResponseOutcome.USER_ACTION_REQUIRED, response_text
    
    # Check for procedure done
    if any(phrase in response_lower for phrase in [
        "procedure is complete", "treatment is done", "you're all set", "all done"
    ]):
        return ResponseOutcome.PROCEDURE_DONE, response_text
    
    # Check for emergency
    if any(phrase in response_lower for phrase in [
        "call 9-1-1", "emergency room", "immediate medical attention"
    ]):
        return ResponseOutcome.EMERGENCY_SITUATION, response_text
    
    # Default to need more info
    return ResponseOutcome.NEED_MORE_INFO, response_text

def get_system_prompt():
    """Generate the system prompt for the medical assistant"""
    kit_contents = [
        "Band-Aids", "4\" x 4\" Gauze Pads", "2\" Roll Gauze", "5\" x 9\" ABD Pad",
        "Cloth Medical Tape", "Triple Antibiotic Ointment", "Tweezers", "Trauma Shears",
        "QuickClot Gauze", "Burn Gel Dressing", "Burn Spray", "Sting & Bite Relief Wipes",
        "Mini Eye Wash Bottle", "Oral Glucose Gel", "Electrolyte Powder Pack",
        "Elastic Ace Bandage", "Instant Cold Pack", "Triangle Bandage"
    ]
    
    contents_str = ", ".join(kit_contents)
    
    return f"""Always speak in English (US). You are Solstis, a calm and supportive AI medical assistant. You help users with first aid using only the items available in their specific kit.

CRITICAL BEHAVIOR: Your primary role is to ASK QUESTIONS and gather information before providing any treatment. Always err on the side of asking for more details rather than making assumptions about the user's situation.

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

# Import LED and audio functions from the main file
# (These would be copied from solstis_elevenlabs_flow.py)
# For brevity, I'm including just the essential functions

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

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
        args += ["-D", "default"]
    
    log(f"🔊 Spawn Command: {' '.join(args)}")
    
    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        log(f"🔊 Spawn Success: aplay process created with PID {process.pid}")
        return process
    except Exception as e:
        log(f"🔊 Spawn Error: Failed to create aplay process: {e}")
        raise

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

def transcribe_audio(audio_data):
    """Transcribe audio using ElevenLabs STT API"""
    try:
        log("🎤 ElevenLabs STT: Starting transcription")
        
        # Create a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            # Convert PCM16 to WAV format
            with wave.open(temp_file.name, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(OUT_SR)
                wav_file.writeframes(audio_data)
            
            # Read the WAV file and send to ElevenLabs STT
            with open(temp_file.name, 'rb') as audio_file:
                audio_content = audio_file.read()
            
            # Clean up temp file
            os.unlink(temp_file.name)
        
        # Send to ElevenLabs STT API
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "audio/wav"
        }
        
        response = requests.post(url, headers=headers, data=audio_content)
        
        if response.status_code == 200:
            result = response.json()
            transcript = result.get("text", "").strip()
            log(f"🎤 ElevenLabs STT Success: '{transcript}'")
            return transcript
        else:
            log(f"🎤 ElevenLabs STT Error: {response.status_code} - {response.text}")
            return ""
    
    except Exception as e:
        log(f"🎤 ElevenLabs STT Error: {e}")
        return ""

def text_to_speech(text):
    """Convert text to speech using ElevenLabs TTS API"""
    try:
        log(f"🎤 ElevenLabs TTS Request: '{text[:50]}{'...' if len(text) > 50 else ''}'")
        log(f"🎤 ElevenLabs TTS Config: voice_id={ELEVENLABS_VOICE_ID}, model_id={ELEVENLABS_MODEL_ID}")
        
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        data = {
            "text": text,
            "model_id": ELEVENLABS_MODEL_ID,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5
            }
        }
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            audio_size = len(response.content)
            log(f"🎤 ElevenLabs TTS Success: Generated {audio_size} bytes of audio data")
            return response.content
        else:
            log(f"🎤 ElevenLabs TTS Error: {response.status_code} - {response.text}")
            return b""
    
    except Exception as e:
        log(f"🎤 ElevenLabs TTS Error: {e}")
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
                return_code = aplay.wait(timeout=10)  # 10 second timeout for PCM
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
    """Convert text to speech and play it using ElevenLabs"""
    log(f"🗣️  Speaking: {text}")
    audio_data = text_to_speech(text)
    if audio_data:
        play_audio(audio_data)
    print(f"Solstis: {text}")

def opening_message():
    """Send the opening message"""
    message = f"Hey {USER_NAME}. I'm SOLSTIS and I'm here to help. If this is a life-threatening emergency, please call 9-1-1 now. Otherwise, is there something I can help you with?"
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

def closing_message():
    """Send the closing message"""
    message = f"If you need any further help, please let me know by saying '{WAKE_WORD_SOLSTIS}'."
    return message

# Main conversation flow (simplified version)
def handle_conversation():
    """Main conversation handler with GPT-based state detection"""
    global current_state, conversation_history
    
    log("🎯 Starting GPT-based conversation flow")
    
    # Main interaction loop
    while True:
        # Opening message
        log("📢 Sending opening message")
        say(opening_message())
        current_state = ConversationState.OPENING
        
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
                    continue
                else:
                    continue
        
        # Transcribe the response using ElevenLabs STT
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
            continue
        
        # Enter active assistance loop
        current_state = ConversationState.ACTIVE_ASSISTANCE
        log("🩺 Entering active assistance mode")
        
        while True:
            # Process the user's response using GPT state detection
            outcome, response_text = process_response(user_text, conversation_history)
            
            # Speak the response
            say(response_text)
            
            if outcome == ResponseOutcome.NEED_MORE_INFO:
                log("📝 Need more info, continuing to listen")
                audio_data = listen_for_speech(timeout=T_NORMAL)
                if audio_data is None:
                    log("🔇 No response to follow-up, prompting and waiting for wake word")
                    say(prompt_no_response())
                    current_state = ConversationState.WAITING_FOR_WAKE_WORD
                    
                    wake_word = wait_for_wake_word()
                    if wake_word == "SOLSTIS":
                        say(prompt_continue_help())
                        break
                    else:
                        break
                
                user_text = transcribe_audio(audio_data)
                if not user_text:
                    log("❌ No transcription received")
                    continue
                
                print(f"User: {user_text}")
                continue
            
            elif outcome == ResponseOutcome.USER_ACTION_REQUIRED:
                log("⏳ User action required, waiting for step completion")
                current_state = ConversationState.WAITING_FOR_STEP_COMPLETE
                say(prompt_step_complete())
                
                # Wait for step complete wake word
                log("Waiting for step complete...")
                wake_word = wait_for_wake_word()
                if wake_word == "STEP_COMPLETE":
                    log("✅ Step complete detected, continuing procedure")
                    user_text = "I've completed the step you asked me to do."
                    continue
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
                    continue
            
            elif outcome == ResponseOutcome.EMERGENCY_SITUATION:
                log("🚨 Emergency situation detected - continuing conversation for support")
                audio_data = listen_for_speech(timeout=T_NORMAL)
                
                if audio_data is None:
                    log("🔇 No response to emergency guidance, prompting and waiting for wake word")
                    say("I'm here if you need any additional guidance while getting help. Say 'SOLSTIS' if you need me.")
                    current_state = ConversationState.WAITING_FOR_WAKE_WORD
                    
                    wake_word = wait_for_wake_word()
                    if wake_word == "SOLSTIS":
                        say(prompt_continue_help())
                        break
                    else:
                        break
                
                user_text = transcribe_audio(audio_data)
                if not user_text:
                    log("❌ No transcription received")
                    continue
                
                print(f"User: {user_text}")
                continue
            
            elif outcome == ResponseOutcome.PROCEDURE_DONE:
                log("✅ Procedure completed")
                say(closing_message())
                current_state = ConversationState.WAITING_FOR_WAKE_WORD
                
                # Wait for wake word to restart
                wake_word = wait_for_wake_word()
                if wake_word == "SOLSTIS":
                    say(prompt_continue_help())
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
    """Kill any existing audio processes that might be holding the devices."""
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
            return
        
        # Normal blocking cleanup
        subprocess.run(["pkill", "-9", "-f", "arecord"], check=False, capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "aplay"], check=False, capture_output=True)
        time.sleep(1.0)
        log("🧹 Cleaned up existing audio processes")
    except Exception as e:
        log(f"Warning: Could not cleanup audio processes: {e}")

def signal_handler(signum, frame):
    """Handle shutdown quickly and non-blocking to avoid deadlocks on Ctrl+C."""
    try:
        log("Shutdown signal received, cleaning up...")
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
    
    log(f"🩺 Solstis GPT State Detection Voice Assistant starting...")
    log(f"User: {USER_NAME}")
    log(f"Model: {MODEL}")
    log(f"GPT State Detection: {'Enabled' if GPT_STATE_DETECTION_ENABLED else 'Disabled'}")
    log(f"GPT State Model: {GPT_STATE_MODEL}")
    log(f"ElevenLabs Voice ID: {ELEVENLABS_VOICE_ID}")
    log(f"ElevenLabs Model ID: {ELEVENLABS_MODEL_ID}")
    log(f"Audio Input: {MIC_DEVICE}")
    log(f"Audio Output: {OUT_DEVICE or 'default'}")
    
    try:
        # Start the conversation flow
        await asyncio.to_thread(handle_conversation)
    except Exception as e:
        log(f"Error in main: {e}")
    finally:
        # Cleanup
        cleanup_audio_processes()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Shutdown complete.")
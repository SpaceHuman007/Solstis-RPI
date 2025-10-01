#!/usr/bin/env python3
# Solstis Voice Assistant with GPT-based State Detection Integration
# Adds GPT state detection to the existing ElevenLabs flow

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
GPT_STATE_MODEL = os.getenv("GPT_STATE_MODEL", "gpt-4o-mini")
GPT_STATE_TEMPERATURE = float(os.getenv("GPT_STATE_TEMPERATURE", "0.1"))
GPT_STATE_CONFIDENCE_THRESHOLD = float(os.getenv("GPT_STATE_CONFIDENCE_THRESHOLD", "0.7"))

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
    """Process user response using GPT-based state detection with fallback"""
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
        
        if outcome is not None and confidence >= GPT_STATE_CONFIDENCE_THRESHOLD:
            log(f"🤖 GPT State Detection Result: {outcome} (confidence: {confidence:.3f})")
            log(f"🤖 Reasoning: {reasoning}")
            return outcome, response_text
        else:
            # Fallback to enhanced keyword analysis if GPT fails or low confidence
            log(f"🤖 GPT analysis failed or low confidence ({confidence:.3f}), using fallback")
            return fallback_enhanced_analysis(response_text, conversation_history)
            
    except Exception as e:
        log(f"Error processing response: {e}")
        return ResponseOutcome.NEED_MORE_INFO, "I'm sorry, I'm having trouble processing your request right now."

def fallback_enhanced_analysis(response_text, conversation_history=None):
    """Enhanced fallback analysis combining multiple approaches"""
    response_lower = response_text.lower()
    
    # Weighted keyword analysis
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
        "healthcare professional": 0.7, "see a doctor": 0.7, "medical attention": 0.7
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
    
    log(f"🔍 Fallback Analysis:")
    log(f"   User Action: {user_action_score:.3f} ({ua_matches} matches)")
    log(f"   Procedure Done: {procedure_done_score:.3f} ({pd_matches} matches)")
    log(f"   Need More Info: {need_more_info_score:.3f} ({nmi_matches} matches)")
    log(f"   Emergency: {emergency_score:.3f} ({em_matches} matches)")
    log(f"   Best: {best_outcome} (confidence: {best_score:.3f})")
    
    return best_outcome, response_text

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

AVAILABLE ITEMS IN YOUR KIT:
{contents_str}

Your role:
• Be a real-time guide—natural, concise, supportive  
• HEAVILY PRIORITIZE asking clarifying questions to fully understand the user's situation before providing any treatment
• Always ask for specific details about the injury/symptom before recommending any treatment
• Assess for life-threatening danger but don't overreact to common symptoms
• Give clear, step-by-step instructions for self-treatment ONLY after gathering sufficient information
• Select only from the current kit (or common home items)  
• Always use the EXACT item names from the kit contents list above
• Only recommend calling 9-1-1 for TRUE emergencies (unconsciousness, severe bleeding, chest pain, etc.)
• Encourage follow-up care when appropriate (e.g., "you may need stitches")
• Maintain conversation flow without repeating opening messages
• Focus on the current medical situation and immediate next steps

IMPORTANT STYLE & FLOW:
- Keep responses to 1-2 short sentences
- Ask one clear follow-up question at a time
- Use plain language; avoid medical jargon
- Acknowledge progress briefly ("Great," "Well done")
- Track progress, user replies, and items used
- Only refer to items in this kit or common home items
- End action steps with "Let me know when you're ready" or "Let me know when done" when appropriate
- Focus on the current situation and next steps

CRITICAL SINGLE-STEP RULE:
- Give ONLY ONE medical item instruction per response
- NEVER mention multiple medical items in the same response
- If multiple steps are needed, give them one at a time and wait for user confirmation"""

# Import essential functions from the main file
# (In a real implementation, you would import these from solstis_elevenlabs_flow.py)

def say(text):
    """Convert text to speech and play it using ElevenLabs"""
    log(f"🗣️  Speaking: {text}")
    # Audio implementation would go here - copy from main file
    print(f"Solstis: {text}")

def opening_message():
    """Send the opening message"""
    message = f"Hey {USER_NAME}. I'm SOLSTIS and I'm here to help. If this is a life-threatening emergency, please call 9-1-1 now. Otherwise, is there something I can help you with?"
    return message

def prompt_wake():
    """Prompt user to use wake word"""
    message = f"OK, if you need me for any help, say {WAKE_WORD_SOLSTIS} to wake me up."
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

# Main conversation flow (simplified - would integrate with full audio system)
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
        
        # Listen for initial response (simplified - would use actual audio capture)
        log("👂 Listening for initial response")
        # user_text = listen_for_speech(timeout=T_SHORT)  # Would be actual audio capture
        user_text = input("User: ")  # Simplified for demo
        
        if not user_text:
            log("🔇 No response, prompting and waiting for wake word")
            say(prompt_wake())
            current_state = ConversationState.WAITING_FOR_WAKE_WORD
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
                # user_text = listen_for_speech(timeout=T_NORMAL)  # Would be actual audio capture
                user_text = input("User: ")  # Simplified for demo
                if not user_text:
                    log("🔇 No response to follow-up")
                    break
                print(f"User: {user_text}")
                continue
            
            elif outcome == ResponseOutcome.USER_ACTION_REQUIRED:
                log("⏳ User action required, waiting for step completion")
                current_state = ConversationState.WAITING_FOR_STEP_COMPLETE
                say(prompt_step_complete())
                
                # Wait for step complete wake word (simplified)
                log("Waiting for step complete...")
                # wake_word = wait_for_wake_word()  # Would be actual wake word detection
                user_input = input("Say 'STEP COMPLETE' when done: ")
                if "step complete" in user_input.lower():
                    log("✅ Step complete detected, continuing procedure")
                    user_text = "I've completed the step you asked me to do."
                    continue
                else:
                    user_text = user_input
                    continue
            
            elif outcome == ResponseOutcome.EMERGENCY_SITUATION:
                log("🚨 Emergency situation detected - continuing conversation for support")
                # user_text = listen_for_speech(timeout=T_NORMAL)  # Would be actual audio capture
                user_text = input("User: ")  # Simplified for demo
                if not user_text:
                    log("🔇 No response to emergency guidance")
                    break
                print(f"User: {user_text}")
                continue
            
            elif outcome == ResponseOutcome.PROCEDURE_DONE:
                log("✅ Procedure completed")
                say(closing_message())
                current_state = ConversationState.WAITING_FOR_WAKE_WORD
                break

async def main():
    """Main entry point"""
    global current_state
    
    log(f"🩺 Solstis GPT State Detection Voice Assistant starting...")
    log(f"User: {USER_NAME}")
    log(f"Model: {MODEL}")
    log(f"GPT State Detection: {'Enabled' if GPT_STATE_DETECTION_ENABLED else 'Disabled'}")
    log(f"GPT State Model: {GPT_STATE_MODEL}")
    log(f"GPT Confidence Threshold: {GPT_STATE_CONFIDENCE_THRESHOLD}")
    
    try:
        # Start the conversation flow
        await asyncio.to_thread(handle_conversation)
    except Exception as e:
        log(f"Error in main: {e}")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Shutdown complete.")

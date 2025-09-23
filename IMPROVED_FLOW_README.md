# Solstis Improved Conversation Flow

## Overview

The new `solstis_improved_flow.py` implements a structured conversation flow with dual wake word support and proper state management, following the pseudo code specification provided.

## Key Features

### 1. Dual Wake Word System
- **SOLSTIS**: General wake word for starting conversations or getting help
- **STEP COMPLETE**: Specific wake word for indicating task completion during procedures

### 2. Conversation States
- `OPENING`: Initial greeting and setup
- `ACTIVE_ASSISTANCE`: Active medical assistance mode
- `WAITING_FOR_STEP_COMPLETE`: Waiting for user to complete a task
- `WAITING_FOR_WAKE_WORD`: Passive mode waiting for wake word

### 3. Response Outcomes
- `NEED_MORE_INFO`: AI needs additional information to proceed
- `USER_ACTION_REQUIRED`: User needs to perform a physical action
- `PROCEDURE_DONE`: Medical procedure is complete

### 4. Timeout Management
- `T_SHORT` (5s): Initial response timeout
- `T_NORMAL` (10s): Normal conversation timeout
- `T_LONG` (15s): Step completion timeout

## Flow Implementation

### Main Conversation Loop

1. **Opening Message**
   ```
   "Hey USER. I'm SOLSTIS and I'm here to help. If this is a life-threatening emergency, please call 9-1-1 now. Otherwise, is there something I can help you with?"
   ```

2. **Response Handling**
   - **User says YES**: Enter active assistance mode
   - **User says NO**: Prompt for wake word and wait
   - **No Response**: Retry opening message, then prompt for wake word

3. **Active Assistance Loop**
   - Process user input with AI
   - Determine outcome (NEED_MORE_INFO, USER_ACTION_REQUIRED, PROCEDURE_DONE)
   - Handle each outcome appropriately

### Outcome Handling

#### NEED_MORE_INFO
- Continue listening automatically
- Process additional information
- Loop back to response processing

#### USER_ACTION_REQUIRED
- Provide step instructions
- Say "Say 'STEP COMPLETE' when you're done"
- Wait for either:
  - "STEP COMPLETE" wake word → Continue procedure
  - "SOLSTIS" wake word → New assistance request
  - Silence → Prompt and wait for wake word

#### PROCEDURE_DONE
- Send closing message
- Wait for "SOLSTIS" wake word to restart
- Return to main conversation loop

## Configuration

### Environment Variables
```bash
# Wake Word Paths
SOLSTIS_WAKEWORD_PATH="Solstice_en_raspberry-pi_v3_0_0.ppn"
STEP_COMPLETE_WAKEWORD_PATH="step-complete_en_raspberry-pi_v3_0_0.ppn"

# Timeouts
T_SHORT=5.0
T_NORMAL=10.0
T_LONG=15.0

# Other existing variables remain the same
```

## Usage

```bash
python3 solstis_improved_flow.py
```

## Key Improvements Over Original

1. **Structured State Management**: Clear conversation states prevent confusion
2. **Dual Wake Word Support**: Separate wake words for different contexts
3. **Proper Timeout Handling**: Different timeouts for different scenarios
4. **Better Error Recovery**: Graceful handling of no response scenarios
5. **Clear Flow Control**: Explicit loops and state transitions
6. **Enhanced Logging**: Detailed logging for debugging and monitoring

## Integration

The new flow maintains compatibility with:
- Existing Picovoice wake word detection
- OpenAI GPT-4 and TTS integration
- LED control system
- Medical kit keyword detection
- Audio processing pipeline

## Testing

To test the new flow:
1. Ensure both wake word files are present
2. Set up environment variables
3. Run the script
4. Test different conversation scenarios:
   - Normal medical assistance
   - Step completion workflow
   - Wake word interruptions
   - No response scenarios

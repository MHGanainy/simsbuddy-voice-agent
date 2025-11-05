import asyncio
import json
import os
import sys
import signal
import argparse
import math
import time
from datetime import datetime

from dotenv import load_dotenv
import aiohttp
import redis
import requests

# Import structured logging
from backend.common.logging_config import setup_logging, LogContext
# Import database service for transcript storage
from backend.common.services import Database

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    InterruptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.transcript_processor import TranscriptProcessor
from pipecat.runner.livekit import configure
from pipecat.services.inworld.tts import InworldTTSService
from pipecat.services.assemblyai.stt import AssemblyAISTTService, AssemblyAIConnectionParams
from pipecat.services.groq.llm import GroqLLMService
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport

load_dotenv(override=True)

# Setup logging
logger = setup_logging(service_name='voice-agent')

# ==================== AGENT CONFIGURATION ====================
# Adjust these parameters to tune the voice agent behavior

# Timing Configuration (Development Only)
ENABLE_TIMING = os.getenv('LOG_LEVEL', 'INFO').upper() == 'DEBUG'
PARTICIPANT_GREETING_DELAY = 0.2  # Seconds to wait before greeting (reduced from 1.0)

# Context Aggregator Settings
AGGREGATION_TIMEOUT = 0.2  # How long to wait for complete responses
BOT_INTERRUPTION_TIMEOUT = 0.2  # How quickly bot can be interrupted

# TTS Configuration (Inworld)
TTS_STREAMING = True
TTS_TEMPERATURE = 1.1  # Voice expressiveness (0.0-2.0)
TTS_DEFAULT_SPEED = 1.0  # Default speech rate

# Voice-specific speed overrides
VOICE_SPEED_OVERRIDES = {
    "Craig": 1.2,    # Male, faster
    "Edward": 1.0,   # Male, normal
    "Olivia": 1.0,   # Female, normal
    "Wendy": 1.2,    # Female, faster
    "Priya": 1.0,    # Asian accent Female, normal
    "Ashley": 1.0,   # Default voice
}

# STT Configuration (AssemblyAI)
STT_SAMPLE_RATE = 16000
STT_ENCODING = "pcm_s16le"
STT_MODEL = "universal-streaming"
STT_FORMAT_TURNS = False
STT_END_OF_TURN_CONFIDENCE = 0.70
STT_MIN_SILENCE_CONFIDENT = 50  # milliseconds
STT_MAX_TURN_SILENCE = 200  # milliseconds
STT_ENABLE_PARTIALS = True
STT_IMMUTABLE_FINALS = True
STT_PUNCTUATE = False
STT_FORMAT_TEXT = False
STT_VAD_FORCE_ENDPOINT = True
STT_LANGUAGE = "en"

# LLM Configuration (Groq)
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_STREAM = True  # Enable streaming for lower latency
LLM_MAX_TOKENS = 100
LLM_TEMPERATURE = 0.6
LLM_TOP_P = 0.8
LLM_PRESENCE_PENALTY = 0.15
LLM_FREQUENCY_PENALTY = 0.30

# Critical Rules (appended to all system prompts - STATIC)
CRITICAL_RULES = """
CRITICAL RULES:
You are roleplaying. Everything you write will be spoken aloud by a text-to-speech system, so follow these rules strictly:

Keep answers short and only answer when asked about a specific point; do not provide unrequested information.

NEVER include:
- Stage directions like "looks anxious," "appears worried," "seems uncomfortable"
- Actions in asterisks like *sighs*, *pauses*, *fidgets*
- Any descriptive text about body language or appearance
- Brackets except for the emotion tags below

ONLY output accepted:
- Actual spoken words the actor would say
- Occasional use of Emotion tags at the START of sentences (when needed): [happy], [sad], [angry], [surprised], [fearful], [disgusted]
- No other emotional tags are supported or allowed to use such as [anxious]. PLEASE DO NOT USE UNSUPPORTED TAGS at any circumstances.

Speaking style:
- Keep responses short and conversational (1-2 sentences max)
- Only answer what is specifically asked
- Don't volunteer extra information unless it's asked specifically about it (Keep information you have until it is asked)
- Speak like a real person, not like you're describing a scene.
""".strip()

# ==================== END CONFIGURATION ====================

# ==================== ENVIRONMENT VALIDATION ====================
def validate_environment():
    """Validate that all required environment variables are set."""
    required_vars = {
        'ASSEMBLY_API_KEY': 'AssemblyAI API key for speech-to-text',
        'GROQ_API_KEY': 'Groq API key for LLM',
        'INWORLD_API_KEY': 'Inworld API key for text-to-speech',
    }

    missing = []
    for var, description in required_vars.items():
        if not os.getenv(var):
            missing.append(f"  - {var}: {description}")

    if missing:
        logger.error("environment_validation_failed",
                    missing_variables=missing,
                    message="Please check your .env file",
                    exc_info=True)
        sys.exit(1)

    logger.info("environment_validated")

validate_environment()


def log_timing(message: str, **kwargs):
    """Log timing information only in development mode"""
    if ENABLE_TIMING:
        logger.debug(f"TIMING: {message}", **kwargs)


class TranscriptStorage:
    """Collects transcripts from Pipecat processor for database persistence"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.transcripts = []
        logger.info(f"TranscriptStorage initialized for session {session_id[:20]}...")

    def add_message(self, role: str, content: str, timestamp: str = None):
        """Add a transcript message"""
        if timestamp is None:
            timestamp = datetime.utcnow().isoformat()

        self.transcripts.append({
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "sequence": len(self.transcripts)
        })
        logger.debug(f"Captured {role} message #{len(self.transcripts)} for {self.session_id[:20]}...")

    def get_transcript_data(self):
        """Get formatted transcript data for database storage"""
        return self.transcripts

    def __len__(self):
        """Return the number of transcript entries"""
        return len(self.transcripts)


async def heartbeat_task(session_id: str, transport=None, transcript_storage=None):
    """
    Send heartbeat to orchestrator every minute for credit billing.

    Args:
        session_id: The session/room name
        transport: LiveKit transport (optional, for graceful shutdown)
        transcript_storage: Transcript storage (optional, for saving before shutdown)
    """
    await asyncio.sleep(60)  # Wait for first minute to complete

    while True:
        try:
            logger.info("heartbeat_sending", session_id=session_id)

            # Get orchestrator URL from environment
            orchestrator_url = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")

            # Send heartbeat (synchronous request in async context)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    f"{orchestrator_url}/api/session/heartbeat",
                    json={"sessionId": session_id},
                    timeout=10
                )
            )

            result = response.json()

            if result.get("status") == "stop":
                logger.warning(
                    "heartbeat_stop_received",
                    session_id=session_id,
                    reason=result.get("reason", "insufficient_credits"),
                    message=result.get("message")
                )

                # Save transcript before stopping
                if transcript_storage and len(transcript_storage) > 0:
                    try:
                        logger.info("heartbeat_saving_transcript_before_stop",
                                   session_id=session_id,
                                   transcript_count=len(transcript_storage))

                        transcript_data = transcript_storage.get_transcript_data()
                        success = await Database.save_transcript(session_id, transcript_data)

                        if success:
                            logger.info("heartbeat_transcript_saved",
                                       session_id=session_id,
                                       transcript_count=len(transcript_data))
                        else:
                            logger.error("heartbeat_transcript_save_failed",
                                        session_id=session_id)
                    except Exception as save_error:
                        logger.error("heartbeat_transcript_save_error",
                                    session_id=session_id,
                                    error=str(save_error))

                # Close transport if available
                if transport:
                    try:
                        await transport.close()
                        logger.info("heartbeat_transport_closed", session_id=session_id)
                    except Exception as close_error:
                        logger.error("heartbeat_transport_close_error",
                                    error=str(close_error))

                # Exit the process (graceful shutdown)
                logger.info("heartbeat_exiting_due_to_insufficient_credits",
                           session_id=session_id)
                sys.exit(0)

            elif result.get("status") == "ok":
                logger.info(
                    "heartbeat_success",
                    session_id=session_id,
                    minute_billed=result.get("minute_billed"),
                    credits_remaining=result.get("credits_remaining"),
                    already_billed=result.get("already_billed", False)
                )
            else:
                logger.error(
                    "heartbeat_error",
                    session_id=session_id,
                    error=result.get("message")
                )

            # Wait 60 seconds before next heartbeat
            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("heartbeat_cancelled", session_id=session_id)
            break
        except Exception as e:
            logger.error(
                "heartbeat_exception",
                session_id=session_id,
                error=str(e),
                exc_info=True
            )
            # Don't crash on heartbeat failure - just log and try again
            await asyncio.sleep(60)


async def main(voice_id="Ashley", opening_line=None, system_prompt=None):
    """Main function to run the voice assistant bot.

    Args:
        voice_id: The Inworld TTS voice ID to use (default: "Ashley")
        opening_line: Custom opening line to speak when user joins (default: auto-generated)
        system_prompt: Custom LLM system prompt (default: generic assistant prompt)
    """
    session = None
    transport = None

    try:
        startup_time = time.perf_counter() if ENABLE_TIMING else None
        if ENABLE_TIMING:
            log_timing("voice_assistant_main_started", timestamp=datetime.utcnow().isoformat())

        logger.info("voice_assistant_starting", voice_id=voice_id, opening_line=opening_line)

        # Configure LiveKit connection
        try:
            (url, token, room_name) = await configure()
            logger.info("livekit_configured", room_name=room_name)
        except Exception as e:
            logger.error("livekit_configuration_failed", error=str(e), exc_info=True)
            raise

        # Validate connection parameters
        if not url or not token or not room_name:
            raise ValueError("Missing LiveKit configuration parameters")

        # Use LogContext to track session throughout the lifecycle
        with LogContext(session_id=room_name, voice_id=voice_id):
            # Create transport
            try:
                transport = LiveKitTransport(
                    url=url,
                    token=token,
                    room_name=room_name,
                    params=LiveKitParams(
                        audio_in_enabled=True,
                        audio_out_enabled=True,
                        vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                        turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams()),
                    ),
                )
                logger.info("livekit_transport_created")
            except Exception as e:
                logger.error("livekit_transport_creation_failed", error=str(e), exc_info=True)
                raise

            # Create STT service (AssemblyAI)
            try:
                stt = AssemblyAISTTService(
                    api_key=os.getenv("ASSEMBLY_API_KEY"),
                    connection_params=AssemblyAIConnectionParams(
                        sample_rate=STT_SAMPLE_RATE,
                        encoding=STT_ENCODING,
                        model=STT_MODEL,
                        format_turns=STT_FORMAT_TURNS,
                        end_of_turn_confidence_threshold=STT_END_OF_TURN_CONFIDENCE,
                        min_end_of_turn_silence_when_confident=STT_MIN_SILENCE_CONFIDENT,
                        max_turn_silence=STT_MAX_TURN_SILENCE,
                        enable_partial_transcripts=STT_ENABLE_PARTIALS,
                        use_immutable_finals=STT_IMMUTABLE_FINALS,
                        punctuate=STT_PUNCTUATE,
                        format_text=STT_FORMAT_TEXT,
                    ),
                    vad_force_turn_endpoint=STT_VAD_FORCE_ENDPOINT,
                    language=STT_LANGUAGE,
                )
                logger.info("assemblyai_stt_initialized",
                           model=STT_MODEL,
                           vad_endpoint=STT_VAD_FORCE_ENDPOINT,
                           confidence_threshold=STT_END_OF_TURN_CONFIDENCE)
            except Exception as e:
                logger.error("assemblyai_stt_initialization_failed", error=str(e), exc_info=True)
                raise

            # Create LLM service (Groq)
            try:
                llm = GroqLLMService(
                    api_key=os.getenv("GROQ_API_KEY"),
                    model=LLM_MODEL,
                    stream=LLM_STREAM,
                    max_tokens=LLM_MAX_TOKENS,
                    temperature=LLM_TEMPERATURE,
                    top_p=LLM_TOP_P,
                    presence_penalty=LLM_PRESENCE_PENALTY,
                    frequency_penalty=LLM_FREQUENCY_PENALTY,
                )
                logger.info("groq_llm_initialized",
                           model=LLM_MODEL,
                           stream=LLM_STREAM,
                           max_tokens=LLM_MAX_TOKENS,
                           temperature=LLM_TEMPERATURE)
            except Exception as e:
                logger.error("groq_llm_initialization_failed", error=str(e), exc_info=True)
                raise

            # Create aiohttp session for InworldTTS
            # This session needs to stay alive throughout the pipeline execution
            try:
                session = aiohttp.ClientSession()
                logger.info("http_session_created")
            except Exception as e:
                logger.error("http_session_creation_failed", error=str(e), exc_info=True)
                raise

            # Create TTS service (Inworld)
            try:
                inworld_key = os.getenv("INWORLD_API_KEY", "")
                if not inworld_key:
                    raise ValueError("INWORLD_API_KEY is empty")

                # Get voice-specific speed or use default
                voice_speed = VOICE_SPEED_OVERRIDES.get(voice_id, TTS_DEFAULT_SPEED)

                tts = InworldTTSService(
                    api_key=inworld_key,
                    aiohttp_session=session,
                    voice_id=voice_id,  # Configured via command-line or API
                    model="inworld-tts-1",
                    streaming=TTS_STREAMING,
                    params=InworldTTSService.InputParams(
                        temperature=TTS_TEMPERATURE,
                        speed=voice_speed
                    ),
                )
                logger.info("inworld_tts_initialized",
                           voice_id=voice_id,
                           speed=voice_speed,
                           temperature=TTS_TEMPERATURE,
                           streaming=TTS_STREAMING)
            except Exception as e:
                logger.error("inworld_tts_initialization_failed", error=str(e), exc_info=True)
                raise

        # Create conversation context
        # Use custom system prompt or default
        default_system_prompt = "You are a helpful AI voice assistant."
        base_prompt = system_prompt or default_system_prompt

        # ALWAYS append critical rules to system prompt (static, non-negotiable)
        full_system_prompt = f"{base_prompt}\n\n{CRITICAL_RULES}"

        messages = [
            {
                "role": "system",
                "content": full_system_prompt,
            },
        ]

        logger.info("system_prompt_configured",
                   custom_prompt=bool(system_prompt),
                   prompt_length=len(full_system_prompt),
                   critical_rules_appended=True)

        # Add opening line to conversation history so LLM remembers it
        if opening_line:
            messages.append({
                "role": "assistant",
                "content": opening_line
            })

        context = LLMContext(messages)
        context_aggregator = LLMContextAggregatorPair(context)

        # Configure context aggregator timeouts
        context_aggregator.aggregation_timeout = AGGREGATION_TIMEOUT
        context_aggregator.bot_interruption_timeout = BOT_INTERRUPTION_TIMEOUT

        logger.info("context_aggregator_configured",
                   aggregation_timeout=AGGREGATION_TIMEOUT,
                   interruption_timeout=BOT_INTERRUPTION_TIMEOUT)

        # Create transcript processor and storage
        transcript_processor = TranscriptProcessor()
        transcript_storage = TranscriptStorage(room_name)
        logger.info(f"Transcript processor created for session {room_name}")

        # Set up transcript event handler
        @transcript_processor.event_handler("on_transcript_update")
        async def on_transcript_update(processor, transcript):
            """Capture transcript updates from Pipecat"""
            if hasattr(transcript, 'messages'):
                for message in transcript.messages:
                    # Extract message details
                    role = getattr(message, 'role', 'unknown')
                    content = getattr(message, 'content', '')
                    timestamp = getattr(message, 'timestamp', datetime.utcnow().isoformat())

                    # Store in transcript storage
                    transcript_storage.add_message(role, content, timestamp)
                    logger.debug(f"Transcript captured: {role[:10]}: {content[:50]}...")

        # Build pipeline with transcript processors
        pipeline = Pipeline(
            [
                transport.input(),  # Transport user input
                stt,
                transcript_processor.user(),  # Capture user transcripts
                context_aggregator.user(),  # User responses
                llm,  # LLM
                tts,  # TTS
                transport.output(),  # Transport bot output
                transcript_processor.assistant(),  # Capture assistant transcripts
                context_aggregator.assistant(),  # Assistant spoken responses
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
        )

        # Track cleanup state to prevent duplicate saves
        cleanup_triggered = False

        # Handle when a participant leaves the room (disconnect, network drop, etc.)
        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant_id, *args):
            """Triggered when any participant leaves the room for any reason"""
            nonlocal cleanup_triggered

            # Extract reason if provided in args
            reason = args[0] if args else "unknown"
            logger.info(f"Participant {participant_id} left the room (reason: {reason})")

            # Check if any participants remain
            try:
                remaining_participants = getattr(transport, 'participants', [])
                logger.info(f"Remaining participants: {len(remaining_participants)}")

                if len(remaining_participants) == 0:
                    logger.info("No participants remaining - ending session")
                    if not cleanup_triggered:
                        cleanup_triggered = True
                        await task.cancel()
            except Exception as e:
                logger.error(f"Error checking remaining participants: {e}")
                # If we can't check, trigger cleanup to be safe
                if not cleanup_triggered:
                    cleanup_triggered = True
                    await task.cancel()

        # Handle when disconnected from the LiveKit room
        @transport.event_handler("on_disconnected")
        async def on_disconnected(transport, *args):
            """Triggered when the transport loses connection to the room"""
            nonlocal cleanup_triggered
            logger.info("Disconnected from LiveKit room - triggering cleanup")
            if not cleanup_triggered:
                cleanup_triggered = True
                await task.cancel()

        # Handle when a specific participant's connection drops
        @transport.event_handler("on_participant_disconnected")
        async def on_participant_disconnected(transport, participant_id, *args):
            """Triggered when a participant's connection is lost"""
            nonlocal cleanup_triggered
            logger.info(f"Participant {participant_id} connection lost")

            # For 1-on-1 sessions, end if the other participant disconnects
            try:
                remaining = getattr(transport, 'participants', [])
                if len(remaining) == 0:
                    logger.info("Last participant disconnected - ending session")
                    if not cleanup_triggered:
                        cleanup_triggered = True
                        await task.cancel()
            except Exception as e:
                logger.error(f"Error in participant disconnect handler: {e}")
                if not cleanup_triggered:
                    cleanup_triggered = True
                    await task.cancel()

        # Optional: Handle connection quality issues
        @transport.event_handler("on_connection_quality_changed")
        async def on_connection_quality_changed(transport, participant_id, quality, *args):
            """Monitor connection quality"""
            if quality == "poor":
                logger.warning(f"Poor connection quality for participant {participant_id}")
            elif quality == "lost":
                logger.error(f"Connection lost for participant {participant_id}")

        # Register an event handler so we can play the audio when the
        # participant joins.
        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant_id):
            event_start = time.perf_counter() if ENABLE_TIMING else None

            try:
                logger.info("participant_joined", participant_id=participant_id)

                # Track conversation start time (for billing)
                redis_start = time.perf_counter() if ENABLE_TIMING else None
                conversation_start_time = int(time.time())
                try:
                    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
                    redis_client = redis.from_url(redis_url)
                    redis_client.hset(f'session:{room_name}',
                                     'conversationStartTime',
                                     conversation_start_time)
                    if ENABLE_TIMING and redis_start:
                        log_timing("redis_operation_complete",
                                 duration_ms=f"{(time.perf_counter() - redis_start) * 1000:.1f}")
                    logger.info("conversation_start_time_tracked", start_time=conversation_start_time)
                except Exception as redis_error:
                    logger.error("redis_start_time_tracking_failed", error=str(redis_error))

                # Pipeline stabilization delay (reduced from 1.0s to 0.2s)
                sleep_start = time.perf_counter() if ENABLE_TIMING else None

                await asyncio.sleep(PARTICIPANT_GREETING_DELAY)

                if ENABLE_TIMING and sleep_start:
                    log_timing("sleep_complete",
                             duration_ms=f"{(time.perf_counter() - sleep_start) * 1000:.1f}")

                # Use custom opening line or default
                greeting = opening_line if opening_line else f"Hello! I'm {voice_id}, your AI assistant. How can I help you today?"

                if ENABLE_TIMING:
                    log_timing("greeting_prepared", greeting_length=len(greeting))
                    queue_start = time.perf_counter()
                else:
                    queue_start = None

                await task.queue_frame(
                    TTSSpeakFrame(greeting)
                )

                if ENABLE_TIMING and queue_start and event_start:
                    queue_duration = (time.perf_counter() - queue_start) * 1000
                    total_duration = (time.perf_counter() - event_start) * 1000
                    log_timing("opening_line_queued",
                             queue_duration_ms=f"{queue_duration:.1f}",
                             total_handler_duration_ms=f"{total_duration:.1f}")

                logger.info("opening_line_sent", greeting_preview=greeting[:50])
            except Exception as e:
                logger.error("participant_join_handler_error", error=str(e), exc_info=True)

        # Register an event handler to receive data from the participant via text chat
        # in the LiveKit room. This will be used to as transcription frames and
        # interrupt the bot and pass it to llm for processing and
        # then pass back to the participant as audio output.
        @transport.event_handler("on_data_received")
        async def on_data_received(transport, data, participant_id):
            try:
                logger.info("data_received", participant_id=participant_id, data=str(data))
                # convert data from bytes to string
                json_data = json.loads(data)

                await task.queue_frames(
                    [
                        InterruptionFrame(),
                        UserStartedSpeakingFrame(),
                        TranscriptionFrame(
                            user_id=participant_id,
                            timestamp=json_data["timestamp"],
                            text=json_data["message"],
                        ),
                        UserStoppedSpeakingFrame(),
                    ],
                )
            except json.JSONDecodeError as e:
                logger.error("json_decode_error", error=str(e), exc_info=True)
            except Exception as e:
                logger.error("data_received_handler_error", error=str(e), exc_info=True)

        # Disable PipelineRunner's built-in signal handling so our finally block can execute
        runner = PipelineRunner(handle_sigint=False)

        # Start heartbeat task in background for credit billing
        logger.info("starting_heartbeat_task", session_id=room_name)
        heartbeat_handle = asyncio.create_task(
            heartbeat_task(room_name, transport, transcript_storage)
        )

        logger.info("pipeline_runner_starting")
        await runner.run(task)

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")
    except Exception as e:
        logger.error("fatal_error", error=str(e), exc_info=True)
        raise
    finally:
        logger.info(f"Cleanup initiated for session {room_name}",
                   cleanup_triggered='cleanup_triggered' in locals() and cleanup_triggered)

        # Cancel heartbeat task if it's running
        if 'heartbeat_handle' in locals() and heartbeat_handle:
            try:
                heartbeat_handle.cancel()
                logger.info("heartbeat_task_cancelled", session_id=room_name)
            except Exception as hb_error:
                logger.error("heartbeat_cancellation_failed", error=str(hb_error))

        # Track conversation end time and duration (for billing)
        try:
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
            redis_client = redis.from_url(redis_url)

            start_time = redis_client.hget(f'session:{room_name}', 'conversationStartTime')
            if start_time:
                start_time = int(start_time)
                end_time = int(time.time())
                duration_seconds = end_time - start_time
                duration_minutes = math.ceil(duration_seconds / 60)  # Round up for billing

                redis_client.hset(f'session:{room_name}', mapping={
                    'conversationDuration': duration_seconds,
                    'conversationDurationMinutes': duration_minutes
                })

                logger.info("conversation_duration_tracked",
                           duration_seconds=duration_seconds,
                           duration_minutes=duration_minutes)
        except Exception as duration_error:
            logger.error("duration_tracking_failed", error=str(duration_error))

        # Save transcripts to database using asyncpg
        if 'transcript_storage' in locals():
            # If no transcripts captured but opening line was sent, save it as fallback
            if len(transcript_storage) == 0 and opening_line:
                logger.info(f"No transcripts captured - adding opening line as fallback for session {room_name}")
                # Reconstruct the greeting that was sent
                greeting = opening_line if opening_line else f"Hello! I'm {voice_id}, your AI assistant. How can I help you today?"
                # Use conversation start time if available, otherwise current time
                fallback_timestamp = start_time if (start_time and isinstance(start_time, int)) else int(time.time())
                transcript_storage.add_message(
                    role="assistant",
                    content=greeting,
                    timestamp=fallback_timestamp
                )

            # Now save if we have any transcripts
            if len(transcript_storage) > 0:
                logger.info(f"Saving {len(transcript_storage)} transcripts for session {room_name}")

                try:
                    # Get transcript data
                    transcript_data = transcript_storage.get_transcript_data()

                    # Save to database
                    success = await Database.save_transcript(room_name, transcript_data)

                    if success:
                        logger.info(f"✅ Transcripts saved successfully for session {room_name}",
                                  transcript_count=len(transcript_data))
                    else:
                        logger.error(f"❌ Failed to save transcripts for session {room_name}")

                except Exception as e:
                    logger.error(f"Exception saving transcripts: {e}",
                               session_id=room_name,
                               exc_info=True)
            else:
                logger.info(f"No transcripts to save for session {room_name}")

        # Close database connection
        try:
            await Database.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}", exc_info=True)

        # Clean up resources
        logger.info("cleanup_started")

        # Close HTTP session if it exists
        if 'session' in locals() and session and not session.closed:
            try:
                await session.close()
                logger.info("http_session_closed")
            except Exception as e:
                logger.error("session_close_error", error=str(e), exc_info=True)

        logger.info("shutdown_complete")


# ==================== GRACEFUL SHUTDOWN ====================
# Note: We rely on disconnect event handlers (on_participant_left, on_disconnected)
# to trigger cleanup via task.cancel(). The finally block will execute naturally
# when the pipeline completes. SIGTERM/SIGINT will interrupt the event loop,
# allowing the finally block to run before exit.


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='LiveKit Voice Assistant with Inworld TTS')
    parser.add_argument('--voice-id', type=str, default='Ashley',
                        help='Inworld TTS voice ID (default: Ashley)')
    parser.add_argument('--opening-line', type=str, default=None,
                        help='Custom opening line to speak when user joins')
    parser.add_argument('--system-prompt', type=str, default=None,
                        help='Custom LLM system prompt (optional)')
    parser.add_argument('--room', type=str, help='LiveKit room name (passed to configure)')

    args = parser.parse_args()

    try:
        asyncio.run(main(
            voice_id=args.voice_id,
            opening_line=args.opening_line,
            system_prompt=args.system_prompt
        ))
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_shutdown")
    except Exception as e:
        logger.error("unhandled_exception", error=str(e), exc_info=True)
        sys.exit(1)
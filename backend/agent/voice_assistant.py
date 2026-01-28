import sys
import os

# Force all output to go to stdout (Railway will capture this)
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

# Ensure unbuffered output
os.environ['PYTHONUNBUFFERED'] = '1'

import asyncio
import json
import signal
import argparse
import math
import time
from datetime import datetime

from dotenv import load_dotenv
import aiohttp
from redis.asyncio import Redis
from typing import Optional

# Import structured logging
from backend.shared.logging_config import setup_logging
# Import database service for transcript storage
from backend.shared.services import Database

from pipecat.audio.interruptions.min_words_interruption_strategy import MinWordsInterruptionStrategy
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
# from pipecat.services.cerebras.llm import CerebrasLLMService  # Temporarily disabled
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport

# =============================================================================
# PRODUCTION FIX #3: AGENT_ALIVE signal
# =============================================================================
# This signal tells Celery that imports completed and the agent process is alive.
# Must be printed AFTER all imports complete but BEFORE any slow operations.
# This enables faster failure detection for crashed vs slow agents.
print("AGENT_ALIVE", flush=True)
sys.stdout.flush()
# =============================================================================

load_dotenv(override=True)

# Setup logging
logger = setup_logging(service_name='voice-agent')


class RedisTracker:
    """
    Optional Redis tracker for conversation metrics.

    Provides graceful degradation - agent continues working even if Redis fails.
    All operations are non-blocking with timeout protection (2 seconds).

    Design principles:
    - Non-critical operations: Redis failures don't crash the agent
    - Connection pooling: Reuse connections for efficiency
    - Comprehensive logging: Track both successes and failures
    - Timeout protection: Never hang indefinitely
    """

    def __init__(self, redis_pool: Optional[Redis] = None):
        """
        Initialize tracker with optional Redis connection pool.

        Args:
            redis_pool: Async Redis connection pool. If None, all operations
                       will be skipped gracefully.
        """
        self.pool = redis_pool
        if redis_pool:
            logger.info("redis_tracker_initialized")
        else:
            logger.info("redis_tracker_disabled")

    async def track_conversation_start(self, session_id: str) -> bool:
        """
        Track conversation start time (non-critical operation).

        Stores the Unix timestamp when the first participant joins.
        Used later to calculate conversation duration.

        Args:
            session_id: Session/room identifier

        Returns:
            True if tracking succeeded, False otherwise (agent continues either way)
        """
        if not self.pool:
            logger.debug(f"redis_pool_unavailable session={session_id[:20]}...")
            return False

        try:
            conversation_start_time = int(time.time())
            await self.pool.hset(
                f'session:{session_id}',
                'conversationStartTime',
                conversation_start_time
            )
            logger.info(f"conversation_start_tracked session={session_id[:20]}... start_time={conversation_start_time}")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"redis_timeout_start session={session_id[:20]}... timeout_after=2s")
        except ConnectionError as e:
            logger.warning(f"redis_connection_error_start session={session_id[:20]}... error={e}")
        except Exception as e:
            logger.warning(f"redis_error_start session={session_id[:20]}... error={e}")
        return False

    async def track_conversation_end(self, session_id: str) -> bool:
        """
        Track conversation end, calculate duration, and update status (non-critical).

        Retrieves the start time, calculates duration in seconds and minutes,
        updates the status to 'completed', and records the last active time.

        This combines the logic from both cleanup Redis operations:
        - Duration tracking (lines 536-549 in original)
        - Status update (lines 590-599 in original)

        Args:
            session_id: Session/room identifier

        Returns:
            True if tracking succeeded, False otherwise (agent continues either way)
        """
        if not self.pool:
            logger.debug(f"redis_pool_unavailable session={session_id[:20]}...")
            return False

        try:
            # Retrieve conversation start time
            start_time = await self.pool.hget(
                f'session:{session_id}',
                'conversationStartTime'
            )

            if start_time:
                # Calculate duration
                duration = int(time.time()) - int(start_time)
                duration_minutes = math.ceil(duration / 60)

                # Update all fields atomically in a single HSET
                # This combines duration tracking and status update
                await self.pool.hset(
                    f'session:{session_id}',
                    mapping={
                        'conversationDuration': duration,
                        'conversationDurationMinutes': duration_minutes,
                        'status': 'completed',
                        'lastActive': int(time.time())
                    }
                )
                logger.info(
                    f"conversation_end_tracked session={session_id[:20]}... "
                    f"duration={duration}s duration_minutes={duration_minutes}"
                )
                return True
            else:
                logger.warning(f"no_start_time_found session={session_id[:20]}...")
        except asyncio.TimeoutError:
            logger.warning(f"redis_timeout_end session={session_id[:20]}... timeout_after=2s")
        except ConnectionError as e:
            logger.warning(f"redis_connection_error_end session={session_id[:20]}... error={e}")
        except Exception as e:
            logger.warning(f"redis_error_end session={session_id[:20]}... error={e}")
        return False

    async def signal_cleanup_complete(self, session_id: str, transcript_saved: bool) -> bool:
        """
        Signal that agent cleanup is complete (transcript saved, ready for orchestrator).

        This is a critical signal that tells the orchestrator it's safe to proceed.
        The orchestrator waits for this signal before returning from cleanup_session.

        Args:
            session_id: Session/room identifier
            transcript_saved: Whether transcript was successfully saved to database

        Returns:
            True if signal was sent successfully, False otherwise
        """
        if not self.pool:
            logger.warning(f"redis_pool_unavailable_for_cleanup_signal session={session_id[:20]}...")
            return False

        try:
            cleanup_key = f"session:{session_id}:cleanup_complete"
            cleanup_data = {
                'completed': 'true',
                'transcript_saved': 'true' if transcript_saved else 'false',
                'completed_at': str(int(time.time()))
            }

            # Set completion signal with 60 second TTL (orchestrator should read within seconds)
            await self.pool.hset(cleanup_key, mapping=cleanup_data)
            await self.pool.expire(cleanup_key, 60)

            logger.info(
                f"cleanup_complete_signal_sent session={session_id[:20]}... "
                f"transcript_saved={transcript_saved}"
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(f"redis_timeout_cleanup_signal session={session_id[:20]}... timeout_after=2s")
        except ConnectionError as e:
            logger.warning(f"redis_connection_error_cleanup_signal session={session_id[:20]}... error={e}")
        except Exception as e:
            logger.warning(f"redis_error_cleanup_signal session={session_id[:20]}... error={e}")
        return False


# ==================== AGENT CONFIGURATION ====================

# Timing Configuration (Development Only)
ENABLE_TIMING = os.getenv('LOG_LEVEL', 'INFO').upper() == 'DEBUG'
PARTICIPANT_GREETING_DELAY = 0.2

# Context Aggregator Settings
AGGREGATION_TIMEOUT = 0.1
BOT_INTERRUPTION_TIMEOUT = 0.1

# TTS Configuration (Inworld)
TTS_STREAMING = True
TTS_TEMPERATURE = 0.8
TTS_DEFAULT_SPEED = 1.0

VOICE_SPEED_OVERRIDES = {
    "Craig": 1.2,
    "Edward": 1.0,
    "Olivia": 1.0,
    "Wendy": 1.2,
    "Priya": 1.0,
    "Ashley": 1.0,
}

# STT Configuration (AssemblyAI)
STT_SAMPLE_RATE = 16000
STT_ENCODING = "pcm_s16le"
STT_MODEL = "universal-streaming"
STT_FORMAT_TURNS = False
STT_END_OF_TURN_CONFIDENCE = 0.40
STT_MIN_SILENCE_CONFIDENT = 200
STT_MAX_TURN_SILENCE = 450
STT_ENABLE_PARTIALS = True
STT_IMMUTABLE_FINALS = True
STT_PUNCTUATE = False
STT_FORMAT_TEXT = False
STT_VAD_FORCE_ENDPOINT = False
STT_LANGUAGE = "en"

# LLM Configuration (Groq)
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_STREAM = True
LLM_MAX_TOKENS = 100
LLM_TEMPERATURE = 0.1

# Critical Rules (appended to all system prompts)
CRITICAL_RULES = """
<role>Simulated role player in a formal exam. Responses spoken via TTS.</role>

<tts_output>
Everything written is read aloud exactly - no filtering.
- NO stage directions, asterisks (*sighs*), brackets, descriptions
- ONLY plain speech + optional emotion tags
- Speak naturally, not descriptively
</tts_output>

<emotion_tags>
Valid tags (START of response only): [happy] [sad] [angry] [surprised] [fearful] [disgusted]
An Other tags are not allowed. 
Use occasionaly when emotionally appropriate only not with every sentence.
</emotion_tags>

<exam_integrity>
CRITICAL: This is a FORMAL EXAM. Student must extract information through proper questioning.
Volunteering unrequested information RUINS the exam and FAILS the student.
You are NOT helping by offering extra details - you are DESTROYING their assessment.
Follow the script that you will be given
</exam_integrity>

<response_rules>
QUESTION asked → Answer with ONE fact only, then STOP
- Keep responses short and conversational (1-2 sentences max)
- Yes/no question = yes/no answer only
- Hold all information until directly asked
- Don't repeat student's words back
- Only answer what is specifically asked

STATEMENT made (greeting/acknowledgment/empathy) → Brief natural response
For example: When student says "okay", "I see", "that must be hard", or any similar STATEMENT
⛔ DO NOT continue sharing script information
⛔ DO NOT volunteer next detail
✅ DO respond briefly and naturally 

Brief response examples (use these OR similar natural variations):
- Acknowledgments: "Mhm", "Yeah", "Okay", or silence
- Empathy: "It is", "Thank you", "I appreciate that"
- Greetings: "Nice to meet you too"
- Always pick what fits the context, like a real person would and use similar natural variations - The above is examples only.
- DO vary responses - never repeat same phrase consecutively - be natural as what a real human will do 

</response_rules>

<forbidden>
- Volunteering unasked information from the scipt
- Continuing script infromation when acknowledged rather than natural brief reply
- Repeating student statements
- Non-speech text (actions, descriptions, invalid tags)
</forbidden>

""".strip()

# ==================== END CONFIGURATION ====================

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
        logger.error(f"environment_validation_failed missing_variables={missing}")
        sys.exit(1)

    logger.info("environment_validated")

validate_environment()

def log_timing(message: str):
    """Log timing information only in development mode"""
    if ENABLE_TIMING:
        logger.debug(f"TIMING: {message}")


# =============================================================================
# PRODUCTION FIX #6: Frontend Status Updates
# =============================================================================

class AgentStatusReporter:
    """
    Sends agent status updates to frontend via LiveKit data channel.

    This allows the frontend to show appropriate UI states like:
    - "Connecting to voice agent..."
    - "Voice agent ready"
    - "Agent encountered an error"

    Status messages are sent as JSON via LiveKit's data channel.
    """

    # Status constants
    STATUS_INITIALIZING = "initializing"
    STATUS_CONNECTING = "connecting"
    STATUS_READY = "ready"
    STATUS_ERROR = "error"
    STATUS_DISCONNECTED = "disconnected"

    def __init__(self, transport):
        self.transport = transport
        self._last_status = None
        logger.info("AgentStatusReporter initialized")

    async def send_status(self, status: str, message: str, details: dict = None):
        """
        Send status update to frontend.

        Args:
            status: One of the STATUS_* constants
            message: Human-readable status message
            details: Optional additional details
        """
        try:
            data = {
                "type": "agent_status",
                "status": status,
                "message": message,
                "timestamp": time.time()
            }
            if details:
                data["details"] = details

            json_data = json.dumps(data)

            # Fire and forget - don't block pipeline for status updates
            asyncio.create_task(self._send_message(json_data))

            self._last_status = status
            logger.debug(f"status_update_sent status={status} message={message}")

        except Exception as e:
            logger.warning(f"status_update_failed status={status} error={str(e)}")

    async def _send_message(self, data: str):
        """Internal method to send message with error handling."""
        try:
            await self.transport.send_message(data)
        except Exception as e:
            logger.warning(f"send_message_failed error={str(e)}")

    async def report_initializing(self, component: str = None):
        """Report that agent is initializing."""
        msg = f"Loading {component}..." if component else "Initializing voice agent..."
        await self.send_status(self.STATUS_INITIALIZING, msg, {"component": component})

    async def report_connecting(self):
        """Report that agent is connecting to room."""
        await self.send_status(self.STATUS_CONNECTING, "Connecting to voice room...")

    async def report_ready(self):
        """Report that agent is ready to converse."""
        await self.send_status(self.STATUS_READY, "Voice agent ready")

    async def report_error(self, error_message: str):
        """Report an error occurred."""
        await self.send_status(self.STATUS_ERROR, error_message)

    async def report_disconnected(self, reason: str = None):
        """Report that agent has disconnected."""
        msg = f"Disconnected: {reason}" if reason else "Voice agent disconnected"
        await self.send_status(self.STATUS_DISCONNECTED, msg)


class TranscriptionReporter:
    """Helper to send transcription events to frontend for latency tracking"""

    def __init__(self, transport):
        self.transport = transport
        logger.info("TranscriptionReporter initialized")

    async def report_user_transcript(self, text: str, timestamp: float = None):
        """Send user transcription to frontend for latency tracking"""
        try:
            if timestamp is None:
                timestamp = asyncio.get_event_loop().time()

            data = json.dumps({
                "type": "transcription",
                "speaker": "user",
                "text": text,
                "timestamp": timestamp
            })

            # Fire and forget - don't block audio pipeline for frontend notifications
            asyncio.create_task(self.transport.send_message(data))
            logger.debug(f"Sent user transcript to frontend: {text[:50]}...")
        except Exception as e:
            logger.error(f"Failed to send user transcript: {e}")

    async def report_assistant_transcript(self, text: str, timestamp: float = None):
        """Send assistant transcription to frontend (for full cycle tracking)"""
        try:
            if timestamp is None:
                timestamp = asyncio.get_event_loop().time()

            data = json.dumps({
                "type": "transcription",
                "speaker": "assistant",
                "text": text,
                "timestamp": timestamp
            })

            # Fire and forget - don't block audio pipeline for frontend notifications
            asyncio.create_task(self.transport.send_message(data))
            logger.debug(f"Sent assistant transcript to frontend: {text[:50]}...")
        except Exception as e:
            logger.error(f"Failed to send assistant transcript: {e}")


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
        logger.debug(f"Captured {role} message #{len(self.transcripts)}")

    def get_transcript_data(self):
        """Get formatted transcript data for database storage"""
        return self.transcripts

    def __len__(self):
        """Return the number of transcript entries"""
        return len(self.transcripts)


async def heartbeat_task(session_id: str, transport=None, transcript_storage=None, heartbeat_session=None):
    """Send heartbeat to orchestrator every minute for credit billing."""
    await asyncio.sleep(60)

    while True:
        try:
            logger.info(f"heartbeat_sending session_id={session_id}")

            orchestrator_url = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")

            if heartbeat_session is None:
                logger.error(f"heartbeat_session_missing session_id={session_id}")
                await asyncio.sleep(60)
                continue

            # Non-blocking heartbeat with 2-second timeout to prevent event loop blocking
            # Wrapped in asyncio.timeout for additional protection against slow responses
            try:
                async with asyncio.timeout(2):
                    async with heartbeat_session.post(
                        f"{orchestrator_url}/api/session/heartbeat",
                        json={"sessionId": session_id},
                        timeout=aiohttp.ClientTimeout(total=2)  # Reduced from 10s to prevent blocking
                    ) as response:
                        result = await response.json()
            except asyncio.TimeoutError:
                # Timeout is not critical - heartbeat will retry in 60s
                logger.warning(f"heartbeat_timeout session_id={session_id} timeout=2s action=continuing")
                await asyncio.sleep(60)
                continue
            except Exception as e:
                # Network errors are not critical - heartbeat will retry in 60s
                logger.warning(f"heartbeat_network_error session_id={session_id} error={str(e)} action=continuing")
                await asyncio.sleep(60)
                continue

            if result.get("status") == "stop":
                logger.warning(f"heartbeat_stop_received session_id={session_id}")

                # Save transcript before stopping
                if transcript_storage and len(transcript_storage) > 0:
                    try:
                        transcript_data = transcript_storage.get_transcript_data()
                        success = await Database.save_transcript(session_id, transcript_data)
                        if success:
                            logger.info(f"Transcript saved before stop: {len(transcript_data)} messages")
                    except Exception as save_error:
                        logger.error(f"Failed to save transcript before stop: {save_error}")

                # Close transport if available
                if transport:
                    try:
                        await transport.close()
                        logger.info("Transport closed due to insufficient credits")
                    except Exception as close_error:
                        logger.error(f"Transport close error: {close_error}")

                logger.info("Exiting due to insufficient credits")
                sys.exit(0)

            elif result.get("status") == "ok":
                logger.info(f"heartbeat_success credits_remaining={result.get('credits_remaining')}")

            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info(f"heartbeat_cancelled session_id={session_id}")
            break
        except Exception as e:
            logger.error(f"heartbeat_exception: {e}")
            await asyncio.sleep(60)


async def main(voice_id="Ashley", opening_line=None, system_prompt=None):
    """Main function to run the voice assistant bot."""
    session = None
    transport = None
    redis_pool = None
    redis_tracker = None
    status_reporter = None  # PRODUCTION FIX #6

    try:
        logger.info(f"voice_assistant_starting voice_id={voice_id}")

        # Configure LiveKit connection
        (url, token, room_name) = await configure()
        logger.info(f"livekit_configured room_name={room_name}")

        # Initialize Redis connection pool (optional, non-critical)
        # Agent will continue working even if Redis is unavailable
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
        try:
            redis_pool = await Redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=10,              # Pool up to 10 connections
                socket_connect_timeout=2,        # 2 second connection timeout
                socket_timeout=2,                # 2 second operation timeout
                socket_keepalive=True,           # Keep connections alive
                health_check_interval=30         # Check connection health every 30s
            )
            logger.info("redis_pool_created max_connections=10 timeout=2s")
            redis_tracker = RedisTracker(redis_pool)
        except asyncio.TimeoutError:
            logger.warning(f"redis_pool_creation_timeout url={redis_url} timeout=2s")
            logger.info("continuing_without_redis_tracking")
            redis_tracker = RedisTracker(None)
        except ConnectionError as e:
            logger.warning(f"redis_pool_connection_failed url={redis_url} error={e}")
            logger.info("continuing_without_redis_tracking")
            redis_tracker = RedisTracker(None)
        except Exception as e:
            logger.warning(f"redis_pool_creation_failed url={redis_url} error={e}")
            logger.info("continuing_without_redis_tracking")
            redis_tracker = RedisTracker(None)

        # Create transport
        transport = LiveKitTransport(
            url=url,
            token=token,
            room_name=room_name,
            params=LiveKitParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                # turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams()),
            ),
        )
        logger.info("livekit_transport_created")

        # PRODUCTION FIX #6: Initialize status reporter
        status_reporter = AgentStatusReporter(transport)

        # Create STT service (AssemblyAI only)
        stt_service_name = "unknown"

        if not os.getenv("ASSEMBLY_API_KEY"):
            raise Exception("ASSEMBLY_API_KEY is required for STT service")

        try:
            logger.info("Initializing AssemblyAI STT service")
            stt = AssemblyAISTTService(
                api_key=os.getenv("ASSEMBLY_API_KEY"),
                api_endpoint_base_url="wss://streaming.eu.assemblyai.com/v3/ws",
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
            stt_service_name = f"AssemblyAI ({STT_MODEL})"
            logger.info(f"stt_service_initialized service=AssemblyAI model={STT_MODEL}")
        except Exception as e:
            logger.error(f"assemblyai_stt_failed error={str(e)}")
            raise Exception(f"AssemblyAI STT service failed. Cannot proceed.") from e

        logger.info(f"stt_service_active service={stt_service_name}")

        # Create LLM service (Groq)
        llm = GroqLLMService(
            api_key=os.getenv("GROQ_API_KEY"),
            model=LLM_MODEL,
            stream=LLM_STREAM,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
        )
        logger.info(f"groq_llm_initialized model={LLM_MODEL} temperature={LLM_TEMPERATURE} max_tokens={LLM_MAX_TOKENS}")

        # Create aiohttp session for InworldTTS
        session = aiohttp.ClientSession()

        # Create dedicated aiohttp session for heartbeat
        heartbeat_session = aiohttp.ClientSession()
        logger.info("heartbeat_session_created")

        # Create TTS service (Inworld)
        # Note: Speed parameter is not currently supported by Pipecat's InworldTTSService
        # Only temperature is available in InputParams
        voice_speed = VOICE_SPEED_OVERRIDES.get(voice_id, TTS_DEFAULT_SPEED)
        tts = InworldTTSService(
            api_key=os.getenv("INWORLD_API_KEY"),
            aiohttp_session=session,
            voice_id=voice_id,
            model="inworld-tts-1",
            streaming=TTS_STREAMING,
            params=InworldTTSService.InputParams(
                temperature=TTS_TEMPERATURE,
                # speed parameter not supported by Pipecat's InworldTTSService yet
            ),
        )
        logger.info(f"inworld_tts_initialized voice_id={voice_id} temperature={TTS_TEMPERATURE}")

        # Create conversation context
        base_prompt = system_prompt or "You are a role player actor so follow the script and the critical rules strictly."
        full_system_prompt = f"{base_prompt}\n\n{CRITICAL_RULES}"

        messages = [{"role": "system", "content": full_system_prompt}]

        if opening_line:
            messages.append({"role": "assistant", "content": opening_line})

        context = LLMContext(messages)
        context_aggregator = LLMContextAggregatorPair(context)
        context_aggregator.aggregation_timeout = AGGREGATION_TIMEOUT
        context_aggregator.bot_interruption_timeout = BOT_INTERRUPTION_TIMEOUT

        # Create transcription reporter (will be initialized after connection)
        transcription_reporter = None

        # Create transcript processor and storage
        transcript_processor = TranscriptProcessor()
        transcript_storage = TranscriptStorage(room_name)
        logger.info(f"Transcript processor created for session {room_name}")

        # Set up transcript event handler
        @transcript_processor.event_handler("on_transcript_update")
        async def on_transcript_update(processor, transcript):
            """Capture transcript updates from Pipecat"""
            nonlocal transcription_reporter

            if hasattr(transcript, 'messages'):
                for message in transcript.messages:
                    role = getattr(message, 'role', 'unknown')
                    content = getattr(message, 'content', '')
                    timestamp = getattr(message, 'timestamp', datetime.utcnow().isoformat())

                    # Store in transcript storage
                    transcript_storage.add_message(role, content, timestamp)

                    # Send transcripts to frontend if reporter is initialized
                    if transcription_reporter:
                        if role == 'user' and content:
                            await transcription_reporter.report_user_transcript(content)
                        elif role == 'assistant' and content:
                            await transcription_reporter.report_assistant_transcript(content)

        # Build pipeline with transcript processors
        pipeline = Pipeline([
            transport.input(),
            stt,
            transcript_processor.user(),
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            transcript_processor.assistant(),
            context_aggregator.assistant(),
        ])

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
                allow_interruptions=True,
                interruption_strategies=[
                    MinWordsInterruptionStrategy(min_words=3)
                ]
            ),
        )

        cleanup_triggered = False

        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant_id, *args):
            nonlocal cleanup_triggered
            logger.info(f"Participant {participant_id} left")
            try:
                remaining = getattr(transport, 'participants', [])
                if len(remaining) == 0:
                    logger.info("No participants remaining - ending session")
                    # PRODUCTION FIX #6: Send disconnected status
                    if status_reporter:
                        await status_reporter.report_disconnected("User left the room")
                    if not cleanup_triggered:
                        cleanup_triggered = True
                        await task.cancel()
            except Exception as e:
                logger.error(f"Error in participant_left handler: {e}")
                if not cleanup_triggered:
                    cleanup_triggered = True
                    await task.cancel()

        @transport.event_handler("on_disconnected")
        async def on_disconnected(transport, *args):
            nonlocal cleanup_triggered
            logger.info("Disconnected from LiveKit room")
            # PRODUCTION FIX #6: Send disconnected status
            if status_reporter:
                await status_reporter.report_disconnected("Connection lost")
            if not cleanup_triggered:
                cleanup_triggered = True
                await task.cancel()

        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant_id):
            nonlocal transcription_reporter

            logger.info(f"participant_joined participant_id={participant_id}")

            # Create transcription reporter after transport is connected
            transcription_reporter = TranscriptionReporter(transport)

            # PRODUCTION FIX #6: Send ready status to frontend
            if status_reporter:
                await status_reporter.report_ready()

            # Track conversation start time (non-blocking, non-critical)
            await redis_tracker.track_conversation_start(room_name)

            # Pipeline stabilization delay
            await asyncio.sleep(PARTICIPANT_GREETING_DELAY)

            # Send opening line
            greeting = opening_line if opening_line else f"Hello! I'm {voice_id}, your AI assistant. How can I help you today?"
            await task.queue_frame(TTSSpeakFrame(greeting))
            logger.info(f"opening_line_sent")

        @transport.event_handler("on_data_received")
        async def on_data_received(transport, data, participant_id):
            try:
                json_data = json.loads(data)
                await task.queue_frames([
                    InterruptionFrame(),
                    UserStartedSpeakingFrame(),
                    TranscriptionFrame(
                        user_id=participant_id,
                        timestamp=json_data["timestamp"],
                        text=json_data["message"],
                    ),
                    UserStoppedSpeakingFrame(),
                ])
            except Exception as e:
                logger.error(f"data_received_error: {e}")

        # Disable PipelineRunner's built-in signal handling
        runner = PipelineRunner(handle_sigint=False)

        # Start heartbeat task
        logger.info(f"starting_heartbeat_task session_id={room_name}")
        heartbeat_handle = asyncio.create_task(
            heartbeat_task(room_name, transport, transcript_storage, heartbeat_session)
        )

        logger.info("pipeline_runner_starting")
        await runner.run(task)

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")
    except Exception as e:
        logger.error(f"fatal_error: {e}", exc_info=True)
        # PRODUCTION FIX #6: Send error status
        if status_reporter:
            await status_reporter.report_error(str(e))
        raise
    finally:
        logger.info(f"Cleanup initiated for session {room_name}")

        # Cancel heartbeat task
        if 'heartbeat_handle' in locals() and heartbeat_handle:
            try:
                heartbeat_handle.cancel()
            except Exception:
                pass

        # Track conversation end (combines duration tracking and status update)
        if 'redis_tracker' in locals() and redis_tracker:
            await redis_tracker.track_conversation_end(room_name)

        # Save transcripts to database
        transcript_saved = False
        if 'transcript_storage' in locals():
            if len(transcript_storage) == 0 and opening_line:
                greeting = opening_line if opening_line else f"Hello! I'm {voice_id}, your AI assistant."
                transcript_storage.add_message("assistant", greeting)

            if len(transcript_storage) > 0:
                try:
                    transcript_data = transcript_storage.get_transcript_data()
                    transcript_saved = await Database.save_transcript(room_name, transcript_data)
                    if transcript_saved:
                        logger.info(f"Transcripts saved: {len(transcript_data)} messages")
                    else:
                        logger.error("Failed to save transcripts")
                except Exception as e:
                    logger.error(f"Exception saving transcripts: {e}")

        # Signal cleanup complete to orchestrator (CRITICAL: must happen after transcript save)
        # This allows orchestrator to know it's safe to return from cleanup_session
        if 'redis_tracker' in locals() and redis_tracker:
            await redis_tracker.signal_cleanup_complete(room_name, transcript_saved)

        # Close database connection
        try:
            await Database.close()
        except Exception as e:
            logger.error(f"Error closing database: {e}")

        # Close HTTP session
        if 'session' in locals() and session and not session.closed:
            try:
                await session.close()
            except Exception as e:
                logger.error(f"session_close_error: {e}")

        # Close heartbeat session
        if 'heartbeat_session' in locals() and heartbeat_session and not heartbeat_session.closed:
            try:
                await heartbeat_session.close()
                logger.info("heartbeat_session_closed")
            except Exception as e:
                logger.error(f"heartbeat_session_close_error: {e}")

        # Close Redis pool
        if 'redis_pool' in locals() and redis_pool:
            try:
                await redis_pool.close()
                await redis_pool.connection_pool.disconnect()
                logger.info("redis_pool_closed")
            except Exception as e:
                logger.error(f"redis_pool_cleanup_error: {e}")

        logger.info("shutdown_complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='LiveKit Voice Assistant with Inworld TTS')
    parser.add_argument('--voice-id', type=str, default='Ashley')
    parser.add_argument('--opening-line', type=str, default=None)
    parser.add_argument('--system-prompt', type=str, default=None)
    parser.add_argument('--room', type=str)

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
        logger.error(f"unhandled_exception: {e}", exc_info=True)
        sys.exit(1)

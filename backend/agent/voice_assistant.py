import asyncio
import json
import os
import sys
import signal
import argparse

from dotenv import load_dotenv
import aiohttp

# Import structured logging
from backend.common.logging_config import setup_logging, LogContext

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
from pipecat.runner.livekit import configure
from pipecat.services.inworld.tts import InworldTTSService
from pipecat.services.assemblyai.stt import AssemblyAISTTService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport

load_dotenv(override=True)

# Setup logging
logger = setup_logging(service_name='voice-agent')

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


async def main(voice_id="Ashley", opening_line=None):
    """Main function to run the voice assistant bot.

    Args:
        voice_id: The Inworld TTS voice ID to use (default: "Ashley")
        opening_line: Custom opening line to speak when user joins (default: auto-generated)
    """
    session = None
    transport = None

    try:
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
                stt = AssemblyAISTTService(api_key=os.getenv("ASSEMBLY_API_KEY"))
                logger.info("assemblyai_stt_initialized")
            except Exception as e:
                logger.error("assemblyai_stt_initialization_failed", error=str(e), exc_info=True)
                raise

            # Create LLM service (Groq)
            try:
                llm = GroqLLMService(
                    api_key=os.getenv("GROQ_API_KEY"),
                    model="llama-3.3-70b-versatile"
                )
                logger.info("groq_llm_initialized", model="llama-3.3-70b-versatile")
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

                tts = InworldTTSService(
                    api_key=inworld_key,
                    aiohttp_session=session,
                    voice_id=voice_id,  # Configured via command-line or API
                    model="inworld-tts-1",
                    streaming=True,
                )
                logger.info("inworld_tts_initialized", voice_id=voice_id, model="inworld-tts-1")
            except Exception as e:
                logger.error("inworld_tts_initialization_failed", error=str(e), exc_info=True)
                raise

        # Create conversation context
        messages = [
            {
                "role": "system",
                "content": "You are a helpful LLM in a WebRTC call. "
                "Your goal is to demonstrate your capabilities in a succinct way. "
                "Your output will be converted to audio so don't include special characters in your answers. "
                "Respond to what the user said in a creative and helpful way.",
            },
        ]

        context = LLMContext(messages)
        context_aggregator = LLMContextAggregatorPair(context)

        # Build pipeline
        pipeline = Pipeline(
            [
                transport.input(),  # Transport user input
                stt,
                context_aggregator.user(),  # User responses
                llm,  # LLM
                tts,  # TTS
                transport.output(),  # Transport bot output
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

        # Register an event handler so we can play the audio when the
        # participant joins.
        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant_id):
            try:
                logger.info("participant_joined", participant_id=participant_id)
                await asyncio.sleep(1)

                # Use custom opening line or default
                greeting = opening_line if opening_line else f"Hello! I'm {voice_id}, your AI assistant. How can I help you today?"

                await task.queue_frame(
                    TTSSpeakFrame(greeting)
                )
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

        runner = PipelineRunner()

        logger.info("pipeline_runner_starting")
        await runner.run(task)

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")
    except Exception as e:
        logger.error("fatal_error", error=str(e), exc_info=True)
        raise
    finally:
        # Clean up resources
        logger.info("cleanup_started")
        if session and not session.closed:
            try:
                await session.close()
                logger.info("http_session_closed")
            except Exception as e:
                logger.error("session_close_error", error=str(e), exc_info=True)

        logger.info("shutdown_complete")


# ==================== GRACEFUL SHUTDOWN ====================
def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.warning("signal_received", signal=signum, action="graceful_shutdown")
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='LiveKit Voice Assistant with Inworld TTS')
    parser.add_argument('--voice-id', type=str, default='Ashley',
                        help='Inworld TTS voice ID (default: Ashley)')
    parser.add_argument('--opening-line', type=str, default=None,
                        help='Custom opening line to speak when user joins')
    parser.add_argument('--room', type=str, help='LiveKit room name (passed to configure)')

    args = parser.parse_args()

    try:
        asyncio.run(main(
            voice_id=args.voice_id,
            opening_line=args.opening_line
        ))
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_shutdown")
    except Exception as e:
        logger.error("unhandled_exception", error=str(e), exc_info=True)
        sys.exit(1)
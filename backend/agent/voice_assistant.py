import asyncio
import json
import os
import sys
import signal
import argparse

from dotenv import load_dotenv
from loguru import logger
import aiohttp

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

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

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
        logger.error("FATAL: Missing required environment variables:")
        for msg in missing:
            logger.error(msg)
        logger.error("Please check your .env file and ensure all required variables are set.")
        sys.exit(1)

    logger.info("✓ Environment variables validated")

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
        logger.info(f"Starting voice assistant bot with voice: {voice_id}")

        # Configure LiveKit connection
        try:
            (url, token, room_name) = await configure()
            logger.info(f"Configured for room: {room_name}")
        except Exception as e:
            logger.error(f"Failed to configure LiveKit: {e}")
            raise

        # Validate connection parameters
        if not url or not token or not room_name:
            raise ValueError("Missing LiveKit configuration parameters")

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
            logger.info("LiveKit transport created")
        except Exception as e:
            logger.error(f"Failed to create LiveKit transport: {e}")
            raise

        # Create STT service (AssemblyAI)
        try:
            stt = AssemblyAISTTService(api_key=os.getenv("ASSEMBLY_API_KEY"))
            logger.info("AssemblyAI STT service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize AssemblyAI STT: {e}")
            raise

        # Create LLM service (Groq)
        try:
            llm = GroqLLMService(
                api_key=os.getenv("GROQ_API_KEY"),
                model="llama-3.3-70b-versatile"
            )
            logger.info("Groq LLM service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Groq LLM: {e}")
            raise

        # Create aiohttp session for InworldTTS
        # This session needs to stay alive throughout the pipeline execution
        try:
            session = aiohttp.ClientSession()
            logger.info("HTTP session created for TTS")
        except Exception as e:
            logger.error(f"Failed to create HTTP session: {e}")
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
            logger.info(f"Inworld TTS service initialized with voice: {voice_id}")
        except Exception as e:
            logger.error(f"Failed to initialize Inworld TTS: {e}")
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
                logger.info(f"First participant joined: {participant_id}")
                await asyncio.sleep(1)

                # Use custom opening line or default
                greeting = opening_line if opening_line else f"Hello! I'm {voice_id}, your AI assistant. How can I help you today?"

                await task.queue_frame(
                    TTSSpeakFrame(greeting)
                )
                logger.info(f"Sent opening line: {greeting[:50]}...")
            except Exception as e:
                logger.error(f"Error in on_first_participant_joined: {e}")

        # Register an event handler to receive data from the participant via text chat
        # in the LiveKit room. This will be used to as transcription frames and
        # interrupt the bot and pass it to llm for processing and
        # then pass back to the participant as audio output.
        @transport.event_handler("on_data_received")
        async def on_data_received(transport, data, participant_id):
            try:
                logger.info(f"Received data from participant {participant_id}: {data}")
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
                logger.error(f"Failed to parse JSON data: {e}")
            except Exception as e:
                logger.error(f"Error in on_data_received: {e}")

        runner = PipelineRunner()

        logger.info("Starting pipeline runner...")
        await runner.run(task)

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise
    finally:
        # Clean up resources
        logger.info("Cleaning up resources...")
        if session and not session.closed:
            try:
                await session.close()
                logger.info("HTTP session closed")
            except Exception as e:
                logger.error(f"Error closing session: {e}")

        logger.info("Bot shutdown complete")


# ==================== GRACEFUL SHUTDOWN ====================
def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.warning(f"Received signal {signum}, initiating graceful shutdown...")
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
        logger.info("Shutting down on keyboard interrupt")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
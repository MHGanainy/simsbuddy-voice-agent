"""
Standalone Voice Agent Server

Provides direct access to a voice agent for frontend testing.
Bypasses orchestrator/Celery architecture entirely.

Features:
- Pre-spawns voice agent on startup
- Generates LiveKit tokens on-demand
- Single agent, single room (for testing only)
- No database, no Celery, minimal dependencies
"""

import os
import sys
import asyncio
import subprocess
import signal
import time
import logging
import threading
from typing import Optional, Dict, Any
from datetime import timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from livekit import api

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================

# LiveKit Configuration
LIVEKIT_URL = os.getenv('LIVEKIT_URL', 'wss://livekit-server.com')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY', '')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET', '')

# Voice Agent Configuration
VOICE_ID = os.getenv('VOICE_ID', 'Ashley')
OPENING_LINE = os.getenv('OPENING_LINE', 'Hello! I am ready for testing. How can I help you?')
SYSTEM_PROMPT = os.getenv('SYSTEM_PROMPT', 'You are a helpful AI voice assistant. Keep responses brief and conversational.')

# Agent Room Configuration
AGENT_ROOM_NAME = os.getenv('AGENT_ROOM_NAME', 'test-agent-room')
AGENT_USER_ID = os.getenv('AGENT_USER_ID', 'voice-agent')

# Server Configuration
SERVER_PORT = int(os.getenv('SERVER_PORT', '8001'))
AGENT_SCRIPT_PATH = os.getenv('AGENT_SCRIPT_PATH', '/app/backend/agent/voice_assistant.py')

# ==================== GLOBAL STATE ====================

agent_process: Optional[subprocess.Popen] = None
agent_status = {
    'running': False,
    'pid': None,
    'started_at': None,
    'room_name': AGENT_ROOM_NAME
}


# ==================== HELPER FUNCTIONS ====================

def validate_environment():
    """Validate required environment variables"""
    required_vars = {
        'LIVEKIT_URL': LIVEKIT_URL,
        'LIVEKIT_API_KEY': LIVEKIT_API_KEY,
        'LIVEKIT_API_SECRET': LIVEKIT_API_SECRET,
        'GROQ_API_KEY': os.getenv('GROQ_API_KEY'),
        'ASSEMBLY_API_KEY': os.getenv('ASSEMBLY_API_KEY'),
        'INWORLD_API_KEY': os.getenv('INWORLD_API_KEY'),
    }

    missing = [name for name, value in required_vars.items() if not value]

    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    logger.info("Environment validated successfully")


def generate_livekit_token(room_name: str, user_identity: str) -> str:
    """
    Generate LiveKit access token for a user to join a room.

    Args:
        room_name: Room to join
        user_identity: User identity

    Returns:
        JWT token string
    """
    try:
        token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        token.with_identity(user_identity)
        token.with_ttl(timedelta(hours=2))
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        ))

        return token.to_jwt()

    except Exception as e:
        logger.error(f"Failed to generate LiveKit token: {e}", exc_info=True)
        raise


async def spawn_voice_agent():
    """
    Spawn the voice agent process.

    The agent will connect to LiveKit and wait in the room.
    """
    global agent_process, agent_status

    if agent_process and agent_process.poll() is None:
        logger.info("Agent already running, skipping spawn")
        return

    logger.info(f"Spawning voice agent for room: {AGENT_ROOM_NAME}")

    # Generate token for the agent
    agent_token = generate_livekit_token(AGENT_ROOM_NAME, AGENT_USER_ID)

    # Build environment
    env = os.environ.copy()
    env['LIVEKIT_URL'] = LIVEKIT_URL
    env['LIVEKIT_TOKEN'] = agent_token
    env['TEST_MODE'] = 'true'  # Always use test mode (no DB/orchestrator)
    env['PYTHONUNBUFFERED'] = '1'

    # Build command
    cmd = [
        'python3',
        AGENT_SCRIPT_PATH,
        '--room', AGENT_ROOM_NAME,
        '--voice-id', VOICE_ID,
        '--opening-line', OPENING_LINE,
        '--system-prompt', SYSTEM_PROMPT
    ]

    logger.info(f"Spawning agent: {' '.join(cmd)}")

    # Spawn process
    agent_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    # Update status
    agent_status['running'] = True
    agent_status['pid'] = agent_process.pid
    agent_status['started_at'] = time.time()

    logger.info(f"Voice agent spawned: PID={agent_process.pid}, room={AGENT_ROOM_NAME}")

    # Start log reader in background thread (not async - readline is blocking)
    log_thread = threading.Thread(
        target=read_agent_logs_sync,
        daemon=True,
        name=f'log-reader-{AGENT_ROOM_NAME}'
    )
    log_thread.start()
    logger.info(f"Log reader thread started: {log_thread.name}")

    # Wait a few seconds for agent to connect
    await asyncio.sleep(5)

    # Check if process is still alive
    if agent_process.poll() is not None:
        logger.error(f"Agent process died immediately: exit code {agent_process.returncode}")
        agent_status['running'] = False
        raise Exception(f"Agent process failed to start: exit code {agent_process.returncode}")

    logger.info("Voice agent connected successfully")


def read_agent_logs_sync():
    """Read agent stdout and log it (runs in separate thread)"""
    global agent_process

    if not agent_process or not agent_process.stdout:
        return

    try:
        for line in iter(agent_process.stdout.readline, ''):
            if not line:
                break
            logger.info(f"[AGENT] {line.strip()}")
    except Exception as e:
        logger.error(f"Error reading agent logs: {e}")


async def stop_voice_agent():
    """Stop the voice agent process"""
    global agent_process, agent_status

    if not agent_process:
        logger.info("No agent process to stop")
        return

    logger.info(f"Stopping voice agent: PID={agent_process.pid}")

    try:
        # Send SIGTERM
        agent_process.terminate()

        # Wait up to 5 seconds for graceful shutdown
        try:
            agent_process.wait(timeout=5)
            logger.info("Agent terminated gracefully")
        except subprocess.TimeoutExpired:
            # Force kill
            logger.warning("Agent didn't terminate gracefully, sending SIGKILL")
            agent_process.kill()
            agent_process.wait()

    except Exception as e:
        logger.error(f"Error stopping agent: {e}")

    finally:
        agent_status['running'] = False
        agent_status['pid'] = None
        agent_process = None


# ==================== LIFESPAN ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown"""

    # Startup
    logger.info("=" * 60)
    logger.info("Voice Agent Server Starting")
    logger.info("=" * 60)

    # Validate environment
    try:
        validate_environment()
    except ValueError as e:
        logger.error(f"Environment validation failed: {e}")
        sys.exit(1)

    # Spawn voice agent
    try:
        await spawn_voice_agent()
        logger.info("Voice agent ready!")
    except Exception as e:
        logger.error(f"Failed to spawn voice agent: {e}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"Server ready on port {SERVER_PORT}")
    logger.info(f"Agent room: {AGENT_ROOM_NAME}")
    logger.info(f"Voice: {VOICE_ID}")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("Server shutting down...")
    await stop_voice_agent()
    logger.info("Shutdown complete")


# ==================== FASTAPI APP ====================

app = FastAPI(
    title="Voice Agent Server",
    description="Standalone voice agent server for direct frontend testing",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== REQUEST/RESPONSE MODELS ====================

class ConnectRequest(BaseModel):
    userName: Optional[str] = None


class ConnectResponse(BaseModel):
    success: bool
    token: str
    serverUrl: str
    roomName: str
    message: str
    voiceId: str
    agentUserId: str


class HealthResponse(BaseModel):
    status: str
    agent_running: bool
    agent_pid: Optional[int]
    agent_uptime_seconds: Optional[float]
    room_name: str


# ==================== ENDPOINTS ====================

@app.post("/connect", response_model=ConnectResponse)
async def connect(request: ConnectRequest):
    """
    Get LiveKit connection details to join the agent's room.

    The agent is already connected and waiting in the room.
    Frontend gets a token to join the same room.

    Args:
        request: Optional user name

    Returns:
        LiveKit connection details (token, server URL, room name)
    """
    try:
        # Check if agent is running
        if not agent_status['running']:
            logger.error("Agent not running")
            raise HTTPException(
                status_code=503,
                detail="Voice agent is not running. Server may be starting up."
            )

        # Generate token for user
        user_name = request.userName or f"user_{int(time.time())}"
        token = generate_livekit_token(AGENT_ROOM_NAME, user_name)

        logger.info(f"Generated token for user: {user_name}")

        return ConnectResponse(
            success=True,
            token=token,
            serverUrl=LIVEKIT_URL,
            roomName=AGENT_ROOM_NAME,
            message="Connected to voice agent. You can now start speaking.",
            voiceId=VOICE_ID,
            agentUserId=AGENT_USER_ID
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate connection details: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate connection details: {str(e)}"
        )


@app.get("/health", response_model=HealthResponse)
async def health():
    """
    Health check endpoint.

    Returns agent status and server health.
    """
    uptime = None
    if agent_status['started_at']:
        uptime = time.time() - agent_status['started_at']

    return HealthResponse(
        status="healthy" if agent_status['running'] else "agent_not_running",
        agent_running=agent_status['running'],
        agent_pid=agent_status['pid'],
        agent_uptime_seconds=uptime,
        room_name=AGENT_ROOM_NAME
    )


@app.get("/")
async def root():
    """Root endpoint with server info"""
    return {
        "service": "Voice Agent Server",
        "version": "1.0.0",
        "room_name": AGENT_ROOM_NAME,
        "voice_id": VOICE_ID,
        "agent_running": agent_status['running']
    }


# ==================== MAIN ====================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=SERVER_PORT,
        log_level="info"
    )

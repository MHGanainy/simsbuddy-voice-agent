"""
FastAPI Orchestrator for Voice Assistant

Replaces Node.js orchestrator with Python FastAPI.
Generates LiveKit tokens and triggers Celery tasks to spawn voice agents.
Includes proper session tracking, cleanup, and LiveKit webhook handling.
"""

import os
import time
import signal
import hashlib
import hmac
import json
import asyncio
from typing import Optional, Dict, Any
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from livekit import api
import redis

# Import Celery app and tasks
from celery import Celery
from backend.orchestrator.tasks import spawn_voice_agent

# Import structured logging
from backend.common.logging_config import setup_logging, LogContext

# Setup logging
logger = setup_logging(service_name='orchestrator')

# Environment variables
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
    raise ValueError("Missing required environment variables: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET")

# Redis connection
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("redis_connected", redis_url=REDIS_URL)
except Exception as e:
    logger.error("redis_connection_failed", redis_url=REDIS_URL, error=str(e), exc_info=True)
    raise

# Celery app (for task revocation)
celery_app = Celery('voice_agent_tasks')
celery_app.config_from_object('backend.orchestrator.celeryconfig')

# FastAPI app
app = FastAPI(
    title="Voice Assistant Orchestrator",
    description="Python FastAPI orchestrator for LiveKit + Pipecat voice assistant",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Voice configuration - must match backend/agent/voice_assistant.py VOICE_SPEED_OVERRIDES
VALID_VOICES = ["Ashley", "Craig", "Edward", "Olivia", "Wendy", "Priya"]

# Request/Response models
class SessionStartRequest(BaseModel):
    userName: str
    voiceId: Optional[str] = "Ashley"
    openingLine: Optional[str] = None
    systemPrompt: Optional[str] = None
    correlationToken: Optional[str] = None  # External correlation ID for tracking

class SessionStartResponse(BaseModel):
    success: bool
    sessionId: str
    token: str
    serverUrl: str
    roomName: str
    message: str

class SessionEndRequest(BaseModel):
    sessionId: str

class SessionEndResponse(BaseModel):
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None

class LiveKitWebhookEvent(BaseModel):
    event: str
    room: Optional[Dict[str, Any]] = None
    participant: Optional[Dict[str, Any]] = None

# Helper functions
def generate_session_id() -> str:
    """Generate unique session ID"""
    import random
    import string
    timestamp = int(time.time() * 1000)
    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=9))
    return f"session_{timestamp}_{random_suffix}"

def generate_livekit_token(session_id: str, user_name: str) -> str:
    """
    Generate LiveKit access token

    Args:
        session_id: Room name (session ID)
        user_name: User identity

    Returns:
        JWT token string

    Raises:
        Exception: If token generation fails
    """
    try:
        # Create token with 2-hour TTL
        token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        token.with_identity(user_name or f"user_{int(time.time())}")
        token.with_ttl(timedelta(hours=2))

        # Add room join grant
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=session_id,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        ))

        return token.to_jwt()
    except Exception as e:
        logger.error("livekit_token_generation_failed", error=str(e), exc_info=True)
        raise

def verify_livekit_webhook(payload: bytes, signature: str) -> bool:
    """
    Verify LiveKit webhook signature

    Args:
        payload: Raw request body
        signature: X-LiveKit-Signature header value

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        # LiveKit uses HMAC-SHA256 with API secret
        expected_signature = hmac.new(
            LIVEKIT_API_SECRET.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature, expected_signature)
    except Exception as e:
        logger.error("webhook_signature_verification_error", error=str(e), exc_info=True)
        return False

async def cleanup_session(session_id: str) -> Dict[str, Any]:
    """
    Clean up session resources (async to avoid blocking API)

    Steps:
    1. Get session data from Redis
    2. Revoke Celery task if exists
    3. Kill voice agent process (SIGTERM then SIGKILL)
    4. Remove all Redis keys for this session

    Args:
        session_id: Session to clean up

    Returns:
        dict with cleanup details
    """
    cleanup_details = {
        "session_id": session_id,
        "celery_task_revoked": False,
        "process_killed": False,
        "redis_cleaned": False,
        "durationSeconds": 0,
        "durationMinutes": 0,
        "errors": []
    }

    try:
        # Get session data
        session_key = f"session:{session_id}"
        session_data = redis_client.hgetall(session_key)

        if not session_data:
            logger.warning("cleanup_no_session_found", session_id=session_id)
            cleanup_details["errors"].append("Session not found")
            return cleanup_details

        # Extract conversation duration (for billing)
        try:
            duration_seconds = session_data.get(b'conversationDuration') or session_data.get('conversationDuration')
            duration_minutes = session_data.get(b'conversationDurationMinutes') or session_data.get('conversationDurationMinutes')

            if duration_seconds:
                cleanup_details["durationSeconds"] = int(duration_seconds) if isinstance(duration_seconds, bytes) else int(duration_seconds)
            if duration_minutes:
                cleanup_details["durationMinutes"] = int(duration_minutes) if isinstance(duration_minutes, bytes) else int(duration_minutes)

            logger.info("cleanup_duration_extracted",
                       duration_seconds=cleanup_details["durationSeconds"],
                       duration_minutes=cleanup_details["durationMinutes"])
        except Exception as duration_error:
            logger.warning("cleanup_duration_extraction_failed", error=str(duration_error))

        logger.info("cleanup_started", session_id=session_id, session_data=session_data)

        # 1. Revoke Celery task if exists
        task_id = session_data.get('celeryTaskId') or session_data.get('taskId')
        if task_id:
            try:
                celery_app.control.revoke(task_id, terminate=True)
                cleanup_details["celery_task_revoked"] = True
                logger.info("cleanup_celery_task_revoked", session_id=session_id, task_id=task_id)
            except Exception as e:
                error_msg = f"Failed to revoke task {task_id}: {e}"
                cleanup_details["errors"].append(error_msg)
                logger.error("cleanup_celery_revoke_failed", session_id=session_id, task_id=task_id, error=str(e), exc_info=True)

        # 2. Kill voice agent process
        pid_str = session_data.get('agentPid')
        if not pid_str:
            # Try alternate storage location
            pid_str = redis_client.get(f"agent:{session_id}:pid")

        if pid_str:
            try:
                pid = int(pid_str)

                # Get PGID for verification
                pgid_str = session_data.get('agentPgid')
                pgid = int(pgid_str) if pgid_str else None

                # Verify process group setup
                if pgid and pgid != pid:
                    logger.warning("cleanup_pgid_mismatch",
                                  session_id=session_id,
                                  pid=pid,
                                  pgid=pgid,
                                  warning="Process may not be a group leader")

                # First, give agent 3 seconds to self-terminate via disconnect handlers
                # Agent's on_participant_left triggers task.cancel() which should cleanly exit
                logger.info("cleanup_waiting_for_self_termination",
                           session_id=session_id,
                           pid=pid,
                           wait_seconds=3)
                await asyncio.sleep(3)

                # Check if agent self-terminated
                try:
                    os.kill(pid, 0)  # Check if process exists
                    logger.info("cleanup_agent_still_running_sending_sigterm",
                               session_id=session_id,
                               pid=pid)
                except ProcessLookupError:
                    logger.info("cleanup_agent_self_terminated",
                               session_id=session_id,
                               pid=pid)
                    cleanup_details["process_killed"] = True
                    cleanup_details["self_terminated"] = True
                    # Agent already dead, skip SIGTERM
                    return cleanup_details

                logger.info("cleanup_killing_process",
                           session_id=session_id,
                           pid=pid,
                           pgid=pgid,
                           is_group_leader=(pgid == pid if pgid else "unknown"),
                           signal="SIGTERM")

                # Send SIGTERM to entire process group
                try:
                    os.killpg(pid, signal.SIGTERM)  # Kill entire process group
                    cleanup_details["process_killed"] = True
                    cleanup_details["pgid"] = pgid

                    # Wait additional 5 seconds for graceful shutdown (async database operations)
                    # Agent needs time to: cancel pipeline, save transcripts to DB, close connections
                    await asyncio.sleep(5)

                    # Check if still alive, send SIGKILL
                    try:
                        os.kill(pid, 0)  # Just check if exists
                        logger.warning("cleanup_process_still_alive", session_id=session_id, pid=pid, signal="SIGKILL")
                        os.killpg(pid, signal.SIGKILL)  # Force kill entire process group
                    except ProcessLookupError:
                        logger.info("cleanup_process_terminated_gracefully", session_id=session_id, pid=pid)

                except ProcessLookupError:
                    logger.info("cleanup_process_already_dead", session_id=session_id, pid=pid)
                    cleanup_details["process_killed"] = True

            except Exception as e:
                error_msg = f"Failed to kill process {pid_str}: {e}"
                cleanup_details["errors"].append(error_msg)
                logger.error("cleanup_kill_process_failed", session_id=session_id, pid=pid_str, error=str(e), exc_info=True)

        # 3. Clean up Redis keys
        try:
            user_id = session_data.get('userId')

            # Delete session keys
            keys_to_delete = [
                f"session:{session_id}",
                f"session:{session_id}:config",  # Session-based config
                f"agent:{session_id}:pid",
                f"agent:{session_id}:logs",
                f"agent:{session_id}:health",
            ]

            if user_id:
                keys_to_delete.append(f"session:user:{user_id}")

            for key in keys_to_delete:
                redis_client.delete(key)

            # Remove from sets
            redis_client.srem('session:ready', session_id)
            redis_client.srem('session:starting', session_id)

            cleanup_details["redis_cleaned"] = True
            logger.info("cleanup_redis_cleaned", session_id=session_id, keys_deleted=len(keys_to_delete))

        except Exception as e:
            error_msg = f"Failed to clean Redis: {e}"
            cleanup_details["errors"].append(error_msg)
            logger.error("cleanup_redis_failed", session_id=session_id, error=str(e), exc_info=True)

        logger.info("cleanup_complete", session_id=session_id, details=cleanup_details)
        return cleanup_details

    except Exception as e:
        error_msg = f"Cleanup failed: {e}"
        cleanup_details["errors"].append(error_msg)
        logger.error("cleanup_failed", session_id=session_id, error=str(e), exc_info=True)
        return cleanup_details

# API Endpoints
@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "Voice Assistant Orchestrator",
        "status": "running",
        "version": "2.0.0",
        "type": "Python FastAPI",
        "features": ["session_tracking", "cleanup", "livekit_webhooks"]
    }

@app.post("/orchestrator/session/start", response_model=SessionStartResponse)
async def start_session(request: SessionStartRequest):
    """
    Start a voice assistant session

    Flow:
    1. Generate unique session ID (or use provided correlationToken)
    2. Generate LiveKit access token
    3. Store session state in Redis (with 2-hour TTL)
    4. Trigger Celery task to spawn voice agent
    5. Return token and session info to client

    Args:
        request: SessionStartRequest with userName, voiceId, openingLine, correlationToken (optional)

    Returns:
        SessionStartResponse with sessionId, token, serverUrl

    Raises:
        HTTPException: 500 if token generation or Redis fails
        HTTPException: 503 if Celery is unavailable
    """
    session_id = None
    try:
        # Use correlation token as session ID if provided, otherwise generate one
        if request.correlationToken:
            session_id = request.correlationToken
            logger.info("session_using_correlation_token", correlation_token=request.correlationToken)
        else:
            session_id = generate_session_id()

        # Validate and normalize voice ID
        requested_voice = request.voiceId or "Ashley"
        if requested_voice not in VALID_VOICES:
            logger.warning("invalid_voice_requested",
                          requested_voice=requested_voice,
                          valid_voices=VALID_VOICES,
                          fallback="Ashley")
            voice_id = "Ashley"
        else:
            voice_id = requested_voice

        # Use LogContext for request correlation
        with LogContext(session_id=session_id, user_name=request.userName):
            logger.info("session_start_requested",
                       voice_id=voice_id,
                       voice_requested=requested_voice,
                       voice_validated=voice_id == requested_voice,
                       opening_line=request.openingLine or 'default')

            # Generate LiveKit token
            try:
                token = generate_livekit_token(session_id, request.userName)
            except Exception as e:
                logger.error("session_token_generation_failed", error=str(e), exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"LiveKit token generation failed: {str(e)}"
                )

        # Store session config in Redis (for voice customization)
        # Use session-based storage so multiple sessions from same user don't conflict
        try:
            config_key = f"session:{session_id}:config"
            config_data = {
                'voiceId': voice_id,  # Use validated voice_id
                'userName': request.userName,
                'updatedAt': str(int(time.time()))
            }

            if request.openingLine:
                config_data['openingLine'] = request.openingLine
            if request.systemPrompt:
                config_data['systemPrompt'] = request.systemPrompt

            redis_client.hset(config_key, mapping=config_data)
            redis_client.expire(config_key, 14400)  # 4 hour TTL same as session
            logger.info("session_config_stored",
                       session_id=session_id,
                       user_name=request.userName,
                       voice_id=voice_id,
                       config_keys=list(config_data.keys()))
        except Exception as e:
            # Non-fatal, just log
            logger.warning("session_config_store_failed",
                          session_id=session_id,
                          user_name=request.userName,
                          error=str(e))

        # Trigger Celery task to spawn voice agent
        try:
            task = spawn_voice_agent.delay(
                session_id=session_id,
                user_id=request.userName
            )
            task_id = task.id
            logger.info("celery_task_queued", task_id=task_id)
        except Exception as e:
            logger.error("celery_task_failed", error=str(e), exc_info=True)
            raise HTTPException(
                status_code=503,
                detail=f"Failed to queue voice agent spawn task: {str(e)}"
            )

        # Store session state in Redis (2-hour TTL)
        try:
            session_key = f"session:{session_id}"
            session_data = {
                'userName': request.userName,
                'voiceId': request.voiceId or 'Ashley',
                'openingLine': request.openingLine or '',
                'systemPrompt': request.systemPrompt or '',
                'celeryTaskId': task_id,
                'status': 'starting',
                'startTime': str(int(time.time()))
            }
            redis_client.hset(session_key, mapping=session_data)
            redis_client.expire(session_key, 14400)  # 4 hours

            logger.info("session_state_stored", ttl_seconds=14400)
        except Exception as e:
            # Non-fatal for now, but log prominently
            logger.warning("session_state_store_failed", error=str(e),
                         warning="Cleanup may not work properly")

        logger.info("session_started",
                   voice_id=request.voiceId or 'Ashley',
                   opening_line=request.openingLine or 'default')

        return SessionStartResponse(
            success=True,
            sessionId=session_id,
            token=token,
            serverUrl=LIVEKIT_URL,
            roomName=session_id,
            message="Session created. Voice agent is being spawned."
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error("session_start_unexpected_error", session_id=session_id, error=str(e), exc_info=True)
        # Attempt cleanup if session was partially created
        if session_id:
            try:
                await cleanup_session(session_id)
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to start session: {str(e)}")

@app.post("/orchestrator/session/end", response_model=SessionEndResponse)
async def end_session(request: SessionEndRequest):
    """
    End a voice assistant session

    Properly cleans up:
    1. Revokes Celery task if still running
    2. Sends SIGTERM (then SIGKILL) to voice agent process
    3. Cleans up all Redis keys for this session

    Args:
        request: SessionEndRequest with sessionId

    Returns:
        SessionEndResponse with success status and cleanup details

    Raises:
        HTTPException: 404 if session not found
        HTTPException: 500 if cleanup fails
    """
    try:
        session_id = request.sessionId

        with LogContext(session_id=session_id):
            # Check if session exists
            session_exists = redis_client.exists(f"session:{session_id}")
            if not session_exists:
                logger.warning("session_not_found")
                raise HTTPException(
                    status_code=404,
                    detail=f"Session {session_id} not found"
                )

            logger.info("session_end_requested")

            # Perform cleanup
            cleanup_details = await cleanup_session(session_id)

            # Check if cleanup had errors
            if cleanup_details["errors"]:
                logger.warning("session_ended_with_errors", errors=cleanup_details['errors'])
                return SessionEndResponse(
                    success=True,  # Still return success if partial cleanup worked
                    message=f"Session {session_id} ended with warnings",
                    details=cleanup_details
                )

            logger.info("session_ended_successfully")
            return SessionEndResponse(
                success=True,
                message=f"Session {session_id} ended and cleaned up",
                details=cleanup_details
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("session_end_failed", session_id=request.sessionId, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to end session: {str(e)}"
        )

@app.post("/webhook/livekit")
async def livekit_webhook(request: Request, x_livekit_signature: Optional[str] = Header(None)):
    """
    LiveKit webhook endpoint

    Handles events:
    - participant_left: User disconnected from room
    - room_finished: Room closed

    When disconnect detected, automatically cleans up the voice agent session.

    Security:
    - Verifies webhook signature using LIVEKIT_API_SECRET

    Returns:
        200 OK if processed
        401 Unauthorized if signature invalid
        400 Bad Request if payload invalid
    """
    try:
        # Get raw body for signature verification
        body = await request.body()

        # Verify signature
        if x_livekit_signature:
            if not verify_livekit_webhook(body, x_livekit_signature):
                logger.warning("webhook_invalid_signature")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        else:
            logger.warning("webhook_no_signature", warning="Allowing for development")

        # Parse event
        try:
            event_data = json.loads(body.decode('utf-8'))
        except Exception as e:
            logger.error("webhook_invalid_json", error=str(e), exc_info=True)
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        event_type = event_data.get('event')
        room_data = event_data.get('room', {})
        participant_data = event_data.get('participant', {})

        room_name = room_data.get('name') or room_data.get('id')
        participant_identity = participant_data.get('identity')

        logger.info("webhook_event_received",
                   event_type=event_type,
                   room=room_name,
                   participant=participant_identity)

        # Handle disconnect events
        if event_type in ['participant_left', 'room_finished']:
            if room_name and room_name.startswith('session_'):
                session_id = room_name

                with LogContext(session_id=session_id):
                    logger.info("webhook_disconnect_detected", event_type=event_type)

                    # Trigger cleanup asynchronously
                    try:
                        cleanup_details = await cleanup_session(session_id)
                        logger.info("webhook_cleanup_initiated", cleanup_details=cleanup_details)
                    except Exception as e:
                        logger.error("webhook_cleanup_failed", error=str(e), exc_info=True)

        return {"status": "ok", "event": event_type}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("webhook_processing_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")

@app.get("/api/debug/session/{session_id}/processes")
async def debug_session_processes(session_id: str):
    """
    Debug endpoint to inspect process group tracking for a session.

    Returns detailed information about:
    - Session existence and data
    - PID and PGID from Redis
    - Process and process group alive status
    - Child processes in the process group

    Args:
        session_id: Session identifier

    Returns:
        JSON with process tracking details

    Raises:
        HTTPException: 404 if session not found
    """
    try:
        import subprocess as sp

        # Get session data
        session_key = f"session:{session_id}"
        session_data = redis_client.hgetall(session_key)

        if not session_data:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )

        # Extract PID and PGID
        pid_str = session_data.get('agentPid')
        pgid_str = session_data.get('agentPgid')

        if not pid_str:
            # Try alternate location
            pid_str = redis_client.get(f"agent:{session_id}:pid")

        result = {
            "session_id": session_id,
            "pid": int(pid_str) if pid_str else None,
            "pgid": int(pgid_str) if pgid_str else None,
            "is_group_leader": None,
            "is_process_alive": False,
            "is_group_alive": False,
            "child_processes": [],
            "session_data": session_data,
            "errors": []
        }

        if not pid_str:
            result["errors"].append("No PID found in Redis")
            return result

        pid = int(pid_str)
        pgid = int(pgid_str) if pgid_str else None

        # Check if PID is group leader
        if pgid:
            result["is_group_leader"] = (pgid == pid)

        # Check if process is alive
        try:
            os.kill(pid, 0)  # Signal 0 just checks existence
            result["is_process_alive"] = True
        except (ProcessLookupError, OSError) as e:
            result["is_process_alive"] = False
            result["errors"].append(f"Process {pid} not alive: {e}")

        # Check if process group is alive
        try:
            os.killpg(pid, 0)  # Signal 0 just checks existence
            result["is_group_alive"] = True
        except (ProcessLookupError, OSError, PermissionError) as e:
            result["is_group_alive"] = False
            result["errors"].append(f"Process group {pid} check failed: {e}")

        # Get child processes using ps command
        if result["is_process_alive"]:
            try:
                # Use ps to find all processes in the same process group
                # -g: select by process group ID
                # -o: output format
                ps_result = sp.run(
                    ['ps', '-g', str(pid), '-o', 'pid,ppid,pgid,cmd'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )

                if ps_result.returncode == 0:
                    lines = ps_result.stdout.strip().split('\n')
                    if len(lines) > 1:  # Skip header
                        for line in lines[1:]:
                            parts = line.strip().split(None, 3)
                            if len(parts) >= 4:
                                result["child_processes"].append({
                                    "pid": int(parts[0]),
                                    "ppid": int(parts[1]),
                                    "pgid": int(parts[2]),
                                    "cmd": parts[3]
                                })
                else:
                    result["errors"].append(f"ps command failed: {ps_result.stderr}")

            except sp.TimeoutExpired:
                result["errors"].append("ps command timed out")
            except FileNotFoundError:
                result["errors"].append("ps command not available")
            except Exception as e:
                result["errors"].append(f"Failed to get child processes: {e}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("debug_endpoint_error", session_id=session_id, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Debug endpoint failed: {str(e)}"
        )

@app.get("/orchestrator/health")
async def health_check():
    """Detailed health check"""
    redis_healthy = False
    try:
        redis_client.ping()
        redis_healthy = True
    except Exception as e:
        logger.error("health_redis_check_failed", error=str(e), exc_info=True)

    status = "healthy" if redis_healthy else "degraded"
    logger.info("health_check", status=status, redis_connected=redis_healthy)

    return {
        "status": status,
        "livekit_url": LIVEKIT_URL,
        "livekit_configured": bool(LIVEKIT_API_KEY and LIVEKIT_API_SECRET),
        "redis_connected": redis_healthy,
        "celery_available": True  # We assume Celery is running
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

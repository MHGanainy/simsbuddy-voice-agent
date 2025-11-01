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
    print(f"[Redis] Connected to {REDIS_URL}")
except Exception as e:
    print(f"[Redis] ERROR: Failed to connect to Redis: {e}")
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

# Request/Response models
class SessionStartRequest(BaseModel):
    userName: str
    voiceId: Optional[str] = "Ashley"
    openingLine: Optional[str] = None

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
        print(f"[Error] LiveKit token generation failed: {e}")
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
        print(f"[Webhook] Signature verification error: {e}")
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
        "errors": []
    }

    try:
        # Get session data
        session_key = f"session:{session_id}"
        session_data = redis_client.hgetall(session_key)

        if not session_data:
            print(f"[Cleanup] No session data found for {session_id}")
            cleanup_details["errors"].append("Session not found")
            return cleanup_details

        print(f"[Cleanup] Cleaning up session {session_id}: {session_data}")

        # 1. Revoke Celery task if exists
        task_id = session_data.get('celeryTaskId') or session_data.get('taskId')
        if task_id:
            try:
                celery_app.control.revoke(task_id, terminate=True)
                cleanup_details["celery_task_revoked"] = True
                print(f"[Cleanup] Revoked Celery task: {task_id}")
            except Exception as e:
                error_msg = f"Failed to revoke task {task_id}: {e}"
                cleanup_details["errors"].append(error_msg)
                print(f"[Cleanup] {error_msg}")

        # 2. Kill voice agent process
        pid_str = session_data.get('agentPid')
        if not pid_str:
            # Try alternate storage location
            pid_str = redis_client.get(f"agent:{session_id}:pid")

        if pid_str:
            try:
                pid = int(pid_str)
                print(f"[Cleanup] Killing process {pid} (SIGTERM)")

                # Send SIGTERM first
                try:
                    os.kill(pid, signal.SIGTERM)
                    cleanup_details["process_killed"] = True

                    # Wait 5 seconds for graceful shutdown (async to avoid blocking)
                    await asyncio.sleep(5)

                    # Check if still alive, send SIGKILL
                    try:
                        os.kill(pid, 0)  # Just check if exists
                        print(f"[Cleanup] Process {pid} still alive, sending SIGKILL")
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        print(f"[Cleanup] Process {pid} terminated gracefully")

                except ProcessLookupError:
                    print(f"[Cleanup] Process {pid} already dead")
                    cleanup_details["process_killed"] = True

            except Exception as e:
                error_msg = f"Failed to kill process {pid_str}: {e}"
                cleanup_details["errors"].append(error_msg)
                print(f"[Cleanup] {error_msg}")

        # 3. Clean up Redis keys
        try:
            user_id = session_data.get('userId')

            # Delete session keys
            keys_to_delete = [
                f"session:{session_id}",
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
            redis_client.srem('pool:ready', session_id)

            cleanup_details["redis_cleaned"] = True
            print(f"[Cleanup] Cleaned up Redis keys for {session_id}")

        except Exception as e:
            error_msg = f"Failed to clean Redis: {e}"
            cleanup_details["errors"].append(error_msg)
            print(f"[Cleanup] {error_msg}")

        print(f"[Cleanup] Session {session_id} cleanup complete")
        return cleanup_details

    except Exception as e:
        error_msg = f"Cleanup failed: {e}"
        cleanup_details["errors"].append(error_msg)
        print(f"[Cleanup] ERROR: {error_msg}")
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

@app.post("/api/session/start", response_model=SessionStartResponse)
async def start_session(request: SessionStartRequest):
    """
    Start a voice assistant session

    Flow:
    1. Generate unique session ID
    2. Generate LiveKit access token
    3. Store session state in Redis (with 2-hour TTL)
    4. Trigger Celery task to spawn voice agent
    5. Return token and session info to client

    Args:
        request: SessionStartRequest with userName, voiceId, openingLine

    Returns:
        SessionStartResponse with sessionId, token, serverUrl

    Raises:
        HTTPException: 500 if token generation or Redis fails
        HTTPException: 503 if Celery is unavailable
    """
    session_id = None
    try:
        # Generate session ID
        session_id = generate_session_id()

        # Generate LiveKit token
        try:
            token = generate_livekit_token(session_id, request.userName)
        except Exception as e:
            print(f"[Session] Token generation failed for {session_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"LiveKit token generation failed: {str(e)}"
            )

        # Store user config in Redis (for voice customization)
        try:
            if request.voiceId or request.openingLine:
                config_key = f"user:{request.userName}:config"
                config_data = {}
                if request.voiceId:
                    config_data['voiceId'] = request.voiceId
                if request.openingLine:
                    config_data['openingLine'] = request.openingLine
                config_data['updatedAt'] = str(int(time.time()))

                redis_client.hset(config_key, mapping=config_data)
                print(f"[Session] Stored user config for {request.userName}")
        except Exception as e:
            # Non-fatal, just log
            print(f"[Session] Warning: Failed to store user config: {e}")

        # Trigger Celery task to spawn voice agent
        try:
            task = spawn_voice_agent.delay(
                session_id=session_id,
                user_id=request.userName,
                prewarm=False
            )
            task_id = task.id
            print(f"[Session] Celery task queued: {task_id}")
        except Exception as e:
            print(f"[Session] Celery task failed for {session_id}: {e}")
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
                'celeryTaskId': task_id,
                'status': 'starting',
                'startTime': str(int(time.time()))
            }
            redis_client.hset(session_key, mapping=session_data)
            redis_client.expire(session_key, 7200)  # 2 hours

            print(f"[Session] Session state stored in Redis: {session_id}")
        except Exception as e:
            # Non-fatal for now, but log prominently
            print(f"[Session] WARNING: Failed to store session in Redis: {e}")
            print(f"[Session] Cleanup may not work properly for {session_id}")

        print(f"[Session] Started session {session_id} for user {request.userName}")
        print(f"[Session] Voice: {request.voiceId or 'Ashley'}, Opening line: {request.openingLine or 'default'}")

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
        print(f"[Error] Unexpected error in start_session: {str(e)}")
        # Attempt cleanup if session was partially created
        if session_id:
            try:
                await cleanup_session(session_id)
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to start session: {str(e)}")

@app.post("/api/session/end", response_model=SessionEndResponse)
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

        # Check if session exists
        session_exists = redis_client.exists(f"session:{session_id}")
        if not session_exists:
            print(f"[Session] Session {session_id} not found")
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )

        print(f"[Session] Ending session {session_id}")

        # Perform cleanup
        cleanup_details = await cleanup_session(session_id)

        # Check if cleanup had errors
        if cleanup_details["errors"]:
            print(f"[Session] Cleanup completed with errors: {cleanup_details['errors']}")
            return SessionEndResponse(
                success=True,  # Still return success if partial cleanup worked
                message=f"Session {session_id} ended with warnings",
                details=cleanup_details
            )

        print(f"[Session] Session {session_id} ended successfully")
        return SessionEndResponse(
            success=True,
            message=f"Session {session_id} ended and cleaned up",
            details=cleanup_details
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Error] Failed to end session {request.sessionId}: {str(e)}")
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
                print(f"[Webhook] Invalid signature")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        else:
            print(f"[Webhook] WARNING: No signature provided (allowing for development)")

        # Parse event
        try:
            event_data = json.loads(body.decode('utf-8'))
        except Exception as e:
            print(f"[Webhook] Invalid JSON payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        event_type = event_data.get('event')
        room_data = event_data.get('room', {})
        participant_data = event_data.get('participant', {})

        room_name = room_data.get('name') or room_data.get('id')
        participant_identity = participant_data.get('identity')

        print(f"[Webhook] Received event: {event_type}, room: {room_name}, participant: {participant_identity}")

        # Handle disconnect events
        if event_type in ['participant_left', 'room_finished']:
            if room_name and room_name.startswith('session_'):
                session_id = room_name

                print(f"[Webhook] Disconnect detected for session {session_id}")

                # Trigger cleanup asynchronously
                try:
                    cleanup_details = await cleanup_session(session_id)
                    print(f"[Webhook] Cleanup initiated for {session_id}: {cleanup_details}")
                except Exception as e:
                    print(f"[Webhook] Cleanup failed for {session_id}: {e}")

        return {"status": "ok", "event": event_type}

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Webhook] Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")

@app.get("/health")
async def health_check():
    """Detailed health check"""
    redis_healthy = False
    try:
        redis_client.ping()
        redis_healthy = True
    except Exception as e:
        print(f"[Health] Redis check failed: {e}")

    return {
        "status": "healthy" if redis_healthy else "degraded",
        "livekit_url": LIVEKIT_URL,
        "livekit_configured": bool(LIVEKIT_API_KEY and LIVEKIT_API_SECRET),
        "redis_connected": redis_healthy,
        "celery_available": True  # We assume Celery is running
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

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

# Import Celery and worker tasks
from celery import Celery
from backend.services.worker.tasks import spawn_voice_agent

# Import structured logging
from backend.shared.logging_config import setup_logging

# Import credit billing service
from backend.shared.services.credit_service import CreditService, CreditDeductionResult

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
    logger.info(f"redis_connected redis_url={REDIS_URL}")
except Exception as e:
    logger.error(f"redis_connection_failed redis_url={REDIS_URL} error={str(e)}", exc_info=True)
    raise

# Celery app (for task revocation)
celery_app = Celery('voice_agent_tasks')
celery_app.config_from_object('backend.services.orchestrator.celeryconfig')

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
    initialCreditDeducted: Optional[bool] = None
    creditsRemaining: Optional[int] = None
    minuteBilled: Optional[int] = None

class SessionEndRequest(BaseModel):
    sessionId: str

class SessionEndResponse(BaseModel):
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None

class HeartbeatRequest(BaseModel):
    sessionId: str

class HeartbeatResponse(BaseModel):
    status: str  # "ok", "stop", or "error"
    message: Optional[str] = None
    minute_billed: Optional[int] = None
    credits_remaining: Optional[int] = None
    already_billed: Optional[bool] = None
    reason: Optional[str] = None  # For "stop" status

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
        logger.error(f"livekit_token_generation_failed error={str(e)}", exc_info=True)
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
        logger.error(f"webhook_signature_verification_error error={str(e)}", exc_info=True)
        return False

async def terminate_session_insufficient_credits(session_id: str) -> Dict[str, Any]:
    """
    Terminate session due to insufficient credits.

    This is called by the billing system when a student runs out of credits
    during an active conversation.

    Args:
        session_id: Session to terminate

    Returns:
        dict with termination details
    """
    logger.warning(f"session_terminating_insufficient_credits session_id={session_id} reason='Student ran out of credits'")

    # Update session status to indicate credit depletion
    try:
        redis_client.hset(f'session:{session_id}', mapping={
            'status': 'terminated',
            'terminationReason': 'insufficient_credits',
            'terminatedAt': int(time.time())
        })
        logger.info(f"session_marked_terminated session_id={session_id}")
    except Exception as e:
        logger.error(f"session_termination_status_update_failed session_id={session_id} error={str(e)}")

    # Call standard cleanup
    cleanup_result = await cleanup_session(session_id)
    cleanup_result["termination_reason"] = "insufficient_credits"

    return cleanup_result


async def wait_for_agent_cleanup_complete(session_id: str, max_wait_seconds: float = 10.0, poll_interval: float = 0.5) -> Dict[str, Any]:
    """
    Wait for the agent to signal cleanup completion.

    The agent sets a Redis key after saving transcripts to the database.
    This function polls for that key to ensure we don't return before
    the transcript is persisted.

    Args:
        session_id: Session to wait for
        max_wait_seconds: Maximum time to wait (default 10s)
        poll_interval: Time between polls (default 0.5s)

    Returns:
        dict with completion status and details
    """
    cleanup_key = f"session:{session_id}:cleanup_complete"
    start_time = time.time()
    attempts = 0

    while (time.time() - start_time) < max_wait_seconds:
        attempts += 1
        try:
            cleanup_data = redis_client.hgetall(cleanup_key)

            if cleanup_data:
                # Decode bytes if needed
                if cleanup_data and isinstance(list(cleanup_data.keys())[0], bytes):
                    cleanup_data = {
                        k.decode() if isinstance(k, bytes) else k:
                        v.decode() if isinstance(v, bytes) else v
                        for k, v in cleanup_data.items()
                    }

                transcript_saved = cleanup_data.get('transcript_saved') == 'true'
                logger.info(
                    f"agent_cleanup_signal_received session_id={session_id} "
                    f"transcript_saved={transcript_saved} attempts={attempts} "
                    f"wait_time={time.time() - start_time:.2f}s"
                )

                # Clean up the signal key
                redis_client.delete(cleanup_key)

                return {
                    "received": True,
                    "transcript_saved": transcript_saved,
                    "attempts": attempts,
                    "wait_time": time.time() - start_time
                }

        except Exception as e:
            logger.warning(f"agent_cleanup_signal_check_error session_id={session_id} error={str(e)}")

        await asyncio.sleep(poll_interval)

    logger.warning(
        f"agent_cleanup_signal_timeout session_id={session_id} "
        f"max_wait={max_wait_seconds}s attempts={attempts}"
    )

    return {
        "received": False,
        "transcript_saved": False,
        "attempts": attempts,
        "wait_time": max_wait_seconds,
        "timeout": True
    }


async def cleanup_session(session_id: str) -> Dict[str, Any]:
    """
    Clean up session resources (async to avoid blocking API)

    Steps:
    1. Get session data from Redis
    2. Revoke Celery task if exists
    3. Kill voice agent process (SIGTERM then SIGKILL)
    4. Wait for agent cleanup completion signal (transcript saved)
    5. Remove all Redis keys for this session

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
            logger.warning(f"cleanup_no_session_found session_id={session_id}")
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

            logger.info(f"cleanup_duration_extracted duration_seconds={cleanup_details['durationSeconds']} duration_minutes={cleanup_details['durationMinutes']}")
        except Exception as duration_error:
            logger.warning(f"cleanup_duration_extraction_failed error={str(duration_error)}")

        # Reconcile billing before cleanup
        if cleanup_details["durationMinutes"] > 0:
            try:
                from backend.shared.services import CreditService

                logger.info(f"cleanup_billing_reconciliation_started session_id={session_id} total_minutes={cleanup_details['durationMinutes']}")

                reconcile_result = await CreditService.reconcile_session(
                    session_id,
                    cleanup_details["durationMinutes"]
                )

                cleanup_details["billing_reconciled"] = reconcile_result.get("success", False)
                cleanup_details["minutes_billed"] = reconcile_result.get("total_billed", 0)

                if reconcile_result.get("success"):
                    logger.info(f"cleanup_billing_reconciliation_success total_billed={reconcile_result.get('total_billed')} minutes_billed_now={reconcile_result.get('minutes_billed')}")
                else:
                    logger.warning(f"cleanup_billing_reconciliation_failed message={reconcile_result.get('message')} failed_minutes={reconcile_result.get('failed_minutes', [])}")
                    cleanup_details["errors"].append(f"Billing reconciliation incomplete: {reconcile_result.get('message')}")

            except Exception as billing_error:
                logger.error(f"cleanup_billing_reconciliation_error error={str(billing_error)}", exc_info=True)
                cleanup_details["errors"].append(f"Billing reconciliation error: {str(billing_error)}")

        logger.info(f"cleanup_started session_id={session_id} session_data={session_data}")

        # 1. Revoke Celery task if exists
        task_id = session_data.get('celeryTaskId') or session_data.get('taskId')
        if task_id:
            try:
                celery_app.control.revoke(task_id, terminate=True)
                cleanup_details["celery_task_revoked"] = True
                logger.info(f"cleanup_celery_task_revoked session_id={session_id} task_id={task_id}")
            except Exception as e:
                error_msg = f"Failed to revoke task {task_id}: {e}"
                cleanup_details["errors"].append(error_msg)
                logger.error(f"cleanup_celery_revoke_failed session_id={session_id} task_id={task_id} error={str(e)}", exc_info=True)

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
                    logger.warning(f"cleanup_pgid_mismatch session_id={session_id} pid={pid} pgid={pgid} warning='Process may not be a group leader'")

                # First, give agent 3 seconds to self-terminate via disconnect handlers
                # Agent's on_participant_left triggers task.cancel() which should cleanly exit
                logger.info(f"cleanup_waiting_for_self_termination session_id={session_id} pid={pid} wait_seconds=3")
                await asyncio.sleep(3)

                # Check if agent self-terminated
                agent_self_terminated = False
                try:
                    os.kill(pid, 0)  # Check if process exists
                    logger.info(f"cleanup_agent_still_running_sending_sigterm session_id={session_id} pid={pid}")
                except ProcessLookupError:
                    logger.info(f"cleanup_agent_self_terminated session_id={session_id} pid={pid}")
                    cleanup_details["process_killed"] = True
                    cleanup_details["self_terminated"] = True
                    agent_self_terminated = True

                    # CRITICAL: Wait for agent cleanup completion signal
                    # Agent may still be saving transcripts to database even though process appears dead
                    cleanup_signal = await wait_for_agent_cleanup_complete(session_id, max_wait_seconds=10.0)
                    cleanup_details["cleanup_signal"] = cleanup_signal

                    if cleanup_signal.get("received"):
                        logger.info(
                            f"cleanup_agent_signal_received session_id={session_id} "
                            f"transcript_saved={cleanup_signal.get('transcript_saved')} "
                            f"wait_time={cleanup_signal.get('wait_time', 0):.2f}s"
                        )
                    else:
                        logger.warning(
                            f"cleanup_agent_signal_timeout session_id={session_id} "
                            f"waited={cleanup_signal.get('wait_time', 0):.2f}s "
                            f"warning='Proceeding without confirmation'"
                        )

                # Only send SIGTERM if agent didn't self-terminate
                if not agent_self_terminated:
                    logger.info(f"cleanup_killing_process session_id={session_id} pid={pid} pgid={pgid} is_group_leader={pgid == pid if pgid else 'unknown'} signal='SIGTERM'")

                    # Send SIGTERM to entire process group
                    try:
                        os.killpg(pid, signal.SIGTERM)  # Kill entire process group
                        cleanup_details["process_killed"] = True
                        cleanup_details["pgid"] = pgid

                        # Wait for agent cleanup completion signal (with SIGTERM case)
                        # Agent needs time to: cancel pipeline, save transcripts to DB, close connections
                        cleanup_signal = await wait_for_agent_cleanup_complete(session_id, max_wait_seconds=10.0)
                        cleanup_details["cleanup_signal"] = cleanup_signal

                        if cleanup_signal.get("received"):
                            logger.info(
                                f"cleanup_agent_signal_received session_id={session_id} "
                                f"transcript_saved={cleanup_signal.get('transcript_saved')} "
                                f"wait_time={cleanup_signal.get('wait_time', 0):.2f}s"
                            )
                        else:
                            # Signal not received, wait additional time as fallback
                            logger.warning(
                                f"cleanup_agent_signal_timeout session_id={session_id} "
                                f"warning='Waiting additional 3s as fallback'"
                            )
                            await asyncio.sleep(3)

                        # Check if still alive, send SIGKILL
                        try:
                            os.kill(pid, 0)  # Just check if exists
                            logger.warning(f"cleanup_process_still_alive session_id={session_id} pid={pid} signal='SIGKILL'")
                            os.killpg(pid, signal.SIGKILL)  # Force kill entire process group
                        except ProcessLookupError:
                            logger.info(f"cleanup_process_terminated_gracefully session_id={session_id} pid={pid}")

                    except ProcessLookupError:
                        logger.info(f"cleanup_process_already_dead session_id={session_id} pid={pid}")
                        cleanup_details["process_killed"] = True

            except Exception as e:
                error_msg = f"Failed to kill process {pid_str}: {e}"
                cleanup_details["errors"].append(error_msg)
                logger.error(f"cleanup_kill_process_failed session_id={session_id} pid={pid_str} error={str(e)}", exc_info=True)

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
            logger.info(f"cleanup_redis_cleaned session_id={session_id} keys_deleted={len(keys_to_delete)}")

        except Exception as e:
            error_msg = f"Failed to clean Redis: {e}"
            cleanup_details["errors"].append(error_msg)
            logger.error(f"cleanup_redis_failed session_id={session_id} error={str(e)}", exc_info=True)

        logger.info(f"cleanup_complete session_id={session_id} details={cleanup_details}")
        return cleanup_details

    except Exception as e:
        error_msg = f"Cleanup failed: {e}"
        cleanup_details["errors"].append(error_msg)
        logger.error(f"cleanup_failed session_id={session_id} error={str(e)}", exc_info=True)
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
            logger.info(f"session_using_correlation_token correlation_token={request.correlationToken}")
        else:
            session_id = generate_session_id()

        # Validate and normalize voice ID
        requested_voice = request.voiceId or "Ashley"
        if requested_voice not in VALID_VOICES:
            logger.warning(f"invalid_voice_requested requested_voice={requested_voice} valid_voices={VALID_VOICES} fallback='Ashley'")
            voice_id = "Ashley"
        else:
            voice_id = requested_voice

        # Removed LogContext wrapper
        if True:  # Removed LogContext wrapper
            logger.info(f"session_start_requested session_id={session_id} user_name={request.userName} voice_id={voice_id} voice_requested={requested_voice} voice_validated={voice_id == requested_voice} opening_line={request.openingLine or 'default'}")

            # ==================== CREDIT CHECK AND DEDUCTION (Minute 0) ====================
            # Check and deduct 1 credit BEFORE creating session
            billing_result = None
            try:
                # Get student_id from SimulationAttempt using correlation_token
                student_id = await CreditService.get_student_id_from_session(session_id)

                if not student_id:
                    logger.error(f"session_start_student_not_found correlation_token={session_id}")
                    raise HTTPException(
                        status_code=404,
                        detail="No student found for this simulation attempt"
                    )

                # Check if student has at least 1 credit
                has_credits = await CreditService.check_sufficient_credits(student_id, 1)

                if not has_credits:
                    logger.warning(f"session_start_insufficient_credits student_id={student_id}")
                    raise HTTPException(
                        status_code=402,  # Payment Required
                        detail="Insufficient credits to start session. You need at least 1 credit."
                    )

                # Deduct 1 credit for minute 0 (initial charge)
                logger.info(f"session_start_billing_minute_0 student_id={student_id}")

                billing_result = await CreditService.deduct_minute(session_id, minute_number=0)

                if billing_result['result'] != CreditDeductionResult.SUCCESS:
                    logger.error(f"session_start_billing_failed student_id={student_id} result={billing_result['result'].value} message={billing_result.get('message')}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to process initial credit charge: {billing_result.get('message')}"
                    )

                logger.info(f"session_start_billing_success student_id={student_id} credits_remaining={billing_result.get('balance_after')} minute_billed=0")

            except HTTPException:
                # Re-raise HTTP exceptions (404, 402, 500)
                raise
            except Exception as e:
                logger.error(f"session_start_billing_error error={str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Credit system error: {str(e)}"
                )
            # ==================== END CREDIT CHECK ====================

            # Generate LiveKit token
            try:
                token = generate_livekit_token(session_id, request.userName)
            except Exception as e:
                logger.error(f"session_token_generation_failed error={str(e)}", exc_info=True)
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
            logger.info(f"session_config_stored session_id={session_id} user_name={request.userName} voice_id={voice_id} config_keys={list(config_data.keys())}")
        except Exception as e:
            # Non-fatal, just log
            logger.warning(f"session_config_store_failed session_id={session_id} user_name={request.userName} error={str(e)}")

        # Trigger Celery task to spawn voice agent
        try:
            task = spawn_voice_agent.delay(
                session_id=session_id,
                user_id=request.userName
            )
            task_id = task.id
            logger.info(f"celery_task_queued task_id={task_id}")
        except Exception as e:
            logger.error(f"celery_task_failed error={str(e)}", exc_info=True)
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

            logger.info(f"session_state_stored ttl_seconds=14400")
        except Exception as e:
            # Non-fatal for now, but log prominently
            logger.warning(f"session_state_store_failed error={str(e)} warning='Cleanup may not work properly'")

        logger.info(f"session_started voice_id={request.voiceId or 'Ashley'} opening_line={request.openingLine or 'default'}")

        return SessionStartResponse(
            success=True,
            sessionId=session_id,
            token=token,
            serverUrl=LIVEKIT_URL,
            roomName=session_id,
            message="Session created. Voice agent is being spawned.",
            initialCreditDeducted=True,
            creditsRemaining=billing_result.get('balance_after') if billing_result else None,
            minuteBilled=0
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"session_start_unexpected_error session_id={session_id} error={str(e)}", exc_info=True)
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

        if True:  # Removed LogContext wrapper
            # Check if session exists
            session_exists = redis_client.exists(f"session:{session_id}")
            if not session_exists:
                logger.warning(f"session_not_found session_id={session_id}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Session {session_id} not found"
                )

            logger.info(f"session_end_requested session_id={session_id}")

            # Perform cleanup
            cleanup_details = await cleanup_session(session_id)

            # Check if cleanup had errors
            if cleanup_details["errors"]:
                logger.warning(f"session_ended_with_errors session_id={session_id} errors={cleanup_details['errors']}")
                return SessionEndResponse(
                    success=True,  # Still return success if partial cleanup worked
                    message=f"Session {session_id} ended with warnings",
                    details=cleanup_details
                )

            logger.info(f"session_ended_successfully session_id={session_id}")
            return SessionEndResponse(
                success=True,
                message=f"Session {session_id} ended and cleaned up",
                details=cleanup_details
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"session_end_failed session_id={request.sessionId} error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to end session: {str(e)}"
        )

@app.post("/api/session/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(request: HeartbeatRequest):
    """
    Heartbeat endpoint for credit billing.

    Voice agents call this endpoint every 60 seconds to:
    1. Report they are still active
    2. Trigger per-minute credit billing
    3. Receive instructions (continue or stop due to insufficient credits)

    Args:
        request: HeartbeatRequest with sessionId

    Returns:
        HeartbeatResponse with status:
        - "ok": Continue conversation, minute billed successfully
        - "stop": Stop conversation, insufficient credits
        - "error": Error occurred

    Raises:
        HTTPException: 404 if session not found
        HTTPException: 500 if billing fails unexpectedly
    """
    session_id = request.sessionId

    try:
        if True:  # Removed LogContext wrapper
            logger.debug(f"heartbeat_received session_id={session_id}")

            # Get session data from Redis
            session_data = redis_client.hgetall(f"session:{session_id}")

            if not session_data:
                logger.warning(f"heartbeat_session_not_found session_id={session_id}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Session {session_id} not found"
                )

            # Decode bytes if needed
            if session_data and isinstance(list(session_data.keys())[0], bytes):
                session_data = {
                    k.decode() if isinstance(k, bytes) else k:
                    v.decode() if isinstance(v, bytes) else v
                    for k, v in session_data.items()
                }

            # Get conversation start time
            conversation_start_time = session_data.get('conversationStartTime')
            if not conversation_start_time:
                logger.warning(f"heartbeat_no_conversation_start_time session_id={session_id}")
                return HeartbeatResponse(
                    status="error",
                    message="No conversation start time found"
                )

            # Calculate which minute of conversation this is
            start_time = int(conversation_start_time)
            elapsed_seconds = int(time.time()) - start_time
            current_minute = elapsed_seconds // 60  # 0, 1, 2, 3... (minute 0 already billed at session start)

            # Use current_minute directly for billing
            # Minute 0 was billed at session start, so heartbeat bills 1, 2, 3...
            billing_minute = current_minute

            logger.debug(f"heartbeat_timing session_id={session_id} elapsed_seconds={elapsed_seconds} current_minute={current_minute} billing_minute={billing_minute}")

            # Don't bill if we're still in minute 0 (< 60 seconds elapsed)
            # Minute 0 was already billed at session start
            if current_minute == 0:
                logger.debug(f"heartbeat_first_minute_skip session_id={session_id}")
                return HeartbeatResponse(
                    status="ok",
                    message="Minute 0 already billed at session start"
                )

            # Attempt to bill this minute
            try:
                result = await CreditService.deduct_minute(session_id, billing_minute)

                # Check result status
                if result['result'] == CreditDeductionResult.SUCCESS:
                    logger.info(f"heartbeat_billing_success session_id={session_id} minute={billing_minute} balance_after={result.get('balance_after')}")

                    return HeartbeatResponse(
                        status="ok",
                        message=f"Minute {billing_minute} billed successfully",
                        minute_billed=billing_minute,
                        credits_remaining=result.get('balance_after'),
                        already_billed=False
                    )

                elif result['result'] == CreditDeductionResult.ALREADY_BILLED:
                    logger.debug(f"heartbeat_already_billed session_id={session_id} minute={billing_minute}")

                    return HeartbeatResponse(
                        status="ok",
                        message=f"Minute {billing_minute} already billed",
                        minute_billed=billing_minute,
                        already_billed=True
                    )

                elif result['result'] == CreditDeductionResult.INSUFFICIENT_CREDITS:
                    # Insufficient credits - tell agent to stop
                    logger.warning(f"heartbeat_insufficient_credits session_id={session_id} minute={billing_minute} balance={result.get('balance', 0)}")

                    # Trigger session termination (async, don't wait)
                    asyncio.create_task(terminate_session_insufficient_credits(session_id))

                    return HeartbeatResponse(
                        status="stop",
                        reason="insufficient_credits",
                        message=f"Insufficient credits to continue (minute {billing_minute})",
                        minute_billed=billing_minute
                    )

                else:
                    # Other errors (session not found, student not found, etc.)
                    logger.error(f"heartbeat_billing_failed session_id={session_id} result={result['result'].value} message={result.get('message')}")

                    return HeartbeatResponse(
                        status="error",
                        message=f"Billing failed: {result.get('message')}"
                    )

            except Exception as billing_error:
                logger.error(f"heartbeat_billing_exception session_id={session_id} error={str(billing_error)}", exc_info=True)

                return HeartbeatResponse(
                    status="error",
                    message=f"Billing error: {str(billing_error)}"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"heartbeat_failed session_id={session_id} error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Heartbeat failed: {str(e)}"
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
                logger.warning(f"webhook_invalid_signature")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        else:
            logger.warning(f"webhook_no_signature warning='Allowing for development'")

        # Parse event
        try:
            event_data = json.loads(body.decode('utf-8'))
        except Exception as e:
            logger.error(f"webhook_invalid_json error={str(e)}", exc_info=True)
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        event_type = event_data.get('event')
        room_data = event_data.get('room', {})
        participant_data = event_data.get('participant', {})

        room_name = room_data.get('name') or room_data.get('id')
        participant_identity = participant_data.get('identity')

        logger.info(f"webhook_event_received event_type={event_type} room={room_name} participant={participant_identity}")

        # Handle disconnect events
        if event_type in ['participant_left', 'room_finished']:
            if room_name and room_name.startswith('session_'):
                session_id = room_name

                if True:  # Removed LogContext wrapper
                    logger.info(f"webhook_disconnect_detected session_id={session_id} event_type={event_type}")

                    # Trigger cleanup asynchronously
                    try:
                        cleanup_details = await cleanup_session(session_id)
                        logger.info(f"webhook_cleanup_initiated session_id={session_id} cleanup_details={cleanup_details}")
                    except Exception as e:
                        logger.error(f"webhook_cleanup_failed session_id={session_id} error={str(e)}", exc_info=True)

        return {"status": "ok", "event": event_type}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"webhook_processing_error error={str(e)}", exc_info=True)
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
        logger.error(f"debug_endpoint_error session_id={session_id} error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Debug endpoint failed: {str(e)}"
        )

# ==============================================================================
# ADMIN / MONITORING ENDPOINTS
# ==============================================================================

@app.get("/api/admin/sessions")
async def list_sessions():
    """
    List all active and recent sessions with their status.

    Returns:
        Array of session objects with id, status, start_time, duration, etc.
    """
    try:
        logger.info(f"admin_list_sessions_requested")

        # Get all session keys from Redis
        session_keys = redis_client.keys("session:*")

        sessions = []
        for key in session_keys:
            # Skip config and user mapping keys
            if isinstance(key, bytes):
                key = key.decode('utf-8')

            if ':config' in key or ':user:' in key or key == 'session:ready' or key == 'session:starting':
                continue

            session_id = key.replace('session:', '')
            session_data = redis_client.hgetall(key)

            if not session_data:
                continue

            # Decode bytes to strings if needed
            if session_data and isinstance(list(session_data.keys())[0], bytes):
                decoded_data = {
                    k.decode('utf-8') if isinstance(k, bytes) else k:
                    v.decode('utf-8') if isinstance(v, bytes) else v
                    for k, v in session_data.items()
                }
            else:
                decoded_data = session_data

            # Get agent PID to check if process is running
            agent_pid_key = f"agent:{session_id}:pid"
            agent_pid = redis_client.get(agent_pid_key)

            is_active = False
            if agent_pid:
                try:
                    pid = int(agent_pid)
                    os.kill(pid, 0)  # Check if process exists
                    is_active = True
                except (OSError, ValueError):
                    is_active = False

            # Calculate duration
            start_time = decoded_data.get('conversationStartTime')
            duration = None
            if start_time:
                try:
                    duration = int(time.time()) - int(start_time)
                except (ValueError, TypeError):
                    duration = None

            sessions.append({
                "session_id": session_id,
                "user_id": decoded_data.get('userName', 'unknown'),
                "voice_id": decoded_data.get('voiceId', 'unknown'),
                "status": decoded_data.get('status', 'unknown'),
                "is_active": is_active,
                "start_time": start_time,
                "duration_seconds": duration,
                "agent_pid": int(agent_pid) if agent_pid else None,
                "created_at": decoded_data.get('createdAt', decoded_data.get('startTime'))
            })

        # Sort by start_time (most recent first)
        sessions.sort(key=lambda x: int(x.get('start_time', 0)) if x.get('start_time') else 0, reverse=True)

        active_count = sum(1 for s in sessions if s['is_active'])

        logger.info(f"admin_list_sessions_success total={len(sessions)} active={active_count}")

        return {
            "sessions": sessions,
            "total": len(sessions),
            "active_count": active_count
        }

    except Exception as e:
        logger.error(f"admin_list_sessions_failed error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list sessions: {str(e)}"
        )


@app.get("/api/admin/sessions/{session_id}/logs")
async def get_session_logs(session_id: str, limit: int = 100):
    """
    Get logs for a specific session from Redis.

    Args:
        session_id: The session ID to get logs for
        limit: Maximum number of log entries to return (default: 100)

    Returns:
        Log entries for the session
    """
    try:
        logger.info(f"admin_get_session_logs_requested session_id={session_id} limit={limit}")

        # Get logs from Redis (stored by agent)
        log_key = f"agent:{session_id}:logs"
        logs = redis_client.lrange(log_key, 0, -1)

        # Decode and parse logs
        parsed_logs = []
        for log_entry in logs:
            if isinstance(log_entry, bytes):
                log_entry = log_entry.decode('utf-8')

            try:
                # Try to parse as JSON
                parsed_logs.append(json.loads(log_entry))
            except json.JSONDecodeError:
                # If not JSON, add as raw message
                parsed_logs.append({"message": log_entry, "raw": True})

        # Limit results
        if limit and limit > 0:
            parsed_logs = parsed_logs[-limit:]

        logger.info(f"admin_get_session_logs_success session_id={session_id} count={len(parsed_logs)}")

        return {
            "session_id": session_id,
            "logs": parsed_logs,
            "count": len(parsed_logs)
        }

    except Exception as e:
        logger.error(f"admin_get_session_logs_failed session_id={session_id} error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session logs: {str(e)}"
        )


@app.get("/api/admin/logs/orchestrator")
async def get_orchestrator_logs(lines: int = 200):
    """
    Get recent orchestrator logs from Docker container or log file.

    Args:
        lines: Number of recent log lines to return (default: 200)

    Returns:
        Recent log entries
    """
    import subprocess

    try:
        logger.info(f"admin_get_orchestrator_logs_requested lines={lines}")

        logs = []
        log_source = None

        # Try reading from Docker container logs first (requires Docker socket mount)
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(lines), "voice-agent-orchestrator"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                log_source = "docker_logs"
                # Combine stdout and stderr
                all_lines = (result.stdout + result.stderr).split('\n')

                for line in all_lines:
                    if line.strip():
                        try:
                            logs.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            logs.append({"message": line.strip(), "raw": True})

                logger.info(f"admin_orchestrator_logs_from_docker count={len(logs)}")

                return {
                    "logs": logs,
                    "count": len(logs),
                    "source": log_source
                }
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError) as docker_error:
            logger.debug(f"admin_docker_logs_unavailable error={str(docker_error)}")

        # Fallback: Check common log file locations
        log_paths = [
            "/app/logs/orchestrator.log",
            "/var/log/orchestrator.log",
            "./logs/orchestrator.log",
            "orchestrator.log"
        ]

        for log_file in log_paths:
            if os.path.exists(log_file):
                log_source = log_file
                try:
                    with open(log_file, 'r') as f:
                        all_lines = f.readlines()
                        recent_lines = all_lines[-lines:] if lines > 0 else all_lines

                        for line in recent_lines:
                            try:
                                logs.append(json.loads(line.strip()))
                            except json.JSONDecodeError:
                                logs.append({"message": line.strip(), "raw": True})
                    break
                except Exception as read_error:
                    logger.warning(f"admin_log_file_read_failed file={log_file} error={str(read_error)}")

        if not logs:
            logger.warning(f"admin_no_orchestrator_logs_found")

            # Provide helpful instructions
            instructions = [
                {"message": "Orchestrator logs are sent to stdout/stderr (Docker logs)", "raw": True},
                {"message": "", "raw": True},
                {"message": "To view logs, run:", "raw": True},
                {"message": "  docker logs voice-agent-orchestrator --tail 200 --follow", "raw": True},
                {"message": "", "raw": True},
                {"message": "Or from host machine:", "raw": True},
                {"message": "  docker logs voice-agent-orchestrator | tail -200", "raw": True},
                {"message": "", "raw": True},
                {"message": "To enable file-based logging, add this to supervisord.conf:", "raw": True},
                {"message": "  stdout_logfile=/var/log/orchestrator.log", "raw": True},
            ]

            return {
                "logs": instructions,
                "count": 0,
                "source": "instructions"
            }

        logger.info(f"admin_get_orchestrator_logs_success count={len(logs)} source={log_source}")

        return {
            "logs": logs,
            "count": len(logs),
            "source": log_source
        }

    except Exception as e:
        logger.error(f"admin_get_orchestrator_logs_failed error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get orchestrator logs: {str(e)}"
        )


@app.get("/api/admin/logs/celery")
async def get_celery_logs(lines: int = 200):
    """
    Get recent Celery worker logs from Docker container or log files.

    Args:
        lines: Number of recent log lines to return (default: 200)

    Returns:
        Recent Celery log entries
    """
    import subprocess

    try:
        logger.info(f"admin_get_celery_logs_requested lines={lines}")

        logs = []
        log_source = None

        # Try reading from supervisor log files first (Celery runs under supervisor)
        supervisor_log_paths = [
            "/var/log/supervisor/celery_worker-stdout---supervisor-*.log",
            "/var/log/supervisor/celery_beat-stdout---supervisor-*.log"
        ]

        import glob
        for log_pattern in supervisor_log_paths:
            matching_files = glob.glob(log_pattern)
            if matching_files:
                log_source = matching_files[0]
                try:
                    with open(matching_files[0], 'r') as f:
                        all_lines = f.readlines()
                        recent_lines = all_lines[-lines:] if lines > 0 else all_lines

                        for line in recent_lines:
                            if line.strip():
                                try:
                                    logs.append(json.loads(line.strip()))
                                except json.JSONDecodeError:
                                    logs.append({"message": line.strip(), "raw": True})

                    logger.info(f"admin_celery_logs_from_supervisor count={len(logs)} file={log_source}")

                    return {
                        "logs": logs,
                        "count": len(logs),
                        "source": log_source
                    }
                except Exception as read_error:
                    logger.warning(f"admin_supervisor_log_read_failed file={matching_files[0]} error={str(read_error)}")

        # Fallback: Try reading from Docker container logs
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(lines), "voice-agent-orchestrator"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                log_source = "docker_logs"
                all_lines = (result.stdout + result.stderr).split('\n')

                # Filter for Celery-related lines
                for line in all_lines:
                    if line.strip() and ('celery' in line.lower() or 'worker' in line.lower() or 'task' in line.lower() or 'beat' in line.lower()):
                        try:
                            logs.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            logs.append({"message": line.strip(), "raw": True})

                logger.info(f"admin_celery_logs_from_docker count={len(logs)}")

                return {
                    "logs": logs,
                    "count": len(logs),
                    "source": log_source
                }
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError) as docker_error:
            logger.debug(f"admin_docker_logs_unavailable error={str(docker_error)}")

        # No logs found - provide helpful instructions
        logger.warning(f"admin_no_celery_logs_found")

        instructions = [
            {"message": "Celery logs are sent to stdout/stderr (Docker logs)", "raw": True},
            {"message": "", "raw": True},
            {"message": "Docker socket not mounted or docker command unavailable.", "raw": True},
            {"message": "Add this to docker-compose.yml to enable log viewing:", "raw": True},
            {"message": "  volumes:", "raw": True},
            {"message": "    - /var/run/docker.sock:/var/run/docker.sock", "raw": True},
        ]

        return {
            "logs": instructions,
            "count": 0,
            "source": "instructions"
        }

    except Exception as e:
        logger.error(f"admin_get_celery_logs_failed error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get Celery logs: {str(e)}"
        )


# ==============================================================================
# METRICS ENDPOINTS
# ==============================================================================

class AgentSpawnMetrics(BaseModel):
    """Response model for agent spawn metrics"""
    total_spawns: int = 0
    successful_spawns: int = 0
    failed_spawns: int = 0
    success_rate: float = 0.0
    average_startup_time_ms: float = 0.0
    average_alive_signal_time_ms: float = 0.0
    cold_starts: int = 0
    total_retries: int = 0
    timeout_failures: int = 0
    recent_failures: list = []


@app.get("/api/metrics/agent-spawn", response_model=AgentSpawnMetrics)
async def get_agent_spawn_metrics():
    """
    Get agent spawn metrics for monitoring and debugging.

    These metrics are tracked by the AgentMetrics class in the worker tasks
    and stored in Redis. Useful for understanding:
    - How long agents take to start
    - How often spawning fails
    - Whether cold starts are causing delays

    Returns:
        AgentSpawnMetrics with spawn statistics
    """
    try:
        logger.info("metrics_agent_spawn_requested")

        # Get metrics from Redis (stored by worker tasks)
        metrics_key = "metrics:agent_spawn"
        metrics_data = redis_client.hgetall(metrics_key)

        if not metrics_data:
            logger.info("metrics_agent_spawn_no_data")
            return AgentSpawnMetrics()

        # Decode bytes if needed
        if metrics_data and isinstance(list(metrics_data.keys())[0], bytes):
            metrics_data = {
                k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in metrics_data.items()
            }

        # Get recent failure details
        recent_failures_key = "metrics:agent_spawn:recent_failures"
        recent_failures_raw = redis_client.lrange(recent_failures_key, 0, 9)  # Last 10
        recent_failures = []
        for failure in recent_failures_raw:
            try:
                if isinstance(failure, bytes):
                    failure = failure.decode()
                recent_failures.append(json.loads(failure))
            except (json.JSONDecodeError, Exception):
                recent_failures.append({"raw": failure})

        # Calculate success rate
        total_spawns = int(metrics_data.get('total_spawns', 0))
        successful_spawns = int(metrics_data.get('successful_spawns', 0))
        success_rate = (successful_spawns / total_spawns * 100) if total_spawns > 0 else 0.0

        result = AgentSpawnMetrics(
            total_spawns=total_spawns,
            successful_spawns=successful_spawns,
            failed_spawns=int(metrics_data.get('failed_spawns', 0)),
            success_rate=round(success_rate, 2),
            average_startup_time_ms=float(metrics_data.get('average_startup_time_ms', 0)),
            average_alive_signal_time_ms=float(metrics_data.get('average_alive_signal_time_ms', 0)),
            cold_starts=int(metrics_data.get('cold_starts', 0)),
            total_retries=int(metrics_data.get('total_retries', 0)),
            timeout_failures=int(metrics_data.get('timeout_failures', 0)),
            recent_failures=recent_failures
        )

        logger.info(f"metrics_agent_spawn_success total={total_spawns} success_rate={success_rate:.1f}%")
        return result

    except Exception as e:
        logger.error(f"metrics_agent_spawn_failed error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent spawn metrics: {str(e)}"
        )


class SessionMetrics(BaseModel):
    """Response model for session-specific metrics"""
    session_id: str
    spawn_started_at: Optional[str] = None
    alive_signal_at: Optional[str] = None
    connected_at: Optional[str] = None
    spawn_duration_ms: Optional[float] = None
    alive_signal_time_ms: Optional[float] = None
    connection_time_ms: Optional[float] = None
    is_cold_start: bool = False
    retry_count: int = 0
    current_status: str = "unknown"
    agent_pid: Optional[int] = None
    errors: list = []


@app.get("/api/metrics/session/{session_id}", response_model=SessionMetrics)
async def get_session_metrics(session_id: str):
    """
    Get detailed metrics for a specific session.

    Useful for debugging why a specific session may have had delays or failures.

    Args:
        session_id: The session to get metrics for

    Returns:
        SessionMetrics with timing and status details
    """
    try:
        logger.info(f"metrics_session_requested session_id={session_id}")

        # Get session metrics from Redis
        metrics_key = f"metrics:session:{session_id}"
        metrics_data = redis_client.hgetall(metrics_key)

        # Also get session data for status
        session_key = f"session:{session_id}"
        session_data = redis_client.hgetall(session_key)

        # Decode bytes if needed
        if metrics_data and isinstance(list(metrics_data.keys())[0], bytes):
            metrics_data = {
                k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in metrics_data.items()
            }

        if session_data and isinstance(list(session_data.keys())[0], bytes):
            session_data = {
                k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in session_data.items()
            }

        # Get agent PID
        agent_pid = None
        pid_str = session_data.get('agentPid') if session_data else None
        if not pid_str:
            pid_str = redis_client.get(f"agent:{session_id}:pid")
        if pid_str:
            try:
                agent_pid = int(pid_str)
            except ValueError:
                pass

        # Get errors from session logs
        errors = []
        logs_key = f"agent:{session_id}:logs"
        logs = redis_client.lrange(logs_key, -20, -1)  # Last 20 log entries
        for log_entry in logs:
            try:
                if isinstance(log_entry, bytes):
                    log_entry = log_entry.decode()
                log_obj = json.loads(log_entry)
                if log_obj.get('level') in ['error', 'ERROR', 'warning', 'WARNING']:
                    errors.append(log_obj)
            except (json.JSONDecodeError, Exception):
                if 'error' in str(log_entry).lower() or 'fail' in str(log_entry).lower():
                    errors.append({"message": str(log_entry)})

        result = SessionMetrics(
            session_id=session_id,
            spawn_started_at=metrics_data.get('spawn_started_at') if metrics_data else None,
            alive_signal_at=metrics_data.get('alive_signal_at') if metrics_data else None,
            connected_at=metrics_data.get('connected_at') if metrics_data else None,
            spawn_duration_ms=float(metrics_data.get('spawn_duration_ms', 0)) if metrics_data else None,
            alive_signal_time_ms=float(metrics_data.get('alive_signal_time_ms', 0)) if metrics_data else None,
            connection_time_ms=float(metrics_data.get('connection_time_ms', 0)) if metrics_data else None,
            is_cold_start=metrics_data.get('is_cold_start', 'false').lower() == 'true' if metrics_data else False,
            retry_count=int(metrics_data.get('retry_count', 0)) if metrics_data else 0,
            current_status=session_data.get('status', 'unknown') if session_data else 'not_found',
            agent_pid=agent_pid,
            errors=errors[-5:]  # Last 5 errors
        )

        logger.info(f"metrics_session_success session_id={session_id} status={result.current_status}")
        return result

    except Exception as e:
        logger.error(f"metrics_session_failed session_id={session_id} error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session metrics: {str(e)}"
        )


@app.post("/api/metrics/agent-spawn/reset")
async def reset_agent_spawn_metrics():
    """
    Reset agent spawn metrics (admin only).

    Clears all accumulated metrics. Useful for starting fresh after deploying fixes.

    Returns:
        Success message
    """
    try:
        logger.warning("metrics_agent_spawn_reset_requested")

        # Delete metrics keys
        keys_to_delete = [
            "metrics:agent_spawn",
            "metrics:agent_spawn:recent_failures"
        ]

        for key in keys_to_delete:
            redis_client.delete(key)

        logger.info("metrics_agent_spawn_reset_success")
        return {"success": True, "message": "Agent spawn metrics reset"}

    except Exception as e:
        logger.error(f"metrics_agent_spawn_reset_failed error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset metrics: {str(e)}"
        )


# ==============================================================================
# AGENT METRICS ENDPOINTS (Histogram + Prometheus Format)
# ==============================================================================

@app.get("/api/metrics/agent")
async def get_agent_metrics():
    """
    Get agent startup performance metrics.

    Returns:
        JSON with metrics:
        - agent_startup_duration_seconds: Histogram and stats
        - agent_startup_timeout_count: Number of timeouts
        - agent_retry_count: Number of retries
        - worker_cold_start_count: Number of cold starts

    Example response:
    {
        "agent_startup_duration_seconds": {
            "histogram": {
                "le_5": 10,
                "le_10": 25,
                "le_15": 45,
                "le_20": 52,
                "le_30": 58,
                "le_45": 60,
                "le_60": 61,
                "le_90": 62,
                "le_inf": 62
            },
            "sum": 892.5,
            "count": 62,
            "avg": 14.4
        },
        "agent_startup_timeout_count": 3,
        "agent_retry_count": 5,
        "worker_cold_start_count": 8
    }
    """
    try:
        metrics_prefix = "metrics:agent:"

        # Get histogram buckets
        histogram_raw = redis_client.hgetall(f"{metrics_prefix}startup_duration_histogram")
        histogram = {}
        if histogram_raw:
            histogram = {
                k.decode() if isinstance(k, bytes) else k:
                int(v.decode() if isinstance(v, bytes) else v)
                for k, v in histogram_raw.items()
            }

        # Get duration stats
        duration_raw = redis_client.hgetall(f"{metrics_prefix}startup_duration")
        duration_sum = 0.0
        duration_count = 0
        if duration_raw:
            sum_val = duration_raw.get(b'sum') or duration_raw.get('sum', 0)
            count_val = duration_raw.get(b'count') or duration_raw.get('count', 0)
            duration_sum = float(sum_val.decode() if isinstance(sum_val, bytes) else sum_val)
            duration_count = int(count_val.decode() if isinstance(count_val, bytes) else count_val)

        # Get counters
        timeout_count = redis_client.get(f"{metrics_prefix}startup_timeout_count")
        retry_count = redis_client.get(f"{metrics_prefix}retry_count")
        cold_start_count = redis_client.get(f"{metrics_prefix}cold_start_count")

        return {
            "agent_startup_duration_seconds": {
                "histogram": histogram,
                "sum": duration_sum,
                "count": duration_count,
                "avg": round(duration_sum / duration_count, 2) if duration_count > 0 else 0
            },
            "agent_startup_timeout_count": int(timeout_count or 0),
            "agent_retry_count": int(retry_count or 0),
            "worker_cold_start_count": int(cold_start_count or 0)
        }

    except Exception as e:
        logger.error(f"metrics_endpoint_error error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve metrics: {str(e)}"
        )


@app.get("/api/metrics/agent/prometheus")
async def get_agent_metrics_prometheus():
    """
    Get agent metrics in Prometheus exposition format.

    Can be scraped by Prometheus directly.

    Returns:
        Plain text in Prometheus format
    """
    from fastapi.responses import PlainTextResponse

    try:
        metrics_prefix = "metrics:agent:"
        lines = []

        # Histogram metrics
        lines.append("# HELP agent_startup_duration_seconds Histogram of agent startup times")
        lines.append("# TYPE agent_startup_duration_seconds histogram")

        histogram_raw = redis_client.hgetall(f"{metrics_prefix}startup_duration_histogram")
        if histogram_raw:
            buckets = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180]
            for bucket in buckets:
                key = f"le_{bucket}".encode() if isinstance(list(histogram_raw.keys())[0], bytes) else f"le_{bucket}"
                count = histogram_raw.get(key, 0)
                if isinstance(count, bytes):
                    count = count.decode()
                lines.append(f'agent_startup_duration_seconds_bucket{{le="{bucket}"}} {count}')

            # +Inf bucket
            inf_key = b"le_inf" if isinstance(list(histogram_raw.keys())[0], bytes) else "le_inf"
            inf_count = histogram_raw.get(inf_key, 0)
            if isinstance(inf_count, bytes):
                inf_count = inf_count.decode()
            lines.append(f'agent_startup_duration_seconds_bucket{{le="+Inf"}} {inf_count}')

        # Duration sum and count
        duration_raw = redis_client.hgetall(f"{metrics_prefix}startup_duration")
        if duration_raw:
            sum_val = duration_raw.get(b'sum') or duration_raw.get('sum', 0)
            count_val = duration_raw.get(b'count') or duration_raw.get('count', 0)
            if isinstance(sum_val, bytes):
                sum_val = sum_val.decode()
            if isinstance(count_val, bytes):
                count_val = count_val.decode()
            lines.append(f"agent_startup_duration_seconds_sum {sum_val}")
            lines.append(f"agent_startup_duration_seconds_count {count_val}")

        # Counter metrics
        lines.append("")
        lines.append("# HELP agent_startup_timeout_total Total number of agent startup timeouts")
        lines.append("# TYPE agent_startup_timeout_total counter")
        timeout_count = redis_client.get(f"{metrics_prefix}startup_timeout_count") or 0
        lines.append(f"agent_startup_timeout_total {timeout_count}")

        lines.append("")
        lines.append("# HELP agent_retry_total Total number of agent spawn retries")
        lines.append("# TYPE agent_retry_total counter")
        retry_count = redis_client.get(f"{metrics_prefix}retry_count") or 0
        lines.append(f"agent_retry_total {retry_count}")

        lines.append("")
        lines.append("# HELP worker_cold_start_total Total number of worker cold starts")
        lines.append("# TYPE worker_cold_start_total counter")
        cold_start_count = redis_client.get(f"{metrics_prefix}cold_start_count") or 0
        lines.append(f"worker_cold_start_total {cold_start_count}")

        return PlainTextResponse(
            content="\n".join(lines),
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    except Exception as e:
        logger.error(f"prometheus_metrics_error error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate Prometheus metrics: {str(e)}"
        )


@app.delete("/api/metrics/agent/reset")
async def reset_agent_metrics():
    """
    Reset all agent metrics (for testing/debugging).

    WARNING: This clears all historical metrics data.

    Returns:
        Confirmation message
    """
    try:
        metrics_prefix = "metrics:agent:"

        keys_to_delete = [
            f"{metrics_prefix}startup_duration_histogram",
            f"{metrics_prefix}startup_duration",
            f"{metrics_prefix}startup_timeout_count",
            f"{metrics_prefix}retry_count",
            f"{metrics_prefix}cold_start_count"
        ]

        deleted = 0
        for key in keys_to_delete:
            deleted += redis_client.delete(key)

        logger.info(f"metrics_reset deleted_keys={deleted}")

        return {
            "success": True,
            "message": f"Reset {deleted} metric keys",
            "keys_deleted": keys_to_delete
        }

    except Exception as e:
        logger.error(f"metrics_reset_error error={str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset metrics: {str(e)}"
        )


# ==============================================================================
# HEALTH CHECK
# ==============================================================================

@app.get("/orchestrator/health")
async def health_check():
    """Detailed health check"""
    redis_healthy = False
    try:
        redis_client.ping()
        redis_healthy = True
    except Exception as e:
        logger.error(f"health_redis_check_failed error={str(e)}", exc_info=True)

    status = "healthy" if redis_healthy else "degraded"
    logger.info(f"health_check status={status} redis_connected={redis_healthy}")

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

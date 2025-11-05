"""
Celery tasks for voice agent orchestration.

This module defines asynchronous tasks for:
- Spawning voice agents
- Health checking running agents
- Cleaning up stale sessions
"""

from celery import Celery, Task
import subprocess
import redis
import time
import os
import uuid
import signal
import threading

# Import structured logging
from backend.common.logging_config import setup_logging, LogContext
from backend.common.session_store import SessionStore

# Setup logging
logger = setup_logging(service_name='celery-worker')

# Initialize Celery
app = Celery('voice_agent_tasks')
app.config_from_object('backend.orchestrator.celeryconfig')

# Redis client
redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

# Session store for type-safe Redis operations
session_store = SessionStore(redis_client)

# Configuration
PYTHON_SCRIPT_PATH = os.getenv('PYTHON_SCRIPT_PATH', '/app/backend/agent/voice_assistant.py')
BOT_STARTUP_TIMEOUT = int(os.getenv('BOT_STARTUP_TIMEOUT', 30))  # Increased for ML model loading
SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', 14400))  # 4 hours for medical conversations
MAX_LOG_ENTRIES = 100
AGENT_LOG_DIR = os.getenv('AGENT_LOG_DIR', '/var/log/voice-agents')

# Ensure log directory exists
os.makedirs(AGENT_LOG_DIR, exist_ok=True)


class AgentSpawnTask(Task):
    """Base task with retry logic and error handling"""
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3, 'countdown': 5}
    retry_backoff = True
    retry_backoff_max = 60
    retry_jitter = True


def continuous_log_reader(process, session_id, log_file_path):
    """
    Background thread to continuously read agent logs.

    This prevents the stdout pipe from filling up and blocking the agent process.
    Logs are written to both a file and Redis for different access patterns.

    Args:
        process: The subprocess.Popen object
        session_id: Session identifier for Redis keys
        log_file_path: Path to the log file
    """
    try:
        with open(log_file_path, 'a', buffering=1) as log_file:  # Line buffered
            for line in process.stdout:
                if not line:
                    break

                line = line.strip()

                # Write to file (for tail -f and long-term storage)
                log_file.write(line + '\n')

                # Store in Redis (for API access, keep last 100 lines)
                try:
                    redis_client.rpush(f'agent:{session_id}:logs', line)
                    redis_client.ltrim(f'agent:{session_id}:logs', -MAX_LOG_ENTRIES, -1)
                except Exception as e:
                    # Don't let Redis errors stop log file writing
                    logger.warning("log_reader_redis_error",
                                 session_id=session_id,
                                 error=str(e))

    except Exception as e:
        logger.error("log_reader_thread_error",
                    session_id=session_id,
                    error=str(e),
                    exc_info=True)
    finally:
        logger.info("log_reader_thread_stopped", session_id=session_id)


@app.task(base=AgentSpawnTask, bind=True, name='spawn_voice_agent')
def spawn_voice_agent(self, session_id, user_id=None):
    """
    Spawn a voice agent process asynchronously.

    Args:
        session_id: Unique session identifier
        user_id: User ID for the session

    Returns:
        dict: {session_id, pid, status, startup_time}
    """
    start_time = time.time()
    task_id = self.request.id

    # Use LogContext for correlation tracking
    with LogContext(session_id=session_id, task_id=task_id, user_id=user_id):
        try:
            logger.info("agent_spawn_started")

            # Fetch session configuration from Redis
            # Changed from user-based to session-based to support multiple concurrent sessions per user
            voice_id = 'Ashley'  # Default voice
            opening_line = None
            system_prompt = None

            try:
                config_key = f'session:{session_id}:config'
                config = redis_client.hgetall(config_key)
                if config and b'voiceId' in config:
                    voice_id = config[b'voiceId'].decode('utf-8')
                    if b'openingLine' in config:
                        opening_line = config[b'openingLine'].decode('utf-8')
                    if b'systemPrompt' in config:
                        system_prompt = config[b'systemPrompt'].decode('utf-8')
                    logger.info("session_config_loaded",
                               voice_id=voice_id,
                               opening_line_preview=opening_line[:50] if opening_line else 'default',
                               system_prompt_preview=system_prompt[:50] if system_prompt else 'default')
            except Exception as e:
                logger.warning("session_config_load_failed", error=str(e), fallback="defaults")

            # Update session status
            redis_client.hset(f'session:{session_id}', mapping={
                'status': 'starting',
                'userId': user_id or '',
                'voiceId': voice_id,
                'createdAt': int(time.time()),
                'celeryTaskId': task_id
            })
            redis_client.sadd('session:starting', session_id)

            # Build command with voice customization
            cmd = ['python3', PYTHON_SCRIPT_PATH, '--room', session_id, '--voice-id', voice_id]
            if opening_line:
                cmd.extend(['--opening-line', opening_line])
            if system_prompt:
                cmd.extend(['--system-prompt', system_prompt])

            # Create log file path for this agent
            log_file_path = os.path.join(AGENT_LOG_DIR, f'{session_id}.log')

            # Spawn Python process
            # Use os.setsid to create new process group for proper cleanup
            # Redirect stderr to stdout so we can read all logs from one stream
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                text=True,
                bufsize=1,
                env=os.environ.copy(),
                preexec_fn=os.setsid  # Create new process group
            )

            pid = process.pid

            # Get process group ID for verification and tracking
            try:
                pgid = os.getpgid(pid)
                is_group_leader = (pgid == pid)

                # Store PID, PGID, and log file path in Redis for cleanup and access
                redis_client.set(f'agent:{session_id}:pid', pid, ex=14400)  # 4 hour TTL
                redis_client.set(f'agent:{session_id}:logfile', log_file_path, ex=14400)  # 4 hour TTL
                redis_client.hset(f'session:{session_id}', 'agentPid', str(pid))
                redis_client.hset(f'session:{session_id}', 'agentPgid', str(pgid))
                redis_client.hset(f'session:{session_id}', 'logFile', log_file_path)

                logger.info("agent_process_spawned",
                           pid=pid,
                           pgid=pgid,
                           is_group_leader=is_group_leader,
                           voice_id=voice_id,
                           log_file=log_file_path)

                # Verify that the process is a group leader (expected with os.setsid)
                if not is_group_leader:
                    logger.warning("agent_not_group_leader",
                                  pid=pid,
                                  pgid=pgid,
                                  warning="Process may not be properly isolated for cleanup")

            except (ProcessLookupError, OSError) as e:
                logger.error("agent_pgid_lookup_failed",
                           pid=pid,
                           error=str(e),
                           warning="Process group tracking unavailable")
                # Still store PID even if PGID lookup fails
                redis_client.set(f'agent:{session_id}:pid', pid, ex=14400)
                redis_client.set(f'agent:{session_id}:logfile', log_file_path, ex=14400)
                redis_client.hset(f'session:{session_id}', 'agentPid', str(pid))
                redis_client.hset(f'session:{session_id}', 'logFile', log_file_path)

            # Start background thread for continuous log reading
            # This prevents the pipe from filling up and blocking the agent
            log_thread = threading.Thread(
                target=continuous_log_reader,
                args=(process, session_id, log_file_path),
                daemon=True,
                name=f'log-reader-{session_id}'
            )
            log_thread.start()
            logger.info("log_reader_thread_started", session_id=session_id, thread_name=log_thread.name)

            # Monitor log file for connection success
            # The background thread is reading stdout and writing to the log file
            connected = False
            last_check = time.time()
            log_check_offset = 0  # Track how many lines we've read

            while time.time() - start_time < BOT_STARTUP_TIMEOUT:
                # Check if process died
                if process.poll() is not None:
                    error_msg = f"Agent process died unexpectedly (exit code: {process.returncode})"
                    logger.error("agent_process_died",
                               exit_code=process.returncode,
                               log_file=log_file_path,
                               exc_info=True)
                    raise Exception(error_msg)

                # Read new lines from Redis logs (written by background thread)
                try:
                    new_lines = redis_client.lrange(f'agent:{session_id}:logs', log_check_offset, -1)
                    if new_lines:
                        log_check_offset += len(new_lines)

                        # Check for connection success patterns in new lines
                        for line_bytes in new_lines:
                            line = line_bytes.decode('utf-8') if isinstance(line_bytes, bytes) else line_bytes

                            # Check for LiveKit connection
                            if any(keyword in line for keyword in ['Connected to', 'Pipeline started', 'Room joined', 'Participant joined']):
                                connected = True
                                logger.info("agent_connected_successfully", log_line=line[:100])
                                break

                        if connected:
                            break

                except Exception as e:
                    logger.warning("agent_log_check_error", error=str(e))

                # Progress log every 5 seconds
                if time.time() - last_check > 5:
                    elapsed = time.time() - start_time
                    logger.debug("agent_connection_waiting", elapsed_seconds=f"{elapsed:.1f}")
                    last_check = time.time()

                time.sleep(0.2)  # Check every 200ms

            if not connected:
                logger.error("agent_connection_timeout", timeout_seconds=BOT_STARTUP_TIMEOUT)
                os.killpg(process.pid, signal.SIGTERM)  # Kill entire process group
                time.sleep(2)
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)  # Force kill process group
                raise Exception(f"Agent failed to connect within {BOT_STARTUP_TIMEOUT}s")

            # Update session to ready
            startup_time = time.time() - start_time
            redis_client.hset(f'session:{session_id}', mapping={
                'status': 'ready',
                'agentPid': pid,
                'startupTime': startup_time,
                'lastActive': int(time.time())
            })

            # Move to ready state
            redis_client.srem('session:starting', session_id)
            redis_client.sadd('session:ready', session_id)
            if user_id:
                redis_client.set(f'session:user:{user_id}', session_id)
            logger.info("agent_ready", startup_time_seconds=f"{startup_time:.2f}")

            result = {
                'session_id': session_id,
                'pid': pid,
                'status': 'ready',
                'startup_time': startup_time
            }
            logger.info("agent_spawn_success", result=result)
            return result

        except Exception as e:
            error_msg = str(e)
            logger.error("agent_spawn_failed", error=error_msg, exc_info=True)

            # Mark session as failed
            redis_client.hset(f'session:{session_id}', mapping={
                'status': 'error',
                'error': error_msg,
                'lastActive': int(time.time())
            })
            redis_client.srem('session:starting', session_id)

            # Retry if not max retries
            if self.request.retries < self.max_retries:
                retry_num = self.request.retries + 1
                logger.info("agent_spawn_retrying", retry_num=retry_num, max_retries=self.max_retries)
                raise self.retry(exc=e)

            raise


@app.task(name='health_check_agents')
def health_check_agents():
    """
    Check health of all running agents.
    Runs every 60 seconds via Beat scheduler.

    Uses SessionStore for type-safe Redis operations.
    """
    try:
        checked_count = 0
        healthy_count = 0
        dead_count = 0

        # Get all session IDs (SessionStore handles filtering and type validation)
        session_ids = session_store.get_all_session_ids()

        for session_id in session_ids:
            # Get session data (already decoded and type-safe)
            session_data = session_store.get_session_data(session_id)

            if not session_data:
                continue

            status = session_data.get('status')
            if status not in ['ready', 'active']:
                continue

            pid = session_data.get('agentPid')
            if not pid:
                continue

            checked_count += 1

            # Check if process is alive
            try:
                os.kill(int(pid), 0)  # Signal 0 = check existence
                redis_client.hset(f'agent:{session_id}:health', mapping={
                    'last_check': int(time.time()),
                    'status': 'healthy'
                })
                healthy_count += 1

            except (ProcessLookupError, OSError):
                # Process is dead
                logger.warning("healthcheck_agent_dead",
                             session_id=session_id,
                             pid=pid,
                             action="marking_as_failed")
                redis_client.hset(f'session:{session_id}', 'status', 'error')
                redis_client.hset(f'session:{session_id}', 'error', 'Process died unexpectedly')
                redis_client.srem('session:ready', session_id)
                dead_count += 1

        logger.info("healthcheck_complete",
                   total_sessions_found=len(session_ids),
                   checked=checked_count,
                   healthy=healthy_count,
                   dead=dead_count)

    except Exception as e:
        logger.error("healthcheck_error", error=str(e), exc_info=True)


@app.task(name='cleanup_stale_agents')
def cleanup_stale_agents():
    """
    Clean up stale sessions and terminated agents.
    Runs every 5 minutes via Beat scheduler.

    Uses SessionStore for type-safe Redis operations.
    """
    try:
        now = int(time.time())
        timeout = int(os.getenv('SESSION_TIMEOUT', 14400))  # Default 4 hours
        cleaned_count = 0

        # Get all session IDs (SessionStore handles filtering and type validation)
        session_ids = session_store.get_all_session_ids()

        for session_id in session_ids:
            # Get session data (already decoded and type-safe)
            session_data = session_store.get_session_data(session_id)

            if not session_data:
                continue

            last_active = int(session_data.get('lastActive', session_data.get('createdAt', 0)))

            if now - last_active > timeout:
                logger.info("cleanup_stale_session",
                           session_id=session_id,
                           inactive_seconds=now - last_active)

                # Stop agent process and all children
                pid = session_data.get('agentPid')
                if pid:
                    try:
                        os.killpg(int(pid), signal.SIGTERM)  # Kill entire process group
                        time.sleep(5)  # Wait 5 seconds for graceful shutdown (transcript save)
                        # Force kill if still alive
                        try:
                            os.killpg(int(pid), signal.SIGKILL)  # Force kill process group
                        except (ProcessLookupError, OSError):
                            pass
                    except (ProcessLookupError, OSError):
                        pass

                # Clean up log file before Redis cleanup
                log_file = session_data.get('logFile')
                if log_file and os.path.exists(log_file):
                    try:
                        os.remove(log_file)
                        logger.debug("cleanup_log_file_removed", log_file=log_file)
                    except Exception as e:
                        logger.warning("cleanup_log_file_removal_failed",
                                     log_file=log_file,
                                     error=str(e))

                # Comprehensive Redis cleanup using SessionStore
                user_id = session_data.get('userId')
                session_store.cleanup_session(session_id, user_id)

                cleaned_count += 1

        if cleaned_count > 0:
            logger.info("cleanup_complete",
                       total_sessions_found=len(session_ids),
                       cleaned_sessions=cleaned_count)
        else:
            logger.debug("cleanup_no_stale_sessions",
                        total_sessions_found=len(session_ids))

    except Exception as e:
        logger.error("cleanup_error", error=str(e), exc_info=True)


# Beat Schedule Configuration
app.conf.beat_schedule = {
    'health-check-every-60s': {
        'task': 'health_check_agents',
        'schedule': 60.0,  # Every 60 seconds
    },
    'cleanup-stale-every-5m': {
        'task': 'cleanup_stale_agents',
        'schedule': 300.0,  # Every 5 minutes
    },
}

app.conf.timezone = 'UTC'


if __name__ == '__main__':
    # For testing tasks directly
    logger.info("celery_tasks_loaded",
               redis_url=os.getenv('REDIS_URL', 'Not set'),
               python_script_path=PYTHON_SCRIPT_PATH,
               bot_startup_timeout=BOT_STARTUP_TIMEOUT)

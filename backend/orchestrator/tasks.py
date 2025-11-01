"""
Celery tasks for voice agent orchestration.

This module defines asynchronous tasks for:
- Spawning voice agents
- Maintaining a pre-warmed agent pool
- Health checking running agents
- Cleaning up stale sessions
"""

from celery import Celery, Task
from celery.schedules import crontab
import subprocess
import redis
import time
import os
import uuid
import signal

# Initialize Celery
app = Celery('voice_agent_tasks')
app.config_from_object('backend.orchestrator.celeryconfig')

# Redis client
redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

# Configuration
PYTHON_SCRIPT_PATH = os.getenv('PYTHON_SCRIPT_PATH', '/app/backend/agent/voice_assistant.py')
BOT_STARTUP_TIMEOUT = int(os.getenv('BOT_STARTUP_TIMEOUT', 30))  # Increased for ML model loading
PREWARM_POOL_SIZE = int(os.getenv('PREWARM_POOL_SIZE', 3))
MAX_LOG_ENTRIES = 100


class AgentSpawnTask(Task):
    """Base task with retry logic and error handling"""
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3, 'countdown': 5}
    retry_backoff = True
    retry_backoff_max = 60
    retry_jitter = True


@app.task(base=AgentSpawnTask, bind=True, name='spawn_voice_agent')
def spawn_voice_agent(self, session_id, user_id=None, prewarm=False):
    """
    Spawn a voice agent process asynchronously.

    Args:
        session_id: Unique session identifier
        user_id: User ID (None for pre-warmed agents)
        prewarm: If True, agent goes to pool instead of ready state

    Returns:
        dict: {session_id, pid, status, startup_time}
    """
    start_time = time.time()
    task_id = self.request.id

    try:
        print(f"[Task {task_id}] Spawning agent for session: {session_id}")

        # Fetch user configuration if user_id is provided
        voice_id = 'Ashley'  # Default voice
        opening_line = None

        if user_id:
            try:
                config_key = f'user:{user_id}:config'
                config = redis_client.hgetall(config_key)
                if config and b'voiceId' in config:
                    voice_id = config[b'voiceId'].decode('utf-8')
                    if b'openingLine' in config:
                        opening_line = config[b'openingLine'].decode('utf-8')
                    print(f"[Task {task_id}] Using user config: voice={voice_id}, opening_line={opening_line[:50] if opening_line else 'default'}...")
            except Exception as e:
                print(f"[Task {task_id}] Error fetching user config: {e}, using defaults")

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

        # Spawn Python process
        # Use start_new_session to detach from parent and prevent zombies
        # Redirect stderr to stdout so we can read all logs from one stream
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            bufsize=1,
            env=os.environ.copy(),
            start_new_session=True  # Detach from parent process group
        )

        pid = process.pid

        # Store PID in both locations immediately for cleanup access
        redis_client.set(f'agent:{session_id}:pid', pid, ex=7200)  # 2 hour TTL
        redis_client.hset(f'session:{session_id}', 'agentPid', str(pid))

        print(f"[Task {task_id}] Process spawned with PID: {pid}")

        # Monitor stdout for connection success (stderr is redirected to stdout)
        connected = False
        last_check = time.time()

        while time.time() - start_time < BOT_STARTUP_TIMEOUT:
            # Check if process died
            if process.poll() is not None:
                # Read any remaining output
                remaining_output = process.stdout.read() if process.stdout else ""
                error_msg = f"Agent process died unexpectedly: {remaining_output}"
                print(f"[Task {task_id}] ERROR: {error_msg}")
                raise Exception(error_msg)

            # Read stdout line (non-blocking with timeout)
            try:
                line = process.stdout.readline()
                if line:
                    line = line.strip()
                    redis_client.rpush(f'agent:{session_id}:logs', line)
                    redis_client.ltrim(f'agent:{session_id}:logs', -MAX_LOG_ENTRIES, -1)

                    # Check for connection success patterns
                    # Pre-warmed agents are ready after initialization (no user to connect to yet)
                    # User agents wait for actual LiveKit connection
                    if prewarm:
                        if any(keyword in line for keyword in ['Inworld TTS service initialized', 'LiveKitInputTransport', 'Pipeline#0::Source']):
                            connected = True
                            print(f"[Task {task_id}] Pre-warmed agent initialized: {line}")
                            break
                    else:
                        if any(keyword in line for keyword in ['Connected to', 'Pipeline started', 'Room joined', 'Participant joined']):
                            connected = True
                            print(f"[Task {task_id}] Agent connected successfully: {line}")
                            break

            except Exception as e:
                print(f"[Task {task_id}] Error reading stdout: {e}")

            # Progress log every 5 seconds
            if time.time() - last_check > 5:
                elapsed = time.time() - start_time
                print(f"[Task {task_id}] Still waiting for connection... ({elapsed:.1f}s elapsed)")
                last_check = time.time()

            time.sleep(0.1)

        if not connected:
            print(f"[Task {task_id}] Timeout - agent failed to connect within {BOT_STARTUP_TIMEOUT}s")
            process.terminate()
            time.sleep(2)
            if process.poll() is None:
                process.kill()
            raise Exception(f"Agent failed to connect within {BOT_STARTUP_TIMEOUT}s")

        # Update session to ready
        startup_time = time.time() - start_time
        redis_client.hset(f'session:{session_id}', mapping={
            'status': 'ready',
            'agentPid': pid,
            'startupTime': startup_time,
            'lastActive': int(time.time())
        })

        # Move to appropriate state
        redis_client.srem('session:starting', session_id)
        if prewarm:
            redis_client.sadd('pool:ready', session_id)
            print(f"[Task {task_id}] Pre-warmed agent ready: {session_id}")
        else:
            redis_client.sadd('session:ready', session_id)
            if user_id:
                redis_client.set(f'session:user:{user_id}', session_id)
            print(f"[Task {task_id}] User agent ready: {session_id} (user: {user_id})")

        # Update pool stats
        redis_client.hincrby('pool:stats', 'total_spawned', 1)

        result = {
            'session_id': session_id,
            'pid': pid,
            'status': 'ready',
            'startup_time': startup_time
        }
        print(f"[Task {task_id}] Success: {result}")
        return result

    except Exception as e:
        error_msg = str(e)
        print(f"[Task {task_id}] FAILED: {error_msg}")

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
            print(f"[Task {task_id}] Retrying... (attempt {retry_num}/{self.max_retries})")
            raise self.retry(exc=e)

        raise


@app.task(name='prewarm_agent_pool')
def prewarm_agent_pool():
    """
    Maintain a pool of pre-warmed agents ready for instant assignment.
    Runs every 30 seconds via Beat scheduler.
    """
    try:
        target_size = int(redis_client.get('pool:target') or PREWARM_POOL_SIZE)
        current_size = redis_client.scard('pool:ready')

        deficit = target_size - current_size

        if deficit > 0:
            print(f"[PreWarm] Pool deficit: {deficit} (current: {current_size}, target: {target_size})")

            for i in range(deficit):
                session_id = f"prewarm_{uuid.uuid4().hex[:8]}"
                print(f"[PreWarm] Spawning agent {i+1}/{deficit}: {session_id}")
                spawn_voice_agent.delay(session_id, user_id=None, prewarm=True)

        else:
            print(f"[PreWarm] Pool healthy: {current_size}/{target_size}")

    except Exception as e:
        print(f"[PreWarm] ERROR: {e}")


@app.task(name='health_check_agents')
def health_check_agents():
    """
    Check health of all running agents.
    Runs every 60 seconds via Beat scheduler.
    """
    try:
        checked_count = 0
        healthy_count = 0
        dead_count = 0

        # Get all session keys (only direct session hashes, not user mappings)
        all_keys = redis_client.keys('session:*')

        # Filter to only get session hashes, not user mapping strings
        session_keys = []
        for key in all_keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            # Skip session:user:* keys (user ID mappings)
            if ':user:' not in key_str:
                session_keys.append(key_str)

        for key_str in session_keys:
            # Extract session ID (everything after "session:")
            session_id = key_str[len('session:'):]
            session_data = redis_client.hgetall(f'session:{session_id}')

            if not session_data:
                continue

            # Decode bytes to strings
            session_data = {
                k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in session_data.items()
            }

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
                print(f"[HealthCheck] Agent {session_id} (PID {pid}) is dead - marking as failed")
                redis_client.hset(f'session:{session_id}', 'status', 'error')
                redis_client.hset(f'session:{session_id}', 'error', 'Process died unexpectedly')
                redis_client.srem('pool:ready', session_id)
                redis_client.srem('session:ready', session_id)
                dead_count += 1

        print(f"[HealthCheck] Checked: {checked_count}, Healthy: {healthy_count}, Dead: {dead_count}")

    except Exception as e:
        print(f"[HealthCheck] ERROR: {e}")


@app.task(name='cleanup_stale_agents')
def cleanup_stale_agents():
    """
    Clean up stale sessions and terminated agents.
    Runs every 5 minutes via Beat scheduler.
    """
    try:
        now = int(time.time())
        timeout = int(os.getenv('SESSION_TIMEOUT', 1800))  # Default 30 minutes
        cleaned_count = 0

        session_keys = redis_client.keys('session:*')

        for key in session_keys:
            key_str = key.decode() if isinstance(key, bytes) else key

            if ':user:' in key_str:
                continue

            session_id = key_str.split(':')[1]
            session_data = redis_client.hgetall(f'session:{session_id}')

            if not session_data:
                continue

            # Decode bytes
            session_data = {
                k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in session_data.items()
            }

            last_active = int(session_data.get('lastActive', session_data.get('createdAt', 0)))

            if now - last_active > timeout:
                print(f"[Cleanup] Removing stale session: {session_id} (inactive for {now - last_active}s)")

                # Stop agent process
                pid = session_data.get('agentPid')
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        time.sleep(2)
                        # Force kill if still alive
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            pass
                    except (ProcessLookupError, OSError):
                        pass

                # Clean up Redis keys
                user_id = session_data.get('userId')
                redis_client.delete(f'session:{session_id}')
                redis_client.delete(f'agent:{session_id}:pid')
                redis_client.delete(f'agent:{session_id}:logs')
                redis_client.delete(f'agent:{session_id}:health')
                redis_client.srem('pool:ready', session_id)
                redis_client.srem('session:ready', session_id)
                redis_client.srem('session:starting', session_id)
                if user_id:
                    redis_client.delete(f'session:user:{user_id}')

                cleaned_count += 1

        if cleaned_count > 0:
            print(f"[Cleanup] Cleaned up {cleaned_count} stale sessions")
        else:
            print(f"[Cleanup] No stale sessions found")

    except Exception as e:
        print(f"[Cleanup] ERROR: {e}")


# Beat Schedule Configuration
app.conf.beat_schedule = {
    'prewarm-pool-every-30s': {
        'task': 'prewarm_agent_pool',
        'schedule': 30.0,  # Every 30 seconds
    },
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
    print("Celery tasks loaded successfully")
    print(f"Redis URL: {os.getenv('REDIS_URL', 'Not set')}")
    print(f"Python script path: {PYTHON_SCRIPT_PATH}")
    print(f"Bot startup timeout: {BOT_STARTUP_TIMEOUT}s")
    print(f"Pre-warm pool size: {PREWARM_POOL_SIZE}")

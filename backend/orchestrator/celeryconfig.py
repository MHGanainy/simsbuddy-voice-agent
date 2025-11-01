"""
Celery configuration for voice agent orchestration.

This module configures Celery to use Redis as both the broker and result backend.
Optimized for Railway deployment with managed Redis addon.
"""

import os

# Redis URL from Railway (injected automatically when Redis addon is provisioned)
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Broker settings (task queue)
broker_url = redis_url
broker_connection_retry_on_startup = True
broker_connection_retry = True
broker_connection_max_retries = 10
broker_connection_retry_delay = 5

# Result backend (task results storage)
result_backend = redis_url
result_expires = 3600  # Results expire after 1 hour
result_persistent = False  # No need to persist results to disk

# Serialization (JSON is safe and human-readable)
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True

# Worker settings
worker_prefetch_multiplier = 2  # Fetch 2 tasks at a time per worker process
worker_max_tasks_per_child = 100  # Restart worker after 100 tasks (prevents memory leaks)
worker_disable_rate_limits = True  # Disable rate limiting for faster processing
worker_send_task_events = True  # Enable task events for monitoring
task_send_sent_event = True  # Send event when task is sent

# Task execution settings
task_acks_late = True  # Acknowledge task after completion (not before)
task_reject_on_worker_lost = True  # Re-queue task if worker dies
task_track_started = True  # Track when task starts (not just when queued)
task_time_limit = 60  # Hard time limit: 60 seconds
task_soft_time_limit = 50  # Soft time limit: 50 seconds (raises exception)

# Performance tuning
result_compression = 'gzip'  # Compress results to save Redis memory
result_cache_max = 1000  # Cache up to 1000 results in memory

# Logging
worker_log_format = '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s'
worker_task_log_format = '[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s'

# Beat scheduler settings
beat_schedule_filename = '/tmp/celerybeat-schedule'  # Store schedule in tmp (ephemeral)
beat_max_loop_interval = 10  # Check for new tasks every 10 seconds

# Ignore result for these tasks (reduces Redis memory usage)
task_ignore_result = False  # We want results for debugging

# Task routes (optional: route specific tasks to specific queues)
# task_routes = {
#     'spawn_voice_agent': {'queue': 'spawning'},
#     'prewarm_agent_pool': {'queue': 'maintenance'},
# }

# Database settings (optional: use PostgreSQL for result backend at scale)
# If you need to scale beyond 10k tasks/sec, uncomment:
# database_url = os.getenv('DATABASE_URL')
# if database_url:
#     result_backend = database_url.replace('postgres://', 'db+postgresql://')

"""
Minimal Celery configuration for orchestrator service.

The orchestrator only needs Celery for:
1. Publishing tasks to worker queue
2. Revoking tasks (when sessions are terminated)

Workers run in separate service (backend/worker/).
"""

import os

# Redis URL for task queue
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Broker settings (task queue)
broker_url = redis_url
broker_connection_retry_on_startup = True
broker_connection_retry = True
broker_connection_max_retries = 10

# Result backend (for task status checking)
result_backend = redis_url
result_expires = 3600

# Serialization
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True

# Task routing - send all tasks to worker queue
task_routes = {
    'spawn_voice_agent': {'queue': 'worker'},
}

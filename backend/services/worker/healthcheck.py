#!/usr/bin/env python3
"""
Celery Worker Health Check Script

This script checks if the Celery worker is responsive and can process tasks.
Used by supervisor's eventlistener to automatically restart frozen workers.

Exit codes:
  0 - Worker is healthy
  1 - Worker is unhealthy (frozen/unresponsive)
"""

import sys
import os

# Add the app directory to the path
sys.path.insert(0, '/app')

def check_worker_health():
    """Check if the Celery worker responds to ping within timeout."""
    try:
        from celery import Celery

        # Create a Celery app with the worker's config
        app = Celery('healthcheck')
        app.config_from_object('backend.services.worker.celeryconfig')

        # Set a short timeout for the inspect command
        inspect = app.control.inspect(timeout=5.0)

        # Try to ping the worker
        result = inspect.ping()

        if result is None:
            print("UNHEALTHY: Worker did not respond to ping")
            return False

        # Check if any worker responded
        if len(result) == 0:
            print("UNHEALTHY: No workers found")
            return False

        print(f"HEALTHY: {len(result)} worker(s) responded")
        return True

    except Exception as e:
        print(f"UNHEALTHY: Error checking worker health: {e}")
        return False


def check_queue_growth():
    """Check if the queue is growing (tasks piling up without being processed)."""
    try:
        import redis

        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        r = redis.from_url(redis_url)

        queue_length = r.llen('worker')

        # If queue has more than 100 tasks, something might be wrong
        # (adjust threshold based on your workload)
        if queue_length > 100:
            print(f"WARNING: Queue has {queue_length} tasks pending")
            # Don't fail on queue length alone, but log it

        return True

    except Exception as e:
        print(f"WARNING: Could not check queue: {e}")
        return True  # Don't fail health check on Redis issues


if __name__ == '__main__':
    is_healthy = check_worker_health()
    check_queue_growth()

    sys.exit(0 if is_healthy else 1)

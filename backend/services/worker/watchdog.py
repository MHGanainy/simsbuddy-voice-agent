#!/usr/bin/env python3
"""
Celery Worker Watchdog

Runs as a background process that periodically checks worker health
and restarts the worker if it becomes unresponsive.

This prevents the frozen worker issue where the main Celery process
deadlocks and stops processing tasks.
"""

import subprocess
import sys
import os
import time
import signal

# Add the app directory to the path
sys.path.insert(0, '/app')

# Configuration
CHECK_INTERVAL = 60  # Check every 60 seconds
MAX_FAILURES = 2  # Restart after 2 consecutive failures
PING_TIMEOUT = 10  # Seconds to wait for worker ping response

consecutive_failures = 0
running = True


def signal_handler(signum, frame):
    global running
    print(f"Watchdog received signal {signum}, shutting down...")
    running = False


def check_worker_health():
    """Check if the Celery worker responds to ping."""
    try:
        from celery import Celery

        app = Celery('watchdog')
        app.config_from_object('backend.services.worker.celeryconfig')

        inspect = app.control.inspect(timeout=PING_TIMEOUT)
        result = inspect.ping()

        if result is None or len(result) == 0:
            return False, "Worker did not respond to ping"

        return True, f"{len(result)} worker(s) healthy"

    except Exception as e:
        return False, f"Error: {e}"


def restart_worker():
    """Restart the celery worker via supervisor or direct kill."""
    print("Attempting to restart celery worker...")

    try:
        # Try supervisor first
        result = subprocess.run(
            ['supervisorctl', '-c', '/app/supervisord.conf', 'restart', 'celery-worker'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            print(f"Supervisor restart succeeded: {result.stdout}")
            return True
    except Exception as e:
        print(f"Supervisor restart failed: {e}")

    # Fallback: kill the main worker process
    try:
        result = subprocess.run(
            ['pkill', '-9', '-f', 'celery.*worker'],
            capture_output=True,
            text=True,
            timeout=10
        )
        print("Killed worker processes via pkill")
        return True
    except Exception as e:
        print(f"pkill failed: {e}")

    return False


def main():
    global consecutive_failures, running

    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print(f"Celery watchdog started (check every {CHECK_INTERVAL}s, restart after {MAX_FAILURES} failures)")

    # Wait for worker to start
    time.sleep(30)

    while running:
        is_healthy, message = check_worker_health()

        if is_healthy:
            if consecutive_failures > 0:
                print(f"Worker recovered: {message}")
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            print(f"Health check failed ({consecutive_failures}/{MAX_FAILURES}): {message}")

            if consecutive_failures >= MAX_FAILURES:
                print(f"Worker unresponsive for {MAX_FAILURES} checks, restarting...")
                restart_worker()
                consecutive_failures = 0
                # Wait for worker to restart
                time.sleep(30)

        # Sleep until next check
        for _ in range(CHECK_INTERVAL):
            if not running:
                break
            time.sleep(1)

    print("Watchdog shutting down")


if __name__ == '__main__':
    main()

"""
Worker service for voice agent task execution.

This service runs Celery workers that handle:
- Agent spawning (subprocess management)
- Health checks (periodic monitoring)
- Cleanup tasks (stale session removal)
"""

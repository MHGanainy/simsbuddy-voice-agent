"""
Simplified Redis session helpers

Direct, lightweight wrappers around redis-py for session management.
Reduced from 648 lines to ~60 lines for better performance.

Previous version had extensive error handling, type checking, and abstractions.
New version: Simple, direct Redis operations with basic error handling.
"""
import redis
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def get_session_data(redis_client: redis.Redis, session_id: str) -> Optional[Dict[str, str]]:
    """Get all session data."""
    try:
        data = redis_client.hgetall(f"session:{session_id}")
        if not data:
            return None
        # Convert bytes to strings if needed
        return {
            k.decode() if isinstance(k, bytes) else k:
            v.decode() if isinstance(v, bytes) else v
            for k, v in data.items()
        }
    except Exception as e:
        logger.error(f"Error getting session data for {session_id}: {e}")
        return None


def set_session_data(redis_client: redis.Redis, session_id: str, data: Dict[str, Any], ttl: int = 14400) -> bool:
    """Set session data with optional TTL."""
    try:
        redis_client.hset(f"session:{session_id}", mapping=data)
        if ttl:
            redis_client.expire(f"session:{session_id}", ttl)
        return True
    except Exception as e:
        logger.error(f"Error setting session data for {session_id}: {e}")
        return False


def delete_session(redis_client: redis.Redis, session_id: str) -> bool:
    """Delete a session."""
    try:
        return redis_client.delete(f"session:{session_id}") > 0
    except Exception as e:
        logger.error(f"Error deleting session {session_id}: {e}")
        return False


def session_exists(redis_client: redis.Redis, session_id: str) -> bool:
    """Check if session exists."""
    try:
        return redis_client.exists(f"session:{session_id}") > 0
    except Exception as e:
        logger.error(f"Error checking session existence {session_id}: {e}")
        return False


def get_all_session_ids(redis_client: redis.Redis) -> List[str]:
    """
    Get all session IDs (use sparingly - expensive operation).
    Filters out config, user, and state tracking keys.
    """
    try:
        keys = redis_client.keys("session:*")
        session_ids = []
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            # Filter out non-session keys
            if (':config' in key_str or ':user:' in key_str or
                key_str in ['session:ready', 'session:starting']):
                continue
            # Extract session ID
            session_id = key_str.replace('session:', '')
            session_ids.append(session_id)
        return session_ids
    except Exception as e:
        logger.error(f"Error getting all session IDs: {e}")
        return []


# For backward compatibility, create a simple SessionStore class
class SessionStore:
    """
    Simplified SessionStore - thin wrapper around Redis.

    Previous version: 648 lines with extensive abstractions
    Current version: ~20 lines, delegates to module functions
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client

    def get_session_data(self, session_id: str) -> Optional[Dict[str, str]]:
        return get_session_data(self.redis_client, session_id)

    def set_session_data(self, session_id: str, data: Dict[str, Any]) -> bool:
        return set_session_data(self.redis_client, session_id, data)

    def delete_session(self, session_id: str) -> bool:
        return delete_session(self.redis_client, session_id)

    def get_all_session_ids(self) -> List[str]:
        return get_all_session_ids(self.redis_client)

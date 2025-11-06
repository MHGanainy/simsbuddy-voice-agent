"""
SessionStore - Type-safe Redis operations for session management.

This module provides a centralized abstraction layer for all session-related
Redis operations, ensuring type safety, proper filtering, and consistent
error handling.

Redis Key Schema:
- session:{id} - HASH: Main session state and metadata
- session:{id}:config - HASH: Voice configuration (voiceId, openingLine, systemPrompt)
- session:ready - SET: Session IDs with running, healthy agents
- session:starting - SET: Session IDs currently spawning agents
- session:user:{email} - STRING: User to session ID mapping
- agent:{id}:pid - STRING: Agent process ID
- agent:{id}:logfile - STRING: Log file path
- agent:{id}:logs - LIST: Recent log entries (last 100)
- agent:{id}:health - HASH: Health check results
"""

import redis
import redis.exceptions
import os
from typing import List, Dict, Optional, Set, Generator
from backend.shared.logging_config import setup_logging

logger = setup_logging(service_name='session-store')


class SessionStore:
    """Type-safe Redis operations for session management with comprehensive error handling."""

    def __init__(self, redis_client: redis.Redis = None):
        """
        Initialize SessionStore.

        Args:
            redis_client: Optional Redis client. If not provided, creates a new one.
        """
        self.redis_client = redis_client or redis.from_url(
            os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        )

    def get_all_session_ids(self) -> List[str]:
        """
        Get all session IDs from session hash keys only.

        Filters out:
        - session:user:{email} (STRING) - User mappings
        - session:ready (SET) - State tracking
        - session:starting (SET) - State tracking
        - session:{id}:config (HASH) - Config keys (not main session)

        Returns:
            List of session IDs (e.g., ['sim_abc123', 'sim_def456'])
            Returns empty list on error.
        """
        try:
            all_keys = self.redis_client.keys('session:*')
            session_ids = []

            for key in all_keys:
                try:
                    key_str = key.decode() if isinstance(key, bytes) else key

                    # Apply filtering
                    if (':user:' in key_str or
                        key_str in ['session:ready', 'session:starting'] or
                        ':config' in key_str):
                        continue

                    # Verify it's actually a hash type
                    key_type = self.redis_client.type(key)
                    key_type_str = key_type.decode('utf-8') if isinstance(key_type, bytes) else key_type

                    if key_type_str != 'hash':
                        logger.warning("get_all_session_ids_unexpected_type",
                                     key=key_str,
                                     expected='hash',
                                     actual=key_type_str)
                        continue

                    # Extract session ID (everything after first colon)
                    session_id = key_str.split(':', 1)[1]
                    session_ids.append(session_id)

                except Exception as e:
                    # Log but continue processing other keys
                    logger.warning("get_all_session_ids_key_processing_error",
                                 key=str(key),
                                 error=str(e))
                    continue

            return session_ids

        except redis.exceptions.ConnectionError as e:
            logger.error("get_all_session_ids_connection_error",
                        error=str(e))
            return []
        except redis.exceptions.TimeoutError as e:
            logger.error("get_all_session_ids_timeout_error",
                        error=str(e))
            return []
        except redis.exceptions.ResponseError as e:
            logger.error("get_all_session_ids_response_error",
                        error=str(e))
            return []
        except redis.exceptions.RedisError as e:
            logger.error("get_all_session_ids_redis_error",
                        error=str(e))
            return []
        except Exception as e:
            logger.error("get_all_session_ids_unexpected_error",
                        error=str(e),
                        exc_info=True)
            return []

    def scan_session_ids(self, count: int = 100) -> Generator[str, None, None]:
        """
        Iterate over session IDs using SCAN (non-blocking).

        This is the preferred method for production use as it doesn't
        block Redis like KEYS does.

        Args:
            count: Number of keys to fetch per iteration

        Yields:
            session_id: Individual session IDs
            Yields nothing on error (gracefully terminates iteration)
        """
        try:
            cursor = 0

            while True:
                try:
                    cursor, keys = self.redis_client.scan(
                        cursor,
                        match='session:*',
                        count=count
                    )

                    for key in keys:
                        try:
                            key_str = key.decode() if isinstance(key, bytes) else key

                            # Apply filtering
                            if (':user:' in key_str or
                                key_str in ['session:ready', 'session:starting'] or
                                ':config' in key_str):
                                continue

                            # Verify type
                            key_type = self.redis_client.type(key)
                            key_type_str = key_type.decode('utf-8') if isinstance(key_type, bytes) else key_type

                            if key_type_str == 'hash':
                                session_id = key_str.split(':', 1)[1]
                                yield session_id

                        except Exception as e:
                            logger.warning("scan_session_ids_key_processing_error",
                                         key=str(key),
                                         error=str(e))
                            continue

                    if cursor == 0:
                        break

                except redis.exceptions.ConnectionError as e:
                    logger.error("scan_session_ids_connection_error",
                                cursor=cursor,
                                error=str(e))
                    break
                except redis.exceptions.TimeoutError as e:
                    logger.error("scan_session_ids_timeout_error",
                                cursor=cursor,
                                error=str(e))
                    break
                except redis.exceptions.ResponseError as e:
                    logger.error("scan_session_ids_response_error",
                                cursor=cursor,
                                error=str(e))
                    break
                except redis.exceptions.RedisError as e:
                    logger.error("scan_session_ids_redis_error",
                                cursor=cursor,
                                error=str(e))
                    break

        except Exception as e:
            logger.error("scan_session_ids_unexpected_error",
                        error=str(e),
                        exc_info=True)

    def get_session_data(self, session_id: str) -> Optional[Dict[str, str]]:
        """
        Get session hash data with type safety and error handling.

        Args:
            session_id: The session identifier

        Returns:
            Dictionary of session data, or None if not found, wrong type, or error
        """
        key = f'session:{session_id}'

        try:
            if not self.redis_client.exists(key):
                return None

            # Verify it's a hash
            key_type = self.redis_client.type(key)
            key_type_str = key_type.decode('utf-8') if isinstance(key_type, bytes) else key_type

            if key_type_str != 'hash':
                logger.warning("get_session_data_wrong_type",
                            session_id=session_id,
                            expected='hash',
                            actual=key_type_str)
                return None

            # Get data and decode
            data = self.redis_client.hgetall(key)

            if not data:
                return None

            # Decode bytes to strings
            return {
                k.decode('utf-8') if isinstance(k, bytes) else k:
                v.decode('utf-8') if isinstance(v, bytes) else v
                for k, v in data.items()
            }

        except redis.exceptions.ConnectionError as e:
            logger.error("get_session_data_connection_error",
                        session_id=session_id,
                        error=str(e))
            return None
        except redis.exceptions.TimeoutError as e:
            logger.error("get_session_data_timeout_error",
                        session_id=session_id,
                        error=str(e))
            return None
        except redis.exceptions.ResponseError as e:
            logger.error("get_session_data_response_error",
                        session_id=session_id,
                        error=str(e))
            return None
        except redis.exceptions.RedisError as e:
            logger.error("get_session_data_redis_error",
                        session_id=session_id,
                        error=str(e))
            return None
        except Exception as e:
            logger.error("get_session_data_unexpected_error",
                        session_id=session_id,
                        error=str(e),
                        exc_info=True)
            return None

    def get_session_config(self, session_id: str) -> Optional[Dict[str, str]]:
        """
        Get session configuration data with error handling.

        Args:
            session_id: The session identifier

        Returns:
            Dictionary of config data (voiceId, openingLine, systemPrompt), or None on error
        """
        key = f'session:{session_id}:config'

        try:
            if not self.redis_client.exists(key):
                return None

            data = self.redis_client.hgetall(key)

            if not data:
                return None

            return {
                k.decode('utf-8') if isinstance(k, bytes) else k:
                v.decode('utf-8') if isinstance(v, bytes) else v
                for k, v in data.items()
            }

        except redis.exceptions.ConnectionError as e:
            logger.error("get_session_config_connection_error",
                        session_id=session_id,
                        error=str(e))
            return None
        except redis.exceptions.TimeoutError as e:
            logger.error("get_session_config_timeout_error",
                        session_id=session_id,
                        error=str(e))
            return None
        except redis.exceptions.ResponseError as e:
            logger.error("get_session_config_response_error",
                        session_id=session_id,
                        error=str(e))
            return None
        except redis.exceptions.RedisError as e:
            logger.error("get_session_config_redis_error",
                        session_id=session_id,
                        error=str(e))
            return None
        except Exception as e:
            logger.error("get_session_config_unexpected_error",
                        session_id=session_id,
                        error=str(e),
                        exc_info=True)
            return None

    def is_session_ready(self, session_id: str) -> bool:
        """
        Check if session is in the ready state with error handling.

        Args:
            session_id: The session identifier

        Returns:
            True if session is in session:ready SET, False on error or not found
        """
        try:
            return bool(self.redis_client.sismember('session:ready', session_id))

        except redis.exceptions.ConnectionError as e:
            logger.error("is_session_ready_connection_error",
                        session_id=session_id,
                        error=str(e))
            return False
        except redis.exceptions.TimeoutError as e:
            logger.error("is_session_ready_timeout_error",
                        session_id=session_id,
                        error=str(e))
            return False
        except redis.exceptions.ResponseError as e:
            logger.error("is_session_ready_response_error",
                        session_id=session_id,
                        error=str(e))
            return False
        except redis.exceptions.RedisError as e:
            logger.error("is_session_ready_redis_error",
                        session_id=session_id,
                        error=str(e))
            return False
        except Exception as e:
            logger.error("is_session_ready_unexpected_error",
                        session_id=session_id,
                        error=str(e),
                        exc_info=True)
            return False

    def is_session_starting(self, session_id: str) -> bool:
        """
        Check if session is in the starting state with error handling.

        Args:
            session_id: The session identifier

        Returns:
            True if session is in session:starting SET, False on error or not found
        """
        try:
            return bool(self.redis_client.sismember('session:starting', session_id))

        except redis.exceptions.ConnectionError as e:
            logger.error("is_session_starting_connection_error",
                        session_id=session_id,
                        error=str(e))
            return False
        except redis.exceptions.TimeoutError as e:
            logger.error("is_session_starting_timeout_error",
                        session_id=session_id,
                        error=str(e))
            return False
        except redis.exceptions.ResponseError as e:
            logger.error("is_session_starting_response_error",
                        session_id=session_id,
                        error=str(e))
            return False
        except redis.exceptions.RedisError as e:
            logger.error("is_session_starting_redis_error",
                        session_id=session_id,
                        error=str(e))
            return False
        except Exception as e:
            logger.error("is_session_starting_unexpected_error",
                        session_id=session_id,
                        error=str(e),
                        exc_info=True)
            return False

    def get_ready_sessions(self) -> Set[str]:
        """
        Get all session IDs in ready state with error handling.

        Returns:
            Set of session IDs, empty set on error
        """
        try:
            members = self.redis_client.smembers('session:ready')
            return {
                m.decode('utf-8') if isinstance(m, bytes) else m
                for m in members
            }

        except redis.exceptions.ConnectionError as e:
            logger.error("get_ready_sessions_connection_error",
                        error=str(e))
            return set()
        except redis.exceptions.TimeoutError as e:
            logger.error("get_ready_sessions_timeout_error",
                        error=str(e))
            return set()
        except redis.exceptions.ResponseError as e:
            logger.error("get_ready_sessions_response_error",
                        error=str(e))
            return set()
        except redis.exceptions.RedisError as e:
            logger.error("get_ready_sessions_redis_error",
                        error=str(e))
            return set()
        except Exception as e:
            logger.error("get_ready_sessions_unexpected_error",
                        error=str(e),
                        exc_info=True)
            return set()

    def get_starting_sessions(self) -> Set[str]:
        """
        Get all session IDs in starting state with error handling.

        Returns:
            Set of session IDs, empty set on error
        """
        try:
            members = self.redis_client.smembers('session:starting')
            return {
                m.decode('utf-8') if isinstance(m, bytes) else m
                for m in members
            }

        except redis.exceptions.ConnectionError as e:
            logger.error("get_starting_sessions_connection_error",
                        error=str(e))
            return set()
        except redis.exceptions.TimeoutError as e:
            logger.error("get_starting_sessions_timeout_error",
                        error=str(e))
            return set()
        except redis.exceptions.ResponseError as e:
            logger.error("get_starting_sessions_response_error",
                        error=str(e))
            return set()
        except redis.exceptions.RedisError as e:
            logger.error("get_starting_sessions_redis_error",
                        error=str(e))
            return set()
        except Exception as e:
            logger.error("get_starting_sessions_unexpected_error",
                        error=str(e),
                        exc_info=True)
            return set()

    def cleanup_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """
        Comprehensive cleanup of all session-related keys with error handling.

        Deletes:
        - session:{id}
        - session:{id}:config
        - agent:{id}:pid
        - agent:{id}:logs
        - agent:{id}:logfile
        - agent:{id}:health
        - session:user:{user_id} (if provided)

        Removes from SETs:
        - session:ready
        - session:starting

        Args:
            session_id: The session identifier
            user_id: Optional user ID for user mapping cleanup

        Returns:
            True if cleanup succeeded, False if any errors occurred
        """
        try:
            # Delete hash keys
            self.redis_client.delete(f'session:{session_id}')
            self.redis_client.delete(f'session:{session_id}:config')

            # Delete agent keys
            self.redis_client.delete(f'agent:{session_id}:pid')
            self.redis_client.delete(f'agent:{session_id}:logs')
            self.redis_client.delete(f'agent:{session_id}:logfile')
            self.redis_client.delete(f'agent:{session_id}:health')

            # Remove from state tracking SETs
            self.redis_client.srem('session:ready', session_id)
            self.redis_client.srem('session:starting', session_id)

            # Delete user mapping if provided
            if user_id:
                self.redis_client.delete(f'session:user:{user_id}')

            logger.info("session_cleanup_complete",
                       session_id=session_id,
                       user_id=user_id)
            return True

        except redis.exceptions.ConnectionError as e:
            logger.error("cleanup_session_connection_error",
                        session_id=session_id,
                        user_id=user_id,
                        error=str(e))
            return False
        except redis.exceptions.TimeoutError as e:
            logger.error("cleanup_session_timeout_error",
                        session_id=session_id,
                        user_id=user_id,
                        error=str(e))
            return False
        except redis.exceptions.ResponseError as e:
            logger.error("cleanup_session_response_error",
                        session_id=session_id,
                        user_id=user_id,
                        error=str(e))
            return False
        except redis.exceptions.RedisError as e:
            logger.error("cleanup_session_redis_error",
                        session_id=session_id,
                        user_id=user_id,
                        error=str(e))
            return False
        except Exception as e:
            logger.error("cleanup_session_unexpected_error",
                        session_id=session_id,
                        user_id=user_id,
                        error=str(e),
                        exc_info=True)
            return False

    def validate_redis_schema(self) -> Dict[str, any]:
        """
        Validate and report on Redis key schema compliance with error handling.

        Useful for debugging and monitoring.

        Returns:
            Dictionary with validation results and statistics
            Returns error dict on failure
        """
        try:
            all_keys = self.redis_client.keys('session:*')

            stats = {
                'total_session_keys': len(all_keys),
                'session_hashes': 0,
                'config_hashes': 0,
                'user_strings': 0,
                'state_sets': 0,
                'unexpected_types': [],
                'unexpected_patterns': []
            }

            for key in all_keys:
                try:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    key_type = self.redis_client.type(key)
                    key_type_str = key_type.decode('utf-8') if isinstance(key_type, bytes) else key_type

                    # Categorize
                    if key_str in ['session:ready', 'session:starting']:
                        stats['state_sets'] += 1
                        if key_type_str != 'set':
                            stats['unexpected_types'].append({
                                'key': key_str,
                                'expected': 'set',
                                'actual': key_type_str
                            })

                    elif ':user:' in key_str:
                        stats['user_strings'] += 1
                        if key_type_str != 'string':
                            stats['unexpected_types'].append({
                                'key': key_str,
                                'expected': 'string',
                                'actual': key_type_str
                            })

                    elif ':config' in key_str:
                        stats['config_hashes'] += 1
                        if key_type_str != 'hash':
                            stats['unexpected_types'].append({
                                'key': key_str,
                                'expected': 'hash',
                                'actual': key_type_str
                            })

                    elif key_str.startswith('session:') and key_str.count(':') == 1:
                        stats['session_hashes'] += 1
                        if key_type_str != 'hash':
                            stats['unexpected_types'].append({
                                'key': key_str,
                                'expected': 'hash',
                                'actual': key_type_str
                            })

                    else:
                        stats['unexpected_patterns'].append({
                            'key': key_str,
                            'type': key_type_str
                        })

                except Exception as e:
                    logger.warning("validate_redis_schema_key_processing_error",
                                 key=str(key),
                                 error=str(e))
                    continue

            return stats

        except redis.exceptions.ConnectionError as e:
            logger.error("validate_redis_schema_connection_error",
                        error=str(e))
            return {'error': 'connection_error', 'message': str(e)}
        except redis.exceptions.TimeoutError as e:
            logger.error("validate_redis_schema_timeout_error",
                        error=str(e))
            return {'error': 'timeout_error', 'message': str(e)}
        except redis.exceptions.ResponseError as e:
            logger.error("validate_redis_schema_response_error",
                        error=str(e))
            return {'error': 'response_error', 'message': str(e)}
        except redis.exceptions.RedisError as e:
            logger.error("validate_redis_schema_redis_error",
                        error=str(e))
            return {'error': 'redis_error', 'message': str(e)}
        except Exception as e:
            logger.error("validate_redis_schema_unexpected_error",
                        error=str(e),
                        exc_info=True)
            return {'error': 'unexpected_error', 'message': str(e)}

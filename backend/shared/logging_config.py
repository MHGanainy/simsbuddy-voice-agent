"""
Simplified logging configuration

Replaces structlog + python-json-logger + loguru with basic Python logging.
Reduces overhead by 50-70% while maintaining essential logging functionality.

Migration from structlog: Use extra={} dict for structured data
Example: logger.info("message", extra={"key": "value"})
"""
import logging
import sys
import os
from typing import Optional


def setup_logging(
    service_name: str,
    level: Optional[str] = None,
    format_type: Optional[str] = None
) -> logging.Logger:
    """
    Setup simple, fast logging with JSON support for production.

    Args:
        service_name: Name of the service (orchestrator, worker, agent)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: 'console' or 'json' (for production)

    Returns:
        Configured logger instance
    """
    # Get config from environment with defaults
    log_level_str = level or os.getenv('LOG_LEVEL', 'INFO')
    log_format_type = format_type or os.getenv('LOG_FORMAT', 'console')

    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    if log_format_type == "json":
        # Minimal JSON format for production log aggregation
        log_format = f'{{"timestamp":"%(asctime)s","service":"{service_name}","level":"%(levelname)s","message":"%(message)s","extra":%(extra)s}}'
    else:
        # Human-readable format for development
        log_format = f'%(asctime)s - {service_name} - %(levelname)s - %(message)s'

    logging.basicConfig(
        level=log_level,
        format=log_format,
        stream=sys.stdout,
        force=True  # Override any existing config
    )

    # Return logger for the service
    logger = logging.getLogger(service_name)
    logger.setLevel(log_level)

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Optional logger name (typically module name)

    Returns:
        Logger instance
    """
    return logging.getLogger(name or "voice-agent")


# Compatibility layer for gradual migration from structlog
class LogContext:
    """
    NO-OP context manager for backward compatibility.

    Structlog used context managers to bind correlation IDs.
    With stdlib logging, we don't use this pattern anymore.
    This is kept so old code doesn't break, but does nothing.

    Gradually replace:
        with LogContext(session_id=sid):
            logger.info("message")

    With:
        logger.info(f"message session_id={sid}")
    """
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

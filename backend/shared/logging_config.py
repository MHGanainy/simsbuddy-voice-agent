"""
Smart layered logging configuration for all services.

Features:
- Structured JSON logs for production
- Pretty console logs for development
- Correlation IDs (session_id, task_id, request_id, user_id)
- Consistent format across all services
- Performance metrics
- Context managers for automatic correlation tracking

Usage:
    from backend.shared.logging_config import setup_logging, get_logger, LogContext

    # Setup logging at service startup
    logger = setup_logging(service_name='orchestrator')

    # Use logger throughout your code
    logger.info("operation_started", user_id="123", session_id="abc")

    # Use context manager for automatic correlation
    with LogContext(session_id="abc", user_id="123"):
        logger.info("processing_request")  # Automatically includes session_id and user_id
"""

import os
import sys
import logging
import structlog
from pythonjsonlogger import jsonlogger
from typing import Optional, Dict, Any

# Configuration from environment
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_FORMAT = os.getenv('LOG_FORMAT', 'console')  # 'console' or 'json'
SERVICE_NAME = os.getenv('SERVICE_NAME', 'unknown')


def setup_logging(service_name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """
    Setup structured logging for the service.

    Configures structlog with appropriate processors for development or production.
    In development (LOG_FORMAT='console'), uses pretty colored output.
    In production (LOG_FORMAT='json'), uses JSON output for easy parsing.

    Args:
        service_name: Name of the service (orchestrator/celery-worker/voice-agent)
                     If None, uses SERVICE_NAME environment variable

    Returns:
        Configured logger instance bound with service name

    Example:
        >>> logger = setup_logging(service_name='orchestrator')
        >>> logger.info("service_started", port=8000)
    """
    # Use provided service_name or fall back to env var
    service = service_name or SERVICE_NAME

    # Configure structlog processors
    if LOG_FORMAT == 'json':
        # Production: JSON logs for aggregation and parsing
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ]
    else:
        # Development: Pretty console logs with colors
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(colors=True)
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, LOG_LEVEL),
    )

    # Create logger bound with service name
    logger = structlog.get_logger()
    logger = logger.bind(service=service)

    return logger


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """
    Get a logger instance with optional name.

    Args:
        name: Optional logger name (typically module name)

    Returns:
        Logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("operation_completed")
    """
    return structlog.get_logger(name)


class LogContext:
    """
    Context manager to add correlation IDs to all logs within the context.

    Automatically binds correlation IDs (session_id, task_id, user_id, etc.)
    to all log statements within the context. IDs are automatically cleared
    when exiting the context.

    Example:
        >>> with LogContext(session_id="abc123", user_id="user_456"):
        ...     logger.info("processing_request")
        ...     # Logs will include session_id and user_id automatically
        ...     process_request()
        # session_id and user_id are cleared after context exit

    Attributes:
        context: Dictionary of correlation IDs to bind
    """

    def __init__(self, **kwargs: Any):
        """
        Initialize context with correlation IDs.

        Args:
            **kwargs: Correlation IDs (session_id, task_id, user_id, request_id, etc.)
        """
        self.context = kwargs
        self.token = None

    def __enter__(self) -> 'LogContext':
        """Bind correlation IDs to context variables."""
        self.token = structlog.contextvars.bind_contextvars(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clear correlation IDs from context variables."""
        structlog.contextvars.unbind_contextvars(*self.context.keys())


def add_correlation_id(logger: structlog.stdlib.BoundLogger, **kwargs: Any) -> structlog.stdlib.BoundLogger:
    """
    Manually bind correlation IDs to a logger instance.

    Use this when you can't use LogContext (e.g., long-running operations).

    Args:
        logger: Logger instance to bind to
        **kwargs: Correlation IDs to bind

    Returns:
        Logger with bound correlation IDs

    Example:
        >>> logger = get_logger()
        >>> logger = add_correlation_id(logger, session_id="abc123")
        >>> logger.info("processing")  # Includes session_id
    """
    return logger.bind(**kwargs)


# Logging level helpers
def set_log_level(level: str):
    """
    Dynamically change log level at runtime.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Example:
        >>> set_log_level('DEBUG')
    """
    logging.getLogger().setLevel(getattr(logging, level.upper()))


def get_log_level() -> str:
    """Get current log level."""
    return logging.getLevelName(logging.getLogger().level)

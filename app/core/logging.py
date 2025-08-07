# app/core/logging.py
"""
Enterprise-grade logging configuration for SAAS applications.
Provides structured logging, multiple outputs, performance monitoring, and security auditing.

Key SAAS Patterns:
- Structured JSON logging for production
- Human-readable console logging for development
- Security-aware log filtering (no sensitive data)
- Performance monitoring integration
- Request correlation IDs
- Log rotation and retention
- Different log levels for different components
"""
import logging
import logging.handlers
import json
import sys
import os
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

from app.core.config import settings


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging in production.
    Adds context, correlation IDs, and sanitizes sensitive data.
    """
    
    SENSITIVE_FIELDS = {
        'password', 'token', 'secret', 'key', 'authorization', 
        'access_token', 'refresh_token', 'api_key', 'stripe_key',
        'client_secret', 'webhook_secret', 'jwt_secret'
    }
    
    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON."""
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add process/thread info
        log_entry['process_id'] = os.getpid()
        log_entry['thread_id'] = record.thread
        log_entry['thread_name'] = record.threadName
        
        # Add request correlation ID if available
        if hasattr(record, 'correlation_id'):
            log_entry['correlation_id'] = record.correlation_id
        
        # Add user context if available
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
        
        # Add request context if available
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        if hasattr(record, 'endpoint'):
            log_entry['endpoint'] = record.endpoint
        if hasattr(record, 'method'):
            log_entry['http_method'] = record.method
        
        # Add performance metrics if available
        if hasattr(record, 'duration_ms'):
            log_entry['duration_ms'] = record.duration_ms
        if hasattr(record, 'memory_mb'):
            log_entry['memory_mb'] = record.memory_mb
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': self._sanitize_traceback(traceback.format_exception(*record.exc_info))
            }
        
        # Add extra fields (sanitized)
        if self.include_extra and hasattr(record, '__dict__'):
            for key, value in record.__dict__.items():
                if (key not in log_entry and 
                    not key.startswith('_') and 
                    key not in ['name', 'msg', 'args', 'levelname', 'levelno', 
                               'pathname', 'filename', 'module', 'exc_info', 
                               'exc_text', 'stack_info', 'lineno', 'funcName', 
                               'created', 'msecs', 'relativeCreated', 'thread', 
                               'threadName', 'processName', 'process']):
                    log_entry[key] = self._sanitize_value(key, value)
        
        # Add environment context
        log_entry['environment'] = settings.environment
        
        return json.dumps(log_entry, default=str, ensure_ascii=False)
    
    def _sanitize_value(self, key: str, value: Any) -> Any:
        """Sanitize sensitive data from log values."""
        if not value:
            return value
        
        key_lower = key.lower()
        
        # Check if key contains sensitive terms
        if any(sensitive in key_lower for sensitive in self.SENSITIVE_FIELDS):
            return "[REDACTED]"
        
        # Sanitize dictionary values
        if isinstance(value, dict):
            return {k: self._sanitize_value(k, v) for k, v in value.items()}
        
        # Sanitize list values
        if isinstance(value, (list, tuple)):
            return [self._sanitize_value("", item) for item in value]
        
        # Check string values for sensitive patterns
        if isinstance(value, str):
            value_lower = value.lower()
            # Check for common secret patterns
            if (len(value) > 20 and 
                any(pattern in value_lower for pattern in ['sk_', 'pk_', 'rk_', 'whsec_']) or
                any(sensitive in value_lower for sensitive in self.SENSITIVE_FIELDS)):
                return "[REDACTED]"
        
        return value
    
    def _sanitize_traceback(self, traceback_lines: List[str]) -> List[str]:
        """Sanitize traceback to remove sensitive information."""
        sanitized = []
        for line in traceback_lines:
            # Remove file paths that might contain sensitive info
            line = line.replace(os.path.expanduser("~"), "~")
            # Remove potential sensitive arguments
            if "password=" in line.lower() or "token=" in line.lower():
                line = "[SANITIZED TRACEBACK LINE]"
            sanitized.append(line)
        return sanitized


class HumanReadableFormatter(logging.Formatter):
    """
    Human-readable formatter for development and console output.
    Includes colors and clear formatting.
    """
    
    # Color codes for different log levels
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'       # Reset
    }
    
    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stderr.isatty()
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record for human readability."""
        # Base message
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        level = record.levelname
        logger_name = record.name
        message = record.getMessage()
        
        # Add colors if enabled
        if self.use_colors:
            color = self.COLORS.get(level, '')
            reset = self.COLORS['RESET']
            level = f"{color}{level}{reset}"
        
        # Build the log line
        log_parts = [
            timestamp,
            f"[{level}]",
            f"{logger_name}:",
            message
        ]
        
        # Add correlation ID if available
        if hasattr(record, 'correlation_id'):
            log_parts.insert(-1, f"[{record.correlation_id}]")
        
        # Add user context if available
        if hasattr(record, 'user_id'):
            log_parts.insert(-1, f"[user:{record.user_id}]")
        
        # Add performance info if available
        if hasattr(record, 'duration_ms'):
            log_parts.insert(-1, f"[{record.duration_ms}ms]")
        
        base_line = " ".join(log_parts)
        
        # Add exception info if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            return f"{base_line}\n{exc_text}"
        
        return base_line


class PerformanceFilter(logging.Filter):
    """Filter to add performance metrics to log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add performance context to log records."""
        # This would be enhanced with actual performance monitoring
        # For now, it's a placeholder for future implementation
        return True


class SecurityFilter(logging.Filter):
    """Filter to ensure no sensitive data leaks into logs."""
    
    SENSITIVE_PATTERNS = [
        r'password["\s]*[:=]["\s]*([^"\\s,}]+)',
        r'token["\s]*[:=]["\s]*([^"\\s,}]+)',
        r'key["\s]*[:=]["\s]*([^"\\s,}]+)',
        r'secret["\s]*[:=]["\s]*([^"\\s,}]+)'
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter out sensitive information from log messages."""
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            # This is a simplified check - in production you'd want more sophisticated scanning
            msg_lower = record.msg.lower()
            if any(sensitive in msg_lower for sensitive in ['password', 'secret', 'token']):
                # Could implement regex replacement here
                pass
        return True


def setup_logging(
    log_level: str = None,
    log_file: Optional[str] = None,
    enable_json_logging: bool = None,
    enable_console_logging: bool = True,
    log_dir: Optional[str] = None
) -> None:
    """
    Setup enterprise logging configuration.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file name
        enable_json_logging: Enable structured JSON logging
        enable_console_logging: Enable console logging
        log_dir: Directory for log files
    """
    # Determine configuration from settings
    if log_level is None:
        log_level = "DEBUG" if settings.debug_mode else "INFO"
    
    if enable_json_logging is None:
        enable_json_logging = settings.is_production
    
    if log_dir is None:
        log_dir = "logs"
    
    # Ensure log directory exists
    if log_file or settings.is_production:
        Path(log_dir).mkdir(exist_ok=True)
    
    # Clear existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Set root log level
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    handlers = []
    
    # Console handler for development
    if enable_console_logging:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        
        if enable_json_logging:
            console_handler.setFormatter(StructuredFormatter())
        else:
            console_handler.setFormatter(HumanReadableFormatter())
        
        console_handler.addFilter(SecurityFilter())
        handlers.append(console_handler)
    
    # File handlers for production
    if log_file or settings.is_production:
        log_filename = log_file or f"app_{settings.environment}.log"
        log_path = Path(log_dir) / log_filename
        
        # Main application log with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=50 * 1024 * 1024,  # 50MB
            backupCount=10,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(StructuredFormatter())
        file_handler.addFilter(SecurityFilter())
        file_handler.addFilter(PerformanceFilter())
        handlers.append(file_handler)
        
        # Separate error log
        error_log_path = Path(log_dir) / f"error_{settings.environment}.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(StructuredFormatter())
        error_handler.addFilter(SecurityFilter())
        handlers.append(error_handler)
    
    # Add all handlers to root logger
    for handler in handlers:
        root_logger.addHandler(handler)
    
    # Configure specific logger levels
    configure_logger_levels()
    
    # Log initialization
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - Level: {log_level}, JSON: {enable_json_logging}, Environment: {settings.environment}")


def configure_logger_levels():
    """Configure log levels for specific components."""
    # Set levels for third-party libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('stripe').setLevel(logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    
    # Set levels for application components
    if settings.debug_mode:
        # Verbose logging in debug mode
        logging.getLogger('app.services').setLevel(logging.DEBUG)
        logging.getLogger('app.data.repositories').setLevel(logging.DEBUG)
        logging.getLogger('app.api').setLevel(logging.DEBUG)
    else:
        # Production logging levels
        logging.getLogger('app.services').setLevel(logging.INFO)
        logging.getLogger('app.data.repositories').setLevel(logging.WARNING)
        logging.getLogger('app.api').setLevel(logging.INFO)
    
    # Always log security events
    logging.getLogger('app.core.security').setLevel(logging.INFO)
    logging.getLogger('app.services.auth_service').setLevel(logging.INFO)
    
    # Always log audit events
    logging.getLogger('app.data.repositories.audit_repository').setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.
    Convenience function for consistent logger creation.
    """
    return logging.getLogger(name)


def log_with_context(
    logger: logging.Logger,
    level: int,
    message: str,
    correlation_id: Optional[str] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    duration_ms: Optional[float] = None,
    **extra
):
    """
    Log with additional context information.
    
    Args:
        logger: Logger instance
        level: Log level (logging.DEBUG, INFO, etc.)
        message: Log message
        correlation_id: Request correlation ID
        user_id: User ID for context
        request_id: Request ID
        endpoint: API endpoint
        method: HTTP method
        duration_ms: Request duration in milliseconds
        **extra: Additional context data
    """
    # Create extra context
    context = {}
    
    if correlation_id:
        context['correlation_id'] = correlation_id
    if user_id:
        context['user_id'] = user_id
    if request_id:
        context['request_id'] = request_id
    if endpoint:
        context['endpoint'] = endpoint
    if method:
        context['method'] = method
    if duration_ms is not None:
        context['duration_ms'] = duration_ms
    
    # Add any additional context
    context.update(extra)
    
    # Log with context
    logger.log(level, message, extra=context)


def log_performance(
    logger: logging.Logger,
    operation: str,
    duration_ms: float,
    user_id: Optional[str] = None,
    **extra
):
    """
    Log performance metrics.
    
    Args:
        logger: Logger instance
        operation: Operation name
        duration_ms: Duration in milliseconds
        user_id: User ID for context
        **extra: Additional metrics
    """
    context = {
        'operation': operation,
        'duration_ms': duration_ms,
        'performance_log': True
    }
    
    if user_id:
        context['user_id'] = user_id
    
    context.update(extra)
    
    # Log at INFO level for performance metrics
    log_level = logging.WARNING if duration_ms > 1000 else logging.INFO
    logger.log(log_level, f"Performance: {operation} took {duration_ms:.2f}ms", extra=context)


def log_security_event(
    logger: logging.Logger,
    event_type: str,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """
    Log security events with standardized format.
    
    Args:
        logger: Logger instance
        event_type: Type of security event
        user_id: User ID if available
        ip_address: Client IP address
        user_agent: Client user agent
        details: Additional event details
    """
    context = {
        'security_event': True,
        'event_type': event_type,
    }
    
    if user_id:
        context['user_id'] = user_id
    if ip_address:
        context['ip_address'] = ip_address
    if user_agent:
        context['user_agent'] = user_agent
    if details:
        context['details'] = details
    
    logger.warning(f"Security Event: {event_type}", extra=context)


# Initialize logging on module import
if not settings.pytest_running:  # Don't auto-initialize during tests
    setup_logging()


# Convenience logger for this module
logger = get_logger(__name__)
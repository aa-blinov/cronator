"""Simple logging module for Cronator scripts.

Usage:
    from cronator_lib import get_logger
    
    log = get_logger()
    log.info("Starting task...")
    log.warning("Something might be wrong")
    log.error("An error occurred", exc_info=True)
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any


class CronatorFormatter(logging.Formatter):
    """Custom formatter that outputs JSON for easy parsing."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data
        
        # Add newline for proper streaming
        return json.dumps(log_entry) + "\n"


class PrettyFormatter(logging.Formatter):
    """Human-readable formatter with colors."""
    
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Format the message
        msg = f"{color}[{timestamp}] {record.levelname:8}{self.RESET} {record.getMessage()}"
        
        # Add exception if present
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        
        return msg


class CronatorLogger(logging.Logger):
    """Extended logger with additional convenience methods."""
    
    def __init__(self, name: str = "cronator_script", level: int = logging.INFO):
        super().__init__(name, level)
        self._setup_handlers()
    
    def _setup_handlers(self) -> None:
        """Setup stdout and stderr handlers."""
        # Determine if we're running in Cronator context
        is_cronator = bool(os.environ.get("CRONATOR_EXECUTION_ID"))
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        
        if is_cronator:
            # Use JSON format when running under Cronator
            console_handler.setFormatter(CronatorFormatter())
        else:
            # Use pretty format for local development
            console_handler.setFormatter(PrettyFormatter())
        
        self.addHandler(console_handler)
    
    def success(self, msg: str, *args, **kwargs) -> None:
        """Log a success message (INFO level with success marker)."""
        self.info(f"[SUCCESS] {msg}", *args, **kwargs)
    
    def task_start(self, task_name: str) -> None:
        """Log the start of a task."""
        self.info(f"[STARTING] {task_name}")
    
    def task_end(self, task_name: str, success: bool = True) -> None:
        """Log the end of a task."""
        if success:
            self.info(f"[COMPLETED] {task_name}")
        else:
            self.error(f"[FAILED] {task_name}")
    
    def with_data(self, msg: str, **data: Any) -> None:
        """Log a message with additional structured data."""
        record = self.makeRecord(
            self.name, logging.INFO, "", 0, msg, (), None
        )
        record.extra_data = data
        self.handle(record)
    
    def progress(self, current: int, total: int, task: str = "") -> None:
        """Log progress."""
        percent = (current / total * 100) if total > 0 else 0
        bar_length = 20
        filled = int(bar_length * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_length - filled)
        
        msg = f"[{bar}] {percent:.1f}% ({current}/{total})"
        if task:
            msg += f" - {task}"
        
        self.info(msg)


# Global logger instance cache
_loggers: dict[str, CronatorLogger] = {}


def get_logger(name: str | None = None) -> CronatorLogger:
    """
    Get a Cronator logger instance.
    
    Args:
        name: Logger name. If None, uses the script name from environment
              or defaults to "cronator_script".
    
    Returns:
        CronatorLogger instance
    
    Example:
        from cronator_lib import get_logger
        
        log = get_logger()
        log.info("Hello from Cronator!")
        log.success("Task completed successfully")
        log.error("Something went wrong", exc_info=True)
    """
    if name is None:
        name = os.environ.get("CRONATOR_SCRIPT_NAME", "cronator_script")
    
    if name not in _loggers:
        logger = CronatorLogger(name)
        _loggers[name] = logger
    
    return _loggers[name]


# Convenience function for quick setup
def setup_logging(level: int = logging.INFO) -> CronatorLogger:
    """
    Quick setup for logging in a script.
    
    Args:
        level: Logging level (default: INFO)
    
    Returns:
        Configured logger
    """
    logger = get_logger()
    logger.setLevel(level)
    return logger

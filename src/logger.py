"""
WFBG-7825 Centralized Logging System

Thread-aware logging with performance timing for the WFBG-7825 DAS system.
"""

import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


class ThreadFormatter(logging.Formatter):
    """Enhanced log formatter with thread info and elapsed timing."""

    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self._start_time = time.perf_counter()

    def format(self, record):
        elapsed_ms = (time.perf_counter() - self._start_time) * 1000
        record.elapsed_ms = f"{elapsed_ms:10.1f}"
        record.thread_name = threading.current_thread().name
        record.thread_id = threading.current_thread().ident
        return super().format(record)


def setup_logging(
    level: int = logging.DEBUG,
    log_file: Optional[str] = None,
    console: bool = True
) -> logging.Logger:
    """Configure centralized logging system."""
    logger = logging.getLogger("wfbg7825")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt_string = "[%(elapsed_ms)s ms] [%(thread_name)-15s] [%(levelname)-5s] %(name)-20s: %(message)s"
    formatter = ThreadFormatter(fmt_string)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Create module-specific logger within the wfbg7825 namespace."""
    return logging.getLogger(f"wfbg7825.{name}")


def log_timing(logger: logging.Logger):
    """Decorator factory for automatic function execution timing."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                logger.debug(f"{func.__name__} completed in {elapsed:.2f} ms")
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                logger.error(f"{func.__name__} failed after {elapsed:.2f} ms: {e}")
                raise
        return wrapper
    return decorator


class PerformanceTimer:
    """Context manager for measuring code block execution time."""

    def __init__(self, logger: logging.Logger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time = 0

    def __enter__(self):
        self.start_time = time.perf_counter()
        self.logger.debug(f"{self.operation} - started")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (time.perf_counter() - self.start_time) * 1000
        if exc_type:
            self.logger.error(f"{self.operation} - failed after {elapsed:.2f} ms: {exc_val}")
        else:
            self.logger.debug(f"{self.operation} - completed in {elapsed:.2f} ms")
        return False

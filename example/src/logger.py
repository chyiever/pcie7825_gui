"""
PCIe-7821 Centralized Logging System

This module provides comprehensive logging capabilities for the PCIe-7821 DAS
acquisition system. It features thread-aware logging with performance timing,
formatted output for debugging multi-threaded operations, and flexible output
destinations (console and file).

Key Features:
- Multi-threaded logging with thread identification
- Performance timing integration with millisecond precision
- Structured log format with elapsed time tracking
- Configurable console and file output
- UTF-8 encoding support for international characters
- Performance measurement decorators and context managers

Architecture:
- ThreadFormatter: Enhanced formatter with timing and thread info
- setup_logging(): Central logging configuration entry point
- get_logger(): Namespace-aware logger factory
- log_timing(): Performance measurement decorator
- PerformanceTimer: Context manager for code block timing

Usage:
    from logger import setup_logging, get_logger

    # Initialize logging system
    setup_logging(level=logging.INFO, log_file="app.log")

    # Get module-specific logger
    log = get_logger("acquisition")
    log.info("Starting data acquisition")

Author: PCIe-7821 Development Team
Last Modified: [Current Date]
Version: 1.0.0

Note: Thread-safe logging is guaranteed by Python's logging module.
      Performance timing uses high-resolution perf_counter() for accuracy.
"""

import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


# ----- CUSTOM FORMATTERS -----
# Enhanced logging formatters with thread information and timing

class ThreadFormatter(logging.Formatter):
    """
    Enhanced log formatter that includes thread information and elapsed timing.

    Extends the standard logging.Formatter to add:
    - Elapsed time since formatter creation (useful for performance analysis)
    - Current thread name and ID for multi-threaded debugging
    - Millisecond-precision timing for performance troubleshooting

    The formatter tracks application runtime from first instantiation,
    providing continuous timing reference across all log messages.

    Attributes:
        _start_time: High-precision start timestamp for elapsed time calculation

    Log Format Enhancement:
        Standard: [INFO] module: message
        Enhanced: [1234.5 ms] [MainThread     ] [INFO ] module: message
    """

    def __init__(self, fmt=None, datefmt=None):
        """
        Initialize enhanced formatter with timing baseline.

        Args:
            fmt: Log format string (uses standard logging format specifiers)
            datefmt: Date/time format (typically not used with elapsed timing)

        Note: Uses perf_counter() for high-resolution timing measurements
        """
        super().__init__(fmt, datefmt)
        # Capture high-precision start time for elapsed calculations
        self._start_time = time.perf_counter()

    def format(self, record):
        """
        Format log record with enhanced thread and timing information.

        Args:
            record: LogRecord instance to format

        Returns:
            Formatted log string with thread info and elapsed time

        Thread Safety: Called from multiple threads - must be thread-safe
        """
        # Calculate elapsed time with millisecond precision
        elapsed_ms = (time.perf_counter() - self._start_time) * 1000
        record.elapsed_ms = f"{elapsed_ms:10.1f}"  # Right-aligned, 10-char width

        # Add current thread identification for debugging multi-threaded issues
        record.thread_name = threading.current_thread().name  # Human-readable name
        record.thread_id = threading.current_thread().ident   # Unique system ID

        # Apply standard formatting with enhanced record attributes
        return super().format(record)


# ----- LOGGING SYSTEM SETUP -----
# Central configuration functions for application-wide logging

def setup_logging(
    level: int = logging.DEBUG,
    log_file: Optional[str] = None,
    console: bool = True
) -> logging.Logger:
    """
    Configure centralized logging system with console and file output.

    Establishes the root logger for the PCIe-7821 application with consistent
    formatting across all modules. Supports simultaneous console and file
    output with thread-aware formatting for debugging complex operations.

    Args:
        level: Minimum logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for persistent logging (auto-creates directories)
        console: Enable console output for real-time monitoring

    Returns:
        Configured root logger for the pcie7821 namespace

    Configuration Details:
        - Namespace: All loggers use "pcie7821.*" hierarchy
        - Format: [elapsed_ms] [thread_name] [level] logger_name: message
        - Encoding: UTF-8 for international character support
        - Handler Management: Clears existing handlers to prevent duplication

    Usage:
        # Basic console logging
        setup_logging(level=logging.INFO)

        # Console + file logging
        setup_logging(level=logging.DEBUG, log_file="logs/acquisition.log")

        # File-only logging
        setup_logging(level=logging.WARNING, log_file="errors.log", console=False)

    Thread Safety: Safe to call from any thread, though typically called once at startup
    """
    # Create root logger for pcie7821 namespace hierarchy
    logger = logging.getLogger("pcie7821")
    logger.setLevel(level)

    # Clear existing handlers to prevent duplicate output in reconfiguration scenarios
    logger.handlers.clear()

    # Enhanced format string with thread information and precise timing
    # Format: [elapsed_ms] [thread_name] [level] logger_name: message
    fmt_string = "[%(elapsed_ms)s ms] [%(thread_name)-15s] [%(levelname)-5s] %(name)-20s: %(message)s"
    formatter = ThreadFormatter(fmt_string)

    # ----- Console Handler Setup -----
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # ----- File Handler Setup -----
    if log_file:
        # Ensure log directory exists (create parent directories if needed)
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Configure file handler with UTF-8 encoding for international support
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Create module-specific logger within the pcie7821 namespace.

    Provides a convenient factory function for creating loggers with
    consistent naming convention across all application modules.

    Args:
        name: Module or component name (typically __name__ without package prefix)

    Returns:
        Logger instance configured for the specified module

    Naming Convention:
        - Input: "acquisition" -> Logger: "pcie7821.acquisition"
        - Input: "gui.main" -> Logger: "pcie7821.gui.main"
        - Hierarchical names supported for sub-component organization

    Usage:
        # In acquisition_thread.py
        log = get_logger("acquisition")
        log.info("Starting acquisition thread")

        # In gui/main_window.py
        log = get_logger("gui.main")
        log.debug("GUI initialized")

    Logger Hierarchy Benefits:
        - Enables level control by module (e.g., DEBUG for specific components)
        - Supports filtering by logger name in log analysis
        - Maintains consistent namespace organization
    """
    return logging.getLogger(f"pcie7821.{name}")


# ----- PERFORMANCE MEASUREMENT UTILITIES -----
# Decorators and context managers for performance profiling

def log_timing(logger: logging.Logger):
    """
    Decorator factory for automatic function execution timing.

    Creates a decorator that measures and logs function execution time
    with exception handling. Useful for identifying performance bottlenecks
    and monitoring critical function execution times.

    Args:
        logger: Logger instance to receive timing messages

    Returns:
        Decorator function for timing measurement

    Features:
        - High-precision timing using perf_counter()
        - Exception-safe timing (logs even if function fails)
        - Automatic function name identification
        - Millisecond precision timing output

    Usage:
        log = get_logger("hardware")

        @log_timing(log)
        def read_hardware_buffer():
            # Complex hardware operation
            return data

        # Automatic timing output:
        # [DEBUG] read_hardware_buffer completed in 15.23 ms
        # [ERROR] read_hardware_buffer failed after 8.45 ms: Device timeout

    Performance Impact: Minimal overhead (~1-2 microseconds per call)
    """
    def decorator(func):
        """
        Actual decorator that wraps the target function.

        Args:
            func: Function to be timed

        Returns:
            Wrapped function with timing capability
        """
        def wrapper(*args, **kwargs):
            """
            Wrapper function that measures execution time.

            Args:
                *args: Original function positional arguments
                **kwargs: Original function keyword arguments

            Returns:
                Original function return value

            Raises:
                Re-raises any exception from original function after logging timing
            """
            # Capture high-precision start time
            start = time.perf_counter()

            try:
                # Execute original function
                result = func(*args, **kwargs)

                # Calculate and log successful execution time
                elapsed = (time.perf_counter() - start) * 1000
                logger.debug(f"{func.__name__} completed in {elapsed:.2f} ms")
                return result

            except Exception as e:
                # Calculate and log failed execution time with error details
                elapsed = (time.perf_counter() - start) * 1000
                logger.error(f"{func.__name__} failed after {elapsed:.2f} ms: {e}")
                # Re-raise exception to preserve original error handling
                raise

        return wrapper
    return decorator


class PerformanceTimer:
    """
    Context manager for measuring code block execution time.

    Provides a convenient way to measure execution time of arbitrary code
    blocks using Python's 'with' statement. Automatically logs start,
    completion, and error timing information.

    Attributes:
        logger: Logger instance for timing output
        operation: Human-readable operation description
        start_time: High-precision start timestamp

    Usage:
        log = get_logger("processing")

        with PerformanceTimer(log, "FFT calculation"):
            # Complex processing code
            result = np.fft.fft(data)

        # Automatic output:
        # [DEBUG] FFT calculation - started
        # [DEBUG] FFT calculation - completed in 125.67 ms

    Exception Handling:
        Measures and logs timing even when exceptions occur within the block.
        Exceptions are not suppressed - they propagate normally after timing.
    """

    def __init__(self, logger: logging.Logger, operation: str):
        """
        Initialize performance timer for specific operation.

        Args:
            logger: Logger instance to receive timing messages
            operation: Descriptive name for the timed operation

        Note: Timer starts when entering context (__enter__), not at construction
        """
        self.logger = logger
        self.operation = operation
        self.start_time = 0  # Will be set in __enter__

    def __enter__(self):
        """
        Context manager entry - start timing and log operation start.

        Returns:
            Self reference for optional use in with statement

        Side Effects:
            - Captures high-precision start time
            - Logs operation start message at DEBUG level
        """
        # Record high-precision start timestamp
        self.start_time = time.perf_counter()

        # Log operation initiation for debugging flow control
        self.logger.debug(f"{self.operation} - started")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit - calculate timing and log results.

        Args:
            exc_type: Exception type if exception occurred (None if successful)
            exc_val: Exception value if exception occurred
            exc_tb: Exception traceback if exception occurred

        Returns:
            False to propagate exceptions normally

        Behavior:
            - Always calculates and logs elapsed time
            - Logs success or failure with timing information
            - Does not suppress exceptions (returns False)
        """
        # Calculate elapsed time with millisecond precision
        elapsed = (time.perf_counter() - self.start_time) * 1000

        if exc_type:
            # Log failed operation with exception details and timing
            self.logger.error(f"{self.operation} - failed after {elapsed:.2f} ms: {exc_val}")
        else:
            # Log successful operation completion with timing
            self.logger.debug(f"{self.operation} - completed in {elapsed:.2f} ms")

        # Return False to allow exceptions to propagate normally
        return False
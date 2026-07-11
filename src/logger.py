#!/usr/bin/env python3
"""Enhanced logging module for the Document OCR Processing Pipeline.

Provides:
- Terminal output with emojis, colors, and progress indicators
- File output with full details
- Timing context manager for tracking operation durations
- Progress tracking for batch operations
- Status line for real-time updates

Usage:
    from src.logger import setup_pipeline_logging, TimingContext, ProgressTracker
    
    # Setup logging
    setup_pipeline_logging(log_level="INFO", log_file="logs/pipeline.log")
    
    # Use timing context
    with TimingContext("Processing files"):
        do_work()
    
    # Use progress tracker
    tracker = ProgressTracker(total=100, description="Classifying")
    for i in range(100):
        tracker.update()
"""

import logging
import sys
import os
import time
from datetime import datetime
from contextlib import contextmanager
from typing import Optional


# -- ANSI Color Codes ---------------------------------------------------------

class ANSI:
    """ANSI escape codes for terminal colors."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    
    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Bright foreground colors
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_CYAN = "\033[96m"


# -- Emoji Mapping ------------------------------------------------------------

EMOJI_MAP = {
    # Log level emojis
    "DEBUG": "🔬",
    "INFO": "ℹ️",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "CRITICAL": "🔥",
    
    # Operation-specific emojis (used when message patterns match)
    "Processing:": "🔄",
    "AI classification:": "🤖",
    "Copied to:": "📦",
    "Deleted": "🗑️",
    "Found": "📄",
    "Starting": "🚀",
    "Completed": "✅",
    "Simulation": "🔍",
    "Sub-folder": "📁",
    "AI classifier": "🧠",
    "Filename": "🏷️",
    "Checksum": "🔐",
    "OCR": "📝",
    "Interrupted": "⏹️",
    "Reroute": "🔀",
    "Undo": "↩️",
}

# Color mapping for log levels
COLOR_MAP = {
    "DEBUG": ANSI.BRIGHT_CYAN,
    "INFO": ANSI.GREEN,
    "WARNING": ANSI.YELLOW,
    "ERROR": ANSI.RED,
    "CRITICAL": ANSI.BRIGHT_RED + ANSI.BOLD,
}


# -- Enhanced Stream Handler --------------------------------------------------

class EnhancedStreamHandler(logging.StreamHandler):
    """Custom StreamHandler with emojis, colors, and visual indicators.
    
    This handler provides rich terminal output with:
    - Timestamps in YYYY-MM-DD HH:MM:SS format
    - Log level with emoji indicator
    - ANSI colors based on log level
    - Logger name
    - Formatted message
    """
    
    def __init__(self, stream=None):
        """Initialize the enhanced stream handler.
        
        Args:
            stream: Output stream (defaults to sys.stdout)
        """
        super().__init__(stream)
        self.setFormatter(EnhancedFormatter())
    
    def emit(self, record):
        """Emit a log record with enhanced formatting."""
        try:
            # Get the formatted message
            msg = self.format(record)
            
            # Add color prefix
            level = record.levelname
            color = COLOR_MAP.get(level, "")
            emoji = EMOJI_MAP.get(level, "•")
            
            # Check for operation-specific emojis
            for pattern, emoji_pattern in EMOJI_MAP.items():
                if pattern != level and pattern in msg:
                    emoji = emoji_pattern
                    break
            
            # Build colored prefix
            colored_prefix = f"{color}{emoji} [{level:>5}]{ANSI.RESET}"
            
            # Write the complete line
            full_msg = f"{colored_prefix} {msg}{ANSI.RESET}{self.terminator}"
            stream = self.stream
            stream.write(full_msg)
            self.flush()
            
        except Exception:
            self.handleError(record)


# -- Enhanced Formatter -------------------------------------------------------

class EnhancedFormatter(logging.Formatter):
    """Formatter that provides enhanced message formatting."""
    
    def __init__(self, fmt=None, datefmt=None):
        """Initialize the formatter.
        
        Args:
            fmt: Format string (defaults to enhanced format)
            datefmt: Date format string (defaults to ISO-like format)
        """
        if fmt is None:
            fmt = "%(message)s"
        super().__init__(fmt=fmt, datefmt=datefmt)
    
    def format(self, record):
        """Format a log record with enhanced output."""
        # Add timestamp
        timestamp = self.formatTime(record, self.datefmt)
        
        # Get the message
        message = record.getMessage()
        
        # Add timing info if available
        if hasattr(record, 'duration'):
            message += f" ({record.duration:.3f}s)"
        
        # Build full formatted message
        return f"{timestamp} {message}"


# -- Timing Context Manager ---------------------------------------------------

class TimingContext:
    """Context manager for timing operations with automatic logging.
    
    Usage:
        logger = logging.getLogger("pipeline")
        with TimingContext(logger, "Processing files"):
            # do work
        # Logs timing info automatically
    """
    
    def __init__(self, logger, operation, level=logging.INFO):
        """Initialize timing context.
        
        Args:
            logger: Logger instance to use for output.
            operation: Name of the operation being timed.
            level: Log level for completion message.
        """
        self.logger = logger
        self.operation = operation
        self.level = level
        self.start_time = None
        self._extra = {}
        
    def __enter__(self):
        """Start timing."""
        self.start_time = time.time()
        self.logger.info("🚀 Starting: %s", self.operation)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timing and log duration."""
        end_time = time.time()
        duration = end_time - self.start_time
        
        if exc_type is None:
            self.logger.log(
                self.level,
                "✅ Completed: %s in %.3fs",
                self.operation,
                duration,
                extra={'duration': duration}
            )
        else:
            self.logger.warning(
                "⚠️  Completed with error: %s in %.3fs (%s: %s)",
                self.operation,
                duration,
                exc_type.__name__,
                exc_val,
                extra={'duration': duration}
            )
        return False
    
    @property
    def elapsed(self):
        """Get elapsed time since start."""
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time


# -- Progress Tracker ---------------------------------------------------------

class ProgressTracker:
    """Track progress of batch operations with visual indicators.
    
    Usage:
        tracker = ProgressTracker(total=100, description="Classifying")
        for item in items:
            # process item
            tracker.update()
        tracker.complete()
    """
    
    def __init__(self, total, description="Processing"):
        """Initialize progress tracker.
        
        Args:
            total: Total number of items to process.
            description: Description of the current operation.
        """
        self.total = total
        self.current = 0
        self.description = description
        self.start_time = time.time()
        self.logger = logging.getLogger("pipeline")
        
    def update(self, message=""):
        """Update progress after processing an item.
        
        Args:
            message: Optional additional message to display.
        """
        self.current += 1
        progress = (self.current / self.total) * 100
        elapsed = time.time() - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        
        # Build progress bar
        bar_width = 20
        filled = int(bar_width * self.current / self.total)
        bar = chr(9608) * filled + chr(9617) * (bar_width - filled)
        
        # Format elapsed time
        elapsed_str = self._format_time(elapsed)
        
        # Build status message
        status = f"[{bar}] {progress:5.1f}% ({self.current}/{self.total}) {elapsed_str} @ {rate:.1f}/s"
        if message:
            status += f" | {message}"
        
        self.logger.info("%s: %s", self.description, status)
    
    def complete(self, message="Done"):
        """Mark progress as complete.
        
        Args:
            message: Final message to display.
        """
        total_time = time.time() - self.start_time
        self.logger.info(
            "✅ %s: %s - Total time: %s",
            self.description,
            message,
            self._format_time(total_time)
        )
    
    def _format_time(self, seconds):
        """Format seconds into human-readable time string.
        
        Args:
            seconds: Time in seconds.
            
        Returns:
            Formatted time string (e.g., "1m 23s").
        """
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}m {secs:.0f}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"


# -- Status Line Handler ------------------------------------------------------

class StatusLineHandler(logging.Handler):
    """Handler that updates a single status line in the terminal.
    
    Useful for showing real-time progress without adding new lines.
    """
    
    def __init__(self):
        """Initialize the status line handler."""
        super().__init__()
        self._status = ""
        self._enabled = True
    
    def emit(self, record):
        """Emit a status update."""
        if self._enabled:
            msg = self.format(record).strip()
            # Move cursor to start of line, write status, add newline
            sys.stdout.write(f"\r{ANSI.BLUE}{msg}{ANSI.RESET}\n")
            sys.stdout.flush()
    
    def clear(self):
        """Clear the status line."""
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()


# -- Logging Setup ------------------------------------------------------------

def setup_pipeline_logging(
    log_level="INFO",
    log_file="logs/pipeline.log",
    enable_colors=True,
    enable_timing=True,
):
    """Set up enhanced logging for the pipeline.
    
    Configures both terminal and file handlers with:
    - Enhanced terminal output with emojis and colors
    - Detailed file logging
    - Optional timing support
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to the log file
        enable_colors: Enable ANSI color codes in terminal
        enable_timing: Enable timing context manager
        
    Returns:
        Configured logger instance
    """
    # Convert string level to logging constant
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    
    # Get root logger
    logger = logging.getLogger("pipeline")
    logger.setLevel(level)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Create formatters
    terminal_formatter = EnhancedFormatter(
        fmt="%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    file_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Create handlers
    if enable_colors:
        terminal_handler = EnhancedStreamHandler(sys.stdout)
    else:
        terminal_handler = logging.StreamHandler(sys.stdout)
        terminal_handler.setFormatter(terminal_formatter)
    
    terminal_handler.setFormatter(terminal_formatter)
    
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(file_formatter)
    
    # Add handlers
    logger.addHandler(terminal_handler)
    logger.addHandler(file_handler)
    
    # Add timing if enabled
    if enable_timing:
        logger.info("⏱️  Timing enabled - operations will show duration")
    
    return logger


def get_logger(name="pipeline"):
    """Get a logger instance.
    
    Args:
        name: Logger name (defaults to "pipeline")
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# -- Convenience Functions ----------------------------------------------------

def log_start(logger, message):
    """Log a start message and return a timing context.
    
    Args:
        logger: Logger instance
        message: Message to log
        
    Returns:
        TimingContext for the operation
    """
    return TimingContext(logger, message)


def log_success(logger, message, duration=0):
    """Log a success message.
    
    Args:
        logger: Logger instance
        message: Success message
        duration: Optional operation duration in seconds
    """
    extra = {'duration': duration} if duration > 0 else {}
    logger.info(f"✅ {message}", extra=extra)


def log_warning(logger, message):
    """Log a warning message.
    
    Args:
        logger: Logger instance
        message: Warning message
    """
    logger.warning(f"⚠️  {message}")


def log_error(logger, message):
    """Log an error message.
    
    Args:
        logger: Logger instance
        message: Error message
    """
    logger.error(f"❌ {message}")


def log_info(logger, message):
    """Log an info message.
    
    Args:
        logger: Logger instance
        message: Info message
    """
    logger.info(f"ℹ️  {message}")


# -- Module-level timing context (for use without explicit logger) ------------

@contextmanager
def timing(operation, logger_name="pipeline"):
    """Context manager for timing operations (module-level convenience).
    
    Usage:
        with timing("Processing files"):
            do_work()
    
    Args:
        operation: Name of the operation
        logger_name: Logger name
        
    Yields:
        TimingContext instance
    """
    logger = logging.getLogger(logger_name)
    ctx = TimingContext(logger, operation)
    ctx.__enter__()
    try:
        yield ctx
    finally:
        ctx.__exit__(None, None, None)


# -- Test / Demo --------------------------------------------------------------

if __name__ == "__main__":
    # Demo enhanced logging
    setup_pipeline_logging(log_level="DEBUG", log_file="logs/enhanced_demo.log")
    logger = get_logger()
    
    logger.info("Enhanced logging demo started")
    
    # Demo timing
    with timing("Demo operation"):
        time.sleep(0.5)
    
    # Demo progress
    tracker = ProgressTracker(total=5, description="Demo items")
    for i in range(5):
        time.sleep(0.2)
        tracker.update(f"Item {i+1} processed")
    tracker.complete()
    
    # Demo different log levels
    logger.debug("This is a DEBUG message")
    logger.info("This is an INFO message")
    logger.warning("This is a WARNING message")
    logger.error("This is an ERROR message")
    
    logger.info("Enhanced logging demo completed")

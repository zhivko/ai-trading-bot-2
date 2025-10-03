# Logging configuration for the trading application

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Define project paths (avoid circular import)
PROJECT_ROOT = Path(__file__).parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

class FlushingFileHandler(RotatingFileHandler):
    """A rotating file handler that flushes on every log record."""
    def __init__(self, *args, maxBytes=None, backupCount=None, **kwargs):
        if maxBytes is None:
            maxBytes = 10 * 1024 * 1024  # 10MB
        if backupCount is None:
            backupCount = 1  # Keep one backup file
        super().__init__(*args, maxBytes=maxBytes, backupCount=backupCount, **kwargs)

    def emit(self, record):
        super().emit(record)
        self.flush()

    def doRollover(self):
        """
        Do a rollover, as described in __init__().
        Override to handle permission errors on Windows when file is locked.
        """
        try:
            super().doRollover()
        except OSError as e:
            # On Windows, if another process has the file open, we can't rotate it.
            # Log a warning and continue without rotation.
            import logging
            rollover_logger = logging.getLogger('FlushingFileHandler')
            rollover_logger.warning(f"Could not rotate log file {self.baseFilename}: {e}. Continuing without rotation.")

# Configure logging
log_file_path = LOGS_DIR / 'trading_view.log'

# Create handlers
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)  # Console shows INFO and above

file_handler = FlushingFileHandler(log_file_path, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)  # File shows DEBUG and above

# Create formatters and add to handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG,  # Root logger level
    handlers=[console_handler, file_handler]
)

# Configure pybit logger to show debug messages for WebSocket connections
pybit_logger = logging.getLogger('pybit')
pybit_logger.setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

# Configure watchfiles logger separately to avoid overriding main logger
watchfiles_logger = logging.getLogger('watchfiles.main')
watchfiles_logger.setLevel(logging.WARNING)

# Disable SSE debug logging to prevent recursive logging loops
sse_logger = logging.getLogger('sse_starlette.sse')
sse_logger.setLevel(logging.WARNING)

# Configure urllib3 logger to WARNING level to reduce HTTP request debug logs
urllib3_logger = logging.getLogger('urllib3.connectionpool')
urllib3_logger.setLevel(logging.WARNING)

# Configure ccxt logger to WARNING level to reduce exchange API debug logs
ccxt_logger = logging.getLogger('ccxt')
ccxt_logger.setLevel(logging.WARNING)

# Configure bybit_price_feed logger to INFO level for file output
bybit_logger = logging.getLogger('bybit_price_feed')
bybit_logger.setLevel(logging.INFO)

# Create a specific handler for bybit_price_feed with INFO level
bybit_file_handler = FlushingFileHandler(log_file_path, encoding="utf-8")
bybit_file_handler.setLevel(logging.INFO)
bybit_file_handler.setFormatter(formatter)

# Add the handler to the bybit logger
bybit_logger.addHandler(bybit_file_handler)
bybit_logger.propagate = False  # Prevent duplicate logs

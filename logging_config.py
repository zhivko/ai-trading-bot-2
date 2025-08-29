# Logging configuration for the trading application

import logging
from pathlib import Path
from config import LOGS_DIR

class FlushingFileHandler(logging.FileHandler):
    """A file handler that flushes on every log record."""
    def emit(self, record):
        super().emit(record)
        self.flush()

# Configure logging
log_file_path = LOGS_DIR / 'trading_view.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.StreamHandler(),
        FlushingFileHandler(log_file_path, encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)

# Configure watchfiles logger separately to avoid overriding main logger
watchfiles_logger = logging.getLogger('watchfiles.main')
watchfiles_logger.setLevel(logging.WARNING)
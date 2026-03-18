"""Centralized logging config for KMS.

All modules import: from kms_logger import logger
Logs to both console and file (logs/kms.log).
"""

import os
import logging

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_BASE_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

logger = logging.getLogger("kms")
logger.setLevel(logging.INFO)

# Console handler
_console = logging.StreamHandler()
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(message)s"))

# File handler (with timestamps for cron debugging)
_file = logging.FileHandler(os.path.join(_LOG_DIR, "kms.log"), encoding="utf-8")
_file.setLevel(logging.DEBUG)
_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s"))

logger.addHandler(_console)
logger.addHandler(_file)

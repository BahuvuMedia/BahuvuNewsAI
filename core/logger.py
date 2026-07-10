"""
BahuvuNewsAI
core/logger.py

Central logging system used by every module.

Features
--------
- Console logging
- File logging
- Automatic log directory creation
- Consistent formatting
- Reusable project logger
"""

from __future__ import annotations

import logging
from logging import Logger
from pathlib import Path

# ------------------------------------------------------------------
# Log Directory
# ------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "bahuvu.log"

# ------------------------------------------------------------------
# Logger Configuration
# ------------------------------------------------------------------

_LOGGER_NAME = "BahuvuNewsAI"
_CONFIGURED = False


def get_logger() -> Logger:
    """
    Return the singleton project logger.
    """

    global _CONFIGURED

    logger = logging.getLogger(_LOGGER_NAME)

    if _CONFIGURED:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --------------------------------------------------------------
    # File Handler
    # --------------------------------------------------------------

    file_handler = logging.FileHandler(
        LOG_FILE,
        encoding="utf-8",
    )

    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # --------------------------------------------------------------
    # Console Handler
    # --------------------------------------------------------------

    console_handler = logging.StreamHandler()

    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    # --------------------------------------------------------------
    # Attach Handlers
    # --------------------------------------------------------------

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _CONFIGURED = True

    return logger


# ------------------------------------------------------------------
# Convenience Functions
# ------------------------------------------------------------------

def info(message: str) -> None:
    get_logger().info(message)


def warning(message: str) -> None:
    get_logger().warning(message)


def error(message: str) -> None:
    get_logger().error(message)


def exception(message: str) -> None:
    get_logger().exception(message)


# ------------------------------------------------------------------
# Self Test
# ------------------------------------------------------------------

if __name__ == "__main__":

    log = get_logger()

    log.info("Logger initialized successfully.")
    log.warning("Warning test.")
    log.error("Error test.")

    print(f"Log file written to: {LOG_FILE.resolve()}")
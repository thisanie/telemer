"""Shared console logging configuration for teleMER backend processes."""

from __future__ import annotations

import logging
import os
import sys


def configure_logging(service_name: str) -> logging.Logger:
    """Configure a service logger that writes process-tagged messages to stdout."""
    logger = logging.getLogger(f"telemer.{service_name}")
    logger.setLevel(os.getenv("TELEMER_LOG_LEVEL", "INFO").upper())
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s pid=%(process)d] %(message)s"
            )
        )
        logger.addHandler(handler)

    return logger

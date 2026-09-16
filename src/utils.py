"""Small helpers shared across the pipeline.

Holds directory creation and the logger. The logger writes to the console and to
the validation log at the same time, so that the log file the spec asks for is a
by-product of running the pipeline rather than something assembled afterwards.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src import config


def ensure_dir(path: Path) -> Path:
    """Create ``path`` and any missing parents, and return it.

    Args:
        path: Directory to create. Existing directories are left alone.

    Returns:
        The same path, so calls can be chained into an expression.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_logger(log_path: Path | None = None, name: str = "pipeline") -> logging.Logger:
    """Return a logger that writes to the console and to the validation log.

    Calling this twice with the same name returns the same configured logger
    rather than attaching duplicate handlers.

    Args:
        log_path: File to append log records to. Defaults to
            ``config.VALIDATION_LOG_PATH``.
        name: Logger name, so separate runs can be told apart if needed.

    Returns:
        A configured ``logging.Logger`` at INFO level.
    """
    log_path = log_path or config.VALIDATION_LOG_PATH
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    ensure_dir(log_path.parent)

    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
    logger.addHandler(console_handler)
    return logger


def log_section(logger: logging.Logger, title: str) -> None:
    """Write a titled separator to the log, to keep the log file readable.

    Args:
        logger: Logger to write to.
        title: Section heading, for example ``"FILE VALIDATION"``.
    """
    logger.info("")
    logger.info("=" * 78)
    logger.info(title.upper())
    logger.info("=" * 78)


def human_bytes(n_bytes: int) -> str:
    """Format a byte count as a short human-readable string.

    Args:
        n_bytes: Number of bytes.

    Returns:
        A string such as ``"1.5 MB"``.
    """
    size = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

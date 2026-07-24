"""Shared helpers for logging, retrying and text parsing."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import wraps
from pathlib import Path
import re
import time
from typing import Any, ParamSpec, TypeVar
import unicodedata

from loguru import logger

from config import Settings

P = ParamSpec("P")
T = TypeVar("T")


def configure_logging(settings: Settings) -> None:
    """Configure console and rotating file logging."""
    logger.remove()
    logger.add(lambda message: print(message, end=""), level="INFO")
    logger.add(settings.logs_dir / "app.log", rotation="5 MB", retention="14 days",
               level="DEBUG", encoding="utf-8", backtrace=True, diagnose=False)


def retry(attempts: int, delay: float = 1.5) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Return a decorator which retries an operation and logs failures."""
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            last_error: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return function(*args, **kwargs)
                except Exception as error:
                    last_error = error
                    logger.warning("{} failed ({}/{}): {}", function.__name__, attempt,
                                   attempts, error)
                    if attempt < attempts:
                        time.sleep(delay * attempt)
            assert last_error is not None
            raise last_error
        return wrapped
    return decorate


def parse_count(value: str | None) -> int | None:
    """Convert Instagram's textual counts such as ``1.2K`` to integers."""
    if not value:
        return None
    match = re.search(r"([\d.,]+)\s*([KMBkmb]?)", value.replace(",", ""))
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(
        match.group(2).upper(), 1)
    return int(number * multiplier)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO timestamps emitted by Instagram ``time`` elements."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def remove_emoji(text: str) -> str:
    """Remove Unicode emoji and symbol characters from text."""
    return "".join(char for char in text if unicodedata.category(char) not in {"So", "Sk"})


def find_emojis(text: str) -> list[str]:
    """Return emoji-like Unicode symbols from a comment."""
    return [char for char in text if unicodedata.category(char) == "So"]


def clean_filename(value: str) -> str:
    """Return a safe filename fragment."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)

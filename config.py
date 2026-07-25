"""Application configuration and filesystem paths."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent


def _parse_optional_datetime(value: str | None) -> datetime | None:
    """Parse an optional ISO datetime from the environment."""
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(
            f"Invalid datetime '{raw}'. Use ISO format like 2026-07-25T12:00:00+08:00"
        ) from error
    if parsed.tzinfo is None:
        # Bare local times are treated as Taiwan time.
        from zoneinfo import ZoneInfo

        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    return parsed


class Settings(BaseModel):
    """Runtime settings loaded from the environment."""

    username: str = Field(default="")
    password: str = Field(default="")
    headless: bool = Field(default=False)
    timeout_ms: int = Field(default=30_000, ge=1_000)
    max_retries: int = Field(default=3, ge=1, le=10)
    max_comments: int = Field(default=0, ge=0)
    crawl_delay_seconds: float = Field(default=3.0, ge=0.0)
    comment_before: datetime | None = Field(default=None)
    comment_after: datetime | None = Field(default=None)
    output_dir: Path = Field(default=BASE_DIR / "output")
    assets_dir: Path = Field(default=BASE_DIR / "assets")
    logs_dir: Path = Field(default=BASE_DIR / "logs")
    session_path: Path = Field(default=BASE_DIR / "session.json")
    template_dir: Path = Field(default=BASE_DIR / "templates")

    def ensure_directories(self) -> None:
        """Create writable directories used by the application."""
        for directory in (self.output_dir, self.assets_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Load settings from ``.env`` and create output directories."""
    load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")
    settings = Settings(
        username=os.getenv("IG_USERNAME", ""),
        password=os.getenv("IG_PASSWORD", ""),
        headless=os.getenv("HEADLESS", "false").lower() in {"1", "true", "yes"},
        timeout_ms=int(os.getenv("CRAWL_TIMEOUT_SECONDS", "30")) * 1_000,
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        max_comments=int(os.getenv("MAX_COMMENTS", "0")),
        crawl_delay_seconds=float(os.getenv("CRAWL_DELAY_SECONDS", "3.0")),
        comment_before=_parse_optional_datetime(os.getenv("COMMENT_BEFORE")),
        comment_after=_parse_optional_datetime(os.getenv("COMMENT_AFTER")),
    )
    settings.ensure_directories()
    return settings

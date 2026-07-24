"""Application configuration and filesystem paths."""

from __future__ import annotations

from pathlib import Path
import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseModel):
    """Runtime settings loaded from the environment."""

    username: str = Field(default="")
    password: str = Field(default="")
    headless: bool = Field(default=False)
    timeout_ms: int = Field(default=30_000, ge=1_000)
    max_retries: int = Field(default=3, ge=1, le=10)
    max_comments: int = Field(default=0, ge=0)
    crawl_delay_seconds: float = Field(default=0.35, ge=0.0)
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
    load_dotenv(BASE_DIR / ".env")
    settings = Settings(
        username=os.getenv("IG_USERNAME", ""),
        password=os.getenv("IG_PASSWORD", ""),
        headless=os.getenv("HEADLESS", "false").lower() in {"1", "true", "yes"},
        timeout_ms=int(os.getenv("CRAWL_TIMEOUT_SECONDS", "30")) * 1_000,
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        max_comments=int(os.getenv("MAX_COMMENTS", "0")),
        crawl_delay_seconds=float(os.getenv("CRAWL_DELAY_SECONDS", "0.35")),
    )
    settings.ensure_directories()
    return settings

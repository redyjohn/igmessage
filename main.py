"""Typer CLI entry point for IG Comment Analyzer."""

from __future__ import annotations

import json

import typer
from loguru import logger
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.table import Table

from analyzer import CommentAnalyzer
from charts import ChartGenerator
from config import load_settings
from crawler import InstagramCrawler
from report import ReportGenerator
from utils import configure_logging

app = typer.Typer(
    help="Analyse Instagram post comments from local CSV/Excel files.",
    no_args_is_help=True,
)
console = Console()

CRAWL_DISABLED_MESSAGE = (
    "Instagram crawling is disabled to protect accounts from lockouts. "
    "Use `analyze` / `report` on an existing output/comments.csv, "
    "or set ALLOW_IG_CRAWL=true only if you accept the risk."
)


def _setup() -> tuple[object, CommentAnalyzer]:
    """Load configuration and return settings with an analyzer instance."""
    settings = load_settings()
    configure_logging(settings)
    return settings, CommentAnalyzer(settings)


def _ensure_crawl_allowed() -> None:
    """Block Playwright Instagram crawl unless explicitly re-enabled."""
    import os

    from dotenv import load_dotenv

    from config import BASE_DIR

    load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")
    if os.getenv("ALLOW_IG_CRAWL", "").lower() not in {"1", "true", "yes"}:
        console.print(f"[red]{CRAWL_DISABLED_MESSAGE}[/red]")
        raise typer.Exit(code=1)


@app.command()
def crawl(post_url: str = typer.Argument(..., help="Instagram post or reel URL.")) -> None:
    """Crawl one Instagram post and save comments.csv/comments.xlsx."""
    _ensure_crawl_allowed()
    settings, _ = _setup()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=settings.headless)
        try:
            comments = InstagramCrawler(settings).crawl(browser, post_url)
            csv_path, xlsx_path = InstagramCrawler(settings).save_comments(comments)
            console.print(f"[green]Saved {len(comments)} comments[/green]\n{csv_path}\n{xlsx_path}")
        finally:
            browser.close()


@app.command()
def analyze() -> None:
    """Analyze the saved comments and write duplicate_comments.xlsx."""
    _, analyzer = _setup()
    result = analyzer.analyze(analyzer.load_comments())
    (analyzer.settings.output_dir / "analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    table = Table(title="Analysis summary")
    table.add_column("Metric"); table.add_column("Value")
    for key, value in dict(result["summary"]).items():
        table.add_row(key, str(value))
    console.print(table)


@app.command()
def report() -> None:
    """Create PNG charts, responsive HTML, and PDF from saved comments."""
    settings, analyzer = _setup()
    result = analyzer.analyze(analyzer.load_comments())
    charts = ChartGenerator(settings).create_all(result)
    html_path, pdf_path = ReportGenerator(settings).generate(result, charts)
    if pdf_path:
        console.print(f"[green]Generated report[/green]\n{html_path}\n{pdf_path}")
    else:
        console.print(f"[green]Generated report[/green]\n{html_path}")


@app.command("publish-docs")
def publish_docs() -> None:
    """Copy the latest HTML report into docs/ for GitHub Pages."""
    from publish_docs import publish

    target = publish()
    console.print(f"[green]Published[/green] {target}")


@app.command()
def all(post_url: str = typer.Argument(..., help="Instagram post or reel URL.")) -> None:
    """Crawl, analyze, chart, and report an Instagram post in one command."""
    _ensure_crawl_allowed()
    crawl(post_url)
    report()


if __name__ == "__main__":
    app()

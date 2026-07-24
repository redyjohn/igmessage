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

app = typer.Typer(help="Crawl and analyse Instagram post comments.", no_args_is_help=True)
console = Console()


def _setup() -> tuple[object, CommentAnalyzer]:
    """Load configuration and return settings with an analyzer instance."""
    settings = load_settings()
    configure_logging(settings)
    return settings, CommentAnalyzer(settings)


@app.command()
def crawl(post_url: str = typer.Argument(..., help="Instagram post or reel URL.")) -> None:
    """Crawl one Instagram post and save comments.csv/comments.xlsx."""
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
    console.print(f"[green]Generated report[/green]\n{html_path}\n{pdf_path}")


@app.command()
def all(post_url: str = typer.Argument(..., help="Instagram post or reel URL.")) -> None:
    """Crawl, analyze, chart, and report an Instagram post in one command."""
    crawl(post_url)
    report()


if __name__ == "__main__":
    app()

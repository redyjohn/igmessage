"""Bootstrap HTML and PDF report generation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from jinja2 import Environment, FileSystemLoader, select_autoescape
from loguru import logger
from playwright.sync_api import sync_playwright

from config import Settings


class ReportGenerator:
    """Render analysis artefacts as a responsive HTML report and PDF."""

    def __init__(self, settings: Settings) -> None:
        """Create a Jinja environment rooted at the project's templates folder."""
        self.settings = settings
        self.environment = Environment(loader=FileSystemLoader(settings.template_dir),
                                       autoescape=select_autoescape(["html", "xml"]))

    def generate(self, analysis: Mapping[str, object], charts: Mapping[str, str]) -> tuple[Path, Path | None]:
        """Write ``report.html`` and optionally print it to ``report.pdf``."""
        template = self.environment.get_template("report.html")
        html = template.render(analysis=analysis, charts=charts)
        html_path = self.settings.output_dir / "report.html"
        pdf_path = self.settings.output_dir / "report.pdf"
        html_path.write_text(html, encoding="utf-8")
        skip_pdf = os.getenv("SKIP_PDF", "false").lower() in {"1", "true", "yes"}
        if skip_pdf:
            logger.info("Generated {} (PDF skipped)", html_path)
            return html_path, None
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(html_path.as_uri(), wait_until="networkidle")
            page.pdf(path=str(pdf_path), format="A4", print_background=True,
                     margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
            browser.close()
        logger.info("Generated {} and {}", html_path, pdf_path)
        return html_path, pdf_path

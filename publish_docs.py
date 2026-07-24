"""Copy the generated HTML report and charts into docs/ for GitHub Pages."""

from __future__ import annotations

import shutil
from pathlib import Path

from config import BASE_DIR


def publish() -> Path:
    """Publish ``output/report.html`` and ``assets/*.png`` into ``docs/``."""
    report_src = BASE_DIR / "output" / "report.html"
    assets_src = BASE_DIR / "assets"
    docs_dir = BASE_DIR / "docs"
    docs_assets = docs_dir / "assets"

    if not report_src.exists():
        raise FileNotFoundError(f"Missing report: {report_src}")

    docs_dir.mkdir(parents=True, exist_ok=True)
    docs_assets.mkdir(parents=True, exist_ok=True)

    html = report_src.read_text(encoding="utf-8").replace("../assets/", "assets/")
    (docs_dir / "index.html").write_text(html, encoding="utf-8")

    for path in assets_src.glob("*.png"):
        shutil.copy2(path, docs_assets / path.name)

    return docs_dir / "index.html"


if __name__ == "__main__":
    target = publish()
    print(f"Published {target}")

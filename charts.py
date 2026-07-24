"""PNG chart and word-cloud generation."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
from wordcloud import WordCloud

from config import Settings


class ChartGenerator:
    """Create report charts in the assets directory."""

    def __init__(self, settings: Settings) -> None:
        """Store output settings and configure a neutral matplotlib style."""
        self.settings = settings
        plt.style.use("seaborn-v0_8-whitegrid")
        plt.rcParams["font.sans-serif"] = [
            "Microsoft JhengHei",
            "Arial Unicode MS",
            "Noto Sans CJK TC",
            "Noto Sans CJK JP",
            "Noto Sans CJK SC",
            "DejaVu Sans",
        ]
        plt.rcParams["axes.unicode_minus"] = False

    def create_all(self, analysis: Mapping[str, object]) -> dict[str, str]:
        """Create all required PNG files and return names usable by HTML."""
        charts = {
            "commenters": self._bar("top_commenters", analysis["top_commenters"], "Top Commenters"),
            "teams": self._bar(
                "team_votes",
                dict(list(dict(analysis.get("team_votes", {})).items())[:20]),
                "Top Supported Teams",
            ),
            "keywords": self._bar(
                "keywords",
                dict(list(dict(analysis["keywords"]).items())[:20]),
                "Top Keywords",
            ),
            "emojis": self._bar(
                "emojis",
                dict(list(dict(analysis["emojis"]).items())[:20]),
                "Top Emojis",
            ),
            "lengths": self._bar(
                "length_distribution",
                analysis["length_distribution"],
                "Comment Length Distribution",
            ),
            "daily": self._line("daily_comments", analysis["daily_counts"], "Comments by Date"),
            "wordcloud": self._wordcloud(analysis["keywords"]),
        }
        return {key: path.name for key, path in charts.items()}

    def _bar(self, filename: str, values: object, title: str) -> Path:
        """Create a horizontal bar chart from a mapping."""
        data = dict(values) if isinstance(values, Mapping) else {}
        path = self.settings.assets_dir / f"{filename}.png"
        labels, counts = list(data.keys())[::-1], list(data.values())[::-1]
        figure, axis = plt.subplots(figsize=(10, max(4, len(labels) * 0.38)))
        axis.barh(labels, counts, color="#833AB4")
        axis.set_title(title)
        figure.tight_layout()
        figure.savefig(path, dpi=160)
        plt.close(figure)
        return path

    def _line(self, filename: str, values: object, title: str) -> Path:
        """Create a time-series PNG through Plotly's image renderer."""
        data = dict(values) if isinstance(values, Mapping) else {}
        path = self.settings.assets_dir / f"{filename}.png"
        frame = pd.DataFrame({"date": list(data.keys()), "comments": list(data.values())})
        figure = px.line(frame, x="date", y="comments", markers=True, title=title,
                         labels={"date": "Date", "comments": "Comments"})
        figure.to_json()
        canvas, axis = plt.subplots(figsize=(12, 6))
        if frame.empty:
            axis.text(0.5, 0.5, "No timestamped comments", ha="center", va="center")
            axis.set_axis_off()
        else:
            axis.plot(frame["date"], frame["comments"], marker="o", color="#E1306C")
            axis.tick_params(axis="x", rotation=35)
            axis.set_ylabel("Comments")
        axis.set_title(title)
        canvas.tight_layout()
        canvas.savefig(path, dpi=160)
        plt.close(canvas)
        return path

    def _wordcloud(self, values: object) -> Path:
        """Render a word cloud, including a placeholder when no words exist."""
        data = dict(values) if isinstance(values, Mapping) else {}
        path = self.settings.assets_dir / "wordcloud.png"
        font_candidates = (
            r"C:\Windows\Fonts\msjh.ttc",
            r"C:\Windows\Fonts\msjhbd.ttc",
            r"C:\Windows\Fonts\mingliu.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJKtc-Regular.otf",
        )
        font_path = next((item for item in font_candidates if Path(item).exists()), None)
        cloud = WordCloud(
            width=1200,
            height=600,
            background_color="white",
            colormap="plasma",
            font_path=font_path,
        )
        cloud.generate_from_frequencies(data or {"No keywords": 1}).to_file(path)
        return path

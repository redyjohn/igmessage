"""Comment metrics, keyword extraction, and duplicate detection."""

from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
import re

import jieba
import pandas as pd
from loguru import logger

from config import Settings
from utils import find_emojis, remove_emoji

STOPWORDS = {
    "的", "了", "是", "我", "你", "他", "她", "它", "在", "有", "和", "也", "都", "就",
    "很", "這", "那", "一個", "我們", "你們", "謝謝", "哈哈", "哈哈哈",
}
SUPPORT_PATTERNS = (
    re.compile(r"我挺\s*([^\n!！。．.]+)", re.IGNORECASE),
    re.compile(r"I\s*support\s+([^\n!！。．.]+)", re.IGNORECASE),
)
FUZZY_DUPLICATE_LIMIT = 2_500


class CommentAnalyzer:
    """Produce structured analysis from a saved comments dataframe."""

    def __init__(self, settings: Settings) -> None:
        """Store settings used for report artefacts."""
        self.settings = settings

    def load_comments(self) -> pd.DataFrame:
        """Load the crawler's CSV export, preserving empty values as missing."""
        path = self.settings.output_dir / "comments.csv"
        if not path.exists():
            raise FileNotFoundError(f"Comments file not found: {path}. Run crawl first.")
        dataframe = pd.read_csv(path, encoding="utf-8-sig")
        dataframe["comment"] = dataframe.get("comment", pd.Series(dtype=str)).fillna("").astype(str)
        dataframe["username"] = dataframe.get("username", pd.Series(dtype=str)).fillna("Unknown").astype(str)
        dataframe["comment_time"] = pd.to_datetime(
            dataframe.get("comment_time"), errors="coerce", utc=True
        )
        return dataframe

    def analyze(self, dataframe: pd.DataFrame) -> dict[str, object]:
        """Calculate all requested metrics and persist duplicate-comment output."""
        authors = dataframe["username"].value_counts()
        lengths = dataframe["comment"].str.len()
        length_bins = pd.cut(
            lengths,
            bins=[-1, 10, 20, 50, float("inf")],
            labels=["0~10", "11~20", "21~50", "50+"],
        ).value_counts().sort_index()
        valid_times = dataframe.dropna(subset=["comment_time"]).copy()
        dates = valid_times["comment_time"].dt.date.value_counts().sort_index()
        hours = valid_times["comment_time"].dt.hour.value_counts().sort_index()
        weekdays = valid_times["comment_time"].dt.day_name().value_counts().reindex(
            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            fill_value=0,
        )
        keywords = self._keywords(dataframe["comment"])
        tags = Counter(re.findall(r"@([A-Za-z0-9._]+)", " ".join(dataframe["comment"])))
        emojis = Counter(emoji for text in dataframe["comment"] for emoji in find_emojis(text))
        team_votes = self._team_votes(dataframe)
        duplicates = self._duplicates(dataframe)
        duplicate_path = self._save_duplicates(duplicates)
        result: dict[str, object] = {
            "summary": {
                "total_comments": int(len(dataframe)),
                "unique_commenters": int(authors.size),
                "average_comment_length": round(float(lengths.mean() or 0), 2),
                "average_comments_per_user": (
                    round(float(len(dataframe) / authors.size), 2) if authors.size else 0
                ),
                "top_commenter": authors.index[0] if not authors.empty else None,
                "supported_teams": int(len(team_votes)),
                "support_comments": int(sum(team_votes.values())),
            },
            "top_commenters": authors.head(20).to_dict(),
            "keywords": dict(keywords.most_common(100)),
            "tags": dict(tags.most_common(100)),
            "emojis": dict(emojis.most_common(100)),
            "team_votes": dict(team_votes.most_common(100)),
            "length_distribution": length_bins.to_dict(),
            "daily_counts": {str(key): int(value) for key, value in dates.items()},
            "hourly_counts": {int(key): int(value) for key, value in hours.items()},
            "weekday_counts": weekdays.to_dict(),
            "duplicates": duplicates.head(200).to_dict(orient="records"),
            "duplicate_file": str(duplicate_path),
        }
        logger.info("Analysis complete for {} comments.", len(dataframe))
        return result

    def _keywords(self, comments: pd.Series) -> Counter[str]:
        """Segment text and count meaningful Chinese and Latin tokens."""
        counter: Counter[str] = Counter()
        for text in comments:
            cleaned = re.sub(r"https?://\S+|www\.\S+|@[\w.]+|\d+", " ", remove_emoji(text))
            for word in jieba.cut(cleaned):
                token = word.strip()
                if len(token) <= 1 or token.lower() in STOPWORDS:
                    continue
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{1,}", token):
                    counter[token.upper() if token.isupper() or " " not in token else token] += 1
                    continue
                if re.search(r"[\u4e00-\u9fff]", token):
                    counter[token] += 1
        return counter

    def _team_votes(self, dataframe: pd.DataFrame) -> Counter[str]:
        """Tally support phrases such as 「我挺TEAM」 / ``I support TEAM``."""
        votes: Counter[str] = Counter()
        for text in dataframe["comment"]:
            for pattern in SUPPORT_PATTERNS:
                found = False
                for team in pattern.findall(text):
                    cleaned = self._normalize_team_name(team)
                    if cleaned:
                        votes[cleaned] += 1
                        found = True
                if found:
                    break
        return votes

    def _normalize_team_name(self, team: str) -> str:
        """Normalize team labels so emoji/case variants collapse together."""
        cleaned = team.strip(" _-－—「」『』\"'（）()[]【】")
        cleaned = re.sub(r"[!！。．.]+$", "", cleaned).strip()
        cleaned = remove_emoji(cleaned)
        cleaned = re.sub(r"[\ufe0e\ufe0f\u200d\u200c\ufffd]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" _-－—")
        if not cleaned:
            return ""
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._'&+-]*", cleaned):
            return cleaned.upper()
        return cleaned

    def _duplicates(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """Find exact duplicates always, and similar pairs only on smaller sets."""
        rows: list[dict[str, object]] = []
        grouped: dict[str, list[int]] = defaultdict(list)
        for index, text in enumerate(dataframe["comment"].tolist()):
            normalized = text.strip()
            if normalized:
                grouped[normalized].append(index)

        for text, indexes in grouped.items():
            if len(indexes) < 2:
                continue
            usernames = [str(dataframe.iloc[index]["username"]) for index in indexes]
            top_users = ", ".join(
                f"{name}×{count}" for name, count in Counter(usernames).most_common(5)
            )
            rows.append(
                {
                    "comment_1": text,
                    "username_1": f"{len(indexes)} occurrences",
                    "comment_2": top_users,
                    "username_2": f"{len(set(usernames))} unique users",
                    "match_type": "exact",
                    "similarity": 1.0,
                }
            )

        if len(dataframe) <= FUZZY_DUPLICATE_LIMIT:
            comments = dataframe["comment"].tolist()
            for first in range(len(comments)):
                one = comments[first].strip()
                if not one:
                    continue
                for second in range(first + 1, len(comments)):
                    two = comments[second].strip()
                    if not two or one == two:
                        continue
                    if abs(len(one) - len(two)) > max(8, int(0.2 * max(len(one), len(two)))):
                        continue
                    score = SequenceMatcher(None, one, two).ratio()
                    if score >= 0.85:
                        rows.append(
                            {
                                "comment_1": one,
                                "username_1": dataframe.iloc[first]["username"],
                                "comment_2": two,
                                "username_2": dataframe.iloc[second]["username"],
                                "match_type": "similar",
                                "similarity": round(score, 3),
                            }
                        )
        else:
            logger.info(
                "Skipped fuzzy duplicate scan for {} comments (limit {}).",
                len(dataframe),
                FUZZY_DUPLICATE_LIMIT,
            )

        return pd.DataFrame(
            rows,
            columns=["comment_1", "username_1", "comment_2", "username_2", "match_type", "similarity"],
        )

    def _save_duplicates(self, duplicates: pd.DataFrame) -> Path:
        """Save duplicate results in an Excel workbook."""
        path = self.settings.output_dir / "duplicate_comments.xlsx"
        duplicates.to_excel(path, index=False, engine="openpyxl")
        return path

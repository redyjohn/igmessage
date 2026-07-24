"""Playwright-backed Instagram comment collection via the web comments API."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re
import time

import pandas as pd
from loguru import logger
from openpyxl.utils import get_column_letter
from playwright.sync_api import Browser, Page
from pydantic import BaseModel

from config import Settings
from login import InstagramAuthenticator
from utils import retry

IG_APP_ID = "936619743392459"
SHORTCODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


class CommentRecord(BaseModel):
    """One normalized Instagram comment."""

    username: str | None = None
    comment: str | None = None
    comment_time: datetime | None = None
    likes: int | None = None
    reply_count: int | None = None
    is_verified: bool | None = None
    profile_url: str | None = None
    comment_id: str | None = None


def shortcode_to_media_id(shortcode: str) -> str:
    """Convert an Instagram shortcode to the numeric media id."""
    media_id = 0
    for char in shortcode:
        media_id = media_id * 64 + SHORTCODE_ALPHABET.index(char)
    return str(media_id)


def extract_shortcode(post_url: str) -> str:
    """Pull the post/reel shortcode from a URL."""
    match = re.search(r"/(?:p|reel|tv)/([^/?#]+)", post_url)
    if not match:
        raise ValueError("The supplied URL is not an Instagram post or reel URL.")
    return match.group(1)


class InstagramCrawler:
    """Collect comments from an Instagram post in an authenticated browser."""

    def __init__(self, settings: Settings) -> None:
        """Create a crawler with the supplied runtime configuration."""
        self.settings = settings

    def crawl(self, browser: Browser, post_url: str) -> list[CommentRecord]:
        """Log in, resolve the media id, and page through the comments API."""
        context = browser.new_context(
            storage_state=str(self.settings.session_path)
            if self.settings.session_path.exists() else None
        )
        page = InstagramAuthenticator(self.settings).login(context)
        try:
            self._open_post(page, post_url)
            media_id = self._resolve_media_id(page, post_url)
            comments = self._fetch_comments_via_api(page, media_id)
            if not comments:
                logger.warning(
                    "No comments were returned by the comments API. "
                    "The post may have no comments or Instagram blocked the request."
                )
                self._save_debug_page(page)
            return comments
        finally:
            context.storage_state(path=str(self.settings.session_path))
            context.close()

    @retry(attempts=3)
    def _open_post(self, page: Page, post_url: str) -> None:
        """Open a supplied post URL and confirm that a post-like page loaded."""
        page.goto(post_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
        page.wait_for_timeout(1_500)
        if "/p/" not in page.url and "/reel/" not in page.url and "/tv/" not in page.url:
            raise ValueError("The supplied URL is not an Instagram post or reel URL.")

    def _resolve_media_id(self, page: Page, post_url: str) -> str:
        """Resolve the numeric media id from page JSON or the URL shortcode."""
        shortcode = extract_shortcode(post_url)
        from_page = page.evaluate(
            """(code) => {
              const html = document.documentElement.innerHTML;
              const patterns = [
                new RegExp('"code":"' + code + '".{0,120}"pk":"(\\d+)"'),
                new RegExp('"pk":"(\\d+)".{0,120}"code":"' + code + '"'),
                /"media_id":"(\\d+)"/,
              ];
              for (const pattern of patterns) {
                const match = html.match(pattern);
                if (match) return match[1];
              }
              return null;
            }""",
            shortcode,
        )
        media_id = from_page or shortcode_to_media_id(shortcode)
        logger.info("Resolved media id {} for shortcode {}.", media_id, shortcode)
        return str(media_id)

    def _fetch_comments_via_api(self, page: Page, media_id: str) -> list[CommentRecord]:
        """Page through Instagram's web comments endpoint until exhausted or capped."""
        state_path = self.settings.output_dir / "crawl_state.json"
        collected = self._load_existing_comments()
        min_id = self._load_resume_min_id(state_path, media_id)
        page_index = 0
        empty_rounds = 0
        fail_rounds = 0
        reported_total: int | None = None
        max_comments = self.settings.max_comments
        if collected:
            logger.info("Resuming with {} comments already collected.", len(collected))

        while True:
            payload = self._request_comments_page_with_retry(page, media_id, min_id)
            if payload.get("status") == "fail" or payload.get("error"):
                fail_rounds += 1
                logger.error("Comments API error ({}/5): {}", fail_rounds, payload)
                if fail_rounds >= 5:
                    break
                time.sleep(min(30.0, 2.0 * fail_rounds))
                try:
                    page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
                    page.wait_for_timeout(1_500)
                except Exception as error:
                    logger.warning("Page reload after API failure did not succeed: {}", error)
                continue
            fail_rounds = 0

            if reported_total is None and payload.get("comment_count") is not None:
                reported_total = int(payload["comment_count"])
                logger.info("Instagram reports {} comments on this media.", reported_total)

            batch = payload.get("comments") or []
            added = 0
            for item in batch:
                record = self._api_comment_to_record(item)
                if record.comment_id and record.comment_id not in collected:
                    collected[record.comment_id] = record
                    added += 1

            page_index += 1
            logger.info(
                "Comments page {}: +{} new (unique total {}).",
                page_index, added, len(collected),
            )

            if max_comments and len(collected) >= max_comments:
                logger.info("Reached MAX_COMMENTS={}.", max_comments)
                break

            if not batch:
                empty_rounds += 1
                if empty_rounds >= 5:
                    logger.warning("Stopping after repeated empty comment pages.")
                    break
            else:
                empty_rounds = 0

            next_min_id = payload.get("next_min_id")
            has_more = bool(payload.get("has_more_headload_comments")) and bool(next_min_id)
            if not has_more:
                if state_path.exists():
                    state_path.unlink()
                break

            min_id = str(next_min_id)
            self._save_crawl_state(state_path, media_id, min_id, len(collected))
            time.sleep(self.settings.crawl_delay_seconds)

            if page_index % 25 == 0:
                self._checkpoint(list(collected.values()))

        records = list(collected.values())
        if max_comments:
            records = records[:max_comments]
        logger.info("Fetched {} unique comments via API.", len(records))
        return records

    def _load_existing_comments(self) -> dict[str, CommentRecord]:
        """Load previously saved comments so a crawl can resume without duplicates."""
        collected: dict[str, CommentRecord] = {}
        for path in (
            self.settings.output_dir / "comments.partial.csv",
            self.settings.output_dir / "comments.csv",
        ):
            if not path.exists():
                continue
            try:
                dataframe = pd.read_csv(path, encoding="utf-8-sig")
            except Exception as error:
                logger.warning("Could not read {}: {}", path, error)
                continue
            for row in dataframe.to_dict(orient="records"):
                comment_id = str(row.get("comment_id") or "")
                if not comment_id or comment_id == "nan" or comment_id in collected:
                    continue

                def _clean(value: object) -> object:
                    if value is None or (isinstance(value, float) and pd.isna(value)):
                        return None
                    if isinstance(value, str) and value.lower() == "nan":
                        return None
                    return value

                comment_time = _clean(row.get("comment_time"))
                parsed_time = None
                if isinstance(comment_time, str) and comment_time.strip():
                    try:
                        parsed_time = datetime.fromisoformat(
                            comment_time.replace("Z", "+00:00")
                        )
                    except ValueError:
                        parsed_time = None
                username = _clean(row.get("username"))
                comment = _clean(row.get("comment"))
                collected[comment_id] = CommentRecord(
                    username=str(username) if username is not None else None,
                    comment=str(comment) if comment is not None else None,
                    comment_time=parsed_time,
                    likes=_clean(row.get("likes")),
                    reply_count=_clean(row.get("reply_count")),
                    is_verified=(
                        bool(row.get("is_verified"))
                        if _clean(row.get("is_verified")) is not None else None
                    ),
                    profile_url=(
                        str(row.get("profile_url"))
                        if _clean(row.get("profile_url")) is not None else None
                    ),
                    comment_id=comment_id,
                )
            if collected:
                logger.info("Loaded {} comments from {}.", len(collected), path.name)
                break
        return collected

    def _load_resume_min_id(self, state_path: Path, media_id: str) -> str | None:
        """Return the saved pagination cursor when it matches the current media."""
        if not state_path.exists():
            return None
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if str(state.get("media_id")) != str(media_id):
            return None
        min_id = state.get("next_min_id")
        return str(min_id) if min_id else None

    def _save_crawl_state(
        self, state_path: Path, media_id: str, min_id: str, count: int
    ) -> None:
        """Persist pagination cursor for crash-safe resumes."""
        state_path.write_text(
            json.dumps(
                {"media_id": media_id, "next_min_id": min_id, "count": count},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _request_comments_page_with_retry(
        self, page: Page, media_id: str, min_id: str | None
    ) -> dict[str, Any]:
        """Fetch one comments page, retrying transient browser/network failures."""
        last_payload: dict[str, Any] = {"status": "fail", "error": "no attempt"}
        for attempt in range(1, 4):
            payload = self._request_comments_page(page, media_id, min_id)
            last_payload = payload
            if payload.get("http_status") == 200 and "comments" in payload:
                return payload
            if payload.get("status") != "fail" and not payload.get("error"):
                return payload
            logger.warning(
                "Comments page request failed ({}/3): {}", attempt, payload.get("error")
            )
            time.sleep(1.5 * attempt)
        return last_payload

    def _request_comments_page(
        self, page: Page, media_id: str, min_id: str | None
    ) -> dict[str, Any]:
        """Fetch one comments page using the authenticated browser session."""
        return page.evaluate(
            """async ({ mediaId, minId, appId }) => {
              let url = `https://www.instagram.com/api/v1/media/${mediaId}/comments/`
                + `?can_support_threading=true&permalink_enabled=false`;
              if (minId) url += `&min_id=${encodeURIComponent(minId)}`;
              try {
                const response = await fetch(url, {
                  credentials: 'include',
                  headers: {
                    'X-IG-App-ID': appId,
                    'X-Requested-With': 'XMLHttpRequest',
                  },
                });
                const data = await response.json();
                data.http_status = response.status;
                return data;
              } catch (error) {
                return { error: String(error), status: 'fail' };
              }
            }""",
            {"mediaId": media_id, "minId": min_id, "appId": IG_APP_ID},
        )

    def _api_comment_to_record(self, item: dict[str, Any]) -> CommentRecord:
        """Normalize one comments-API payload into a CommentRecord."""
        user = item.get("user") or {}
        username = user.get("username")
        created = item.get("created_at") or item.get("created_at_utc")
        comment_time = (
            datetime.fromtimestamp(int(created), tz=timezone.utc) if created else None
        )
        comment_id = str(item.get("pk") or item.get("strong_id__") or "")
        return CommentRecord(
            username=username,
            comment=(item.get("text") or "").strip() or None,
            comment_time=comment_time,
            likes=item.get("comment_like_count"),
            reply_count=item.get("child_comment_count") or 0,
            is_verified=bool(user.get("is_verified")),
            profile_url=f"https://www.instagram.com/{username}/" if username else None,
            comment_id=comment_id or None,
        )

    def _checkpoint(self, comments: list[CommentRecord]) -> None:
        """Persist a partial CSV so long crawls are not lost on failure."""
        path = self.settings.output_dir / "comments.partial.csv"
        dataframe = pd.DataFrame(
            [item.model_dump(mode="json") for item in comments],
            columns=list(CommentRecord.model_fields),
        )
        dataframe.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info("Checkpointed {} comments to {}.", len(comments), path)

    def _save_debug_page(self, page: Page) -> None:
        """Save the rendered page for diagnosis when no comments are found."""
        screenshot_path = self.settings.logs_dir / "post_no_comments.png"
        html_path = self.settings.logs_dir / "post_no_comments.html"
        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")
        logger.info("Saved diagnostic files: {} and {}", screenshot_path, html_path)

    def save_comments(self, comments: list[CommentRecord]) -> tuple[Path, Path]:
        """Write comments as UTF-8 CSV and auto-sized XLSX files."""
        columns = list(CommentRecord.model_fields)
        dataframe = pd.DataFrame(
            [item.model_dump(mode="json") for item in comments], columns=columns
        )
        csv_path = self.settings.output_dir / "comments.csv"
        xlsx_path = self.settings.output_dir / "comments.xlsx"
        dataframe.to_csv(csv_path, index=False, encoding="utf-8-sig")
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            dataframe.to_excel(writer, index=False, sheet_name="Comments")
            worksheet = writer.book["Comments"]
            for index, column in enumerate(worksheet.columns, start=1):
                width = min(max(len(str(cell.value or "")) for cell in column) + 2, 60)
                worksheet.column_dimensions[get_column_letter(index)].width = width
        partial = self.settings.output_dir / "comments.partial.csv"
        if partial.exists():
            partial.unlink()
        logger.info("Saved {} and {}", csv_path, xlsx_path)
        return csv_path, xlsx_path

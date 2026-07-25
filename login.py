"""Instagram authentication and saved browser session handling."""

from __future__ import annotations

import time

from loguru import logger
from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeoutError

from config import Settings


class InstagramLoginError(RuntimeError):
    """Raised when Instagram authentication cannot be completed."""


class InstagramAuthenticator:
    """Authenticate an Instagram browser context using reusable storage state."""

    def __init__(self, settings: Settings) -> None:
        """Store application settings."""
        self.settings = settings

    def login(self, context: BrowserContext) -> Page:
        """Return an authenticated page, restoring or creating a session."""
        page = context.new_page()
        page.set_default_timeout(self.settings.timeout_ms)
        if (
            self.settings.session_path.exists()
            and self._storage_has_session_cookie()
            and self._session_is_valid(page)
        ):
            logger.info("Using saved Instagram session.")
            return page
        if not self.settings.username or not self.settings.password:
            raise InstagramLoginError("Missing IG_USERNAME or IG_PASSWORD in .env")
        if self.settings.session_path.exists():
            logger.warning("Saved session is invalid or incomplete; logging in again.")
        self._perform_login(page)
        if not self._page_has_session_cookie(context):
            raise InstagramLoginError(
                "Login finished without a sessionid cookie. Complete any Instagram "
                "challenge in the browser, then try again."
            )
        context.storage_state(path=str(self.settings.session_path))
        logger.info("Instagram session saved to {}", self.settings.session_path)
        return page

    def _storage_has_session_cookie(self) -> bool:
        """Return True when session.json contains a non-empty sessionid cookie."""
        try:
            import json

            payload = json.loads(self.settings.session_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        for cookie in payload.get("cookies") or []:
            if cookie.get("name") == "sessionid" and cookie.get("value"):
                return True
        return False

    def _page_has_session_cookie(self, context: BrowserContext) -> bool:
        """Return True when the browser context has a sessionid cookie."""
        for cookie in context.cookies("https://www.instagram.com"):
            if cookie.get("name") == "sessionid" and cookie.get("value"):
                return True
        return False

    def _session_is_valid(self, page: Page) -> bool:
        """Check whether restored cookies still provide a signed-in session."""
        try:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            page.wait_for_timeout(1_500)
            if "/accounts/login" in page.url:
                return False
            # Logged-out pages still contain /accounts/login links; require home nav.
            logged_in_markers = (
                'svg[aria-label="Home"]',
                'svg[aria-label="首頁"]',
                'a[href="/direct/inbox/"]',
                'span:has-text("搜尋")',
            )
            for selector in logged_in_markers:
                locator = page.locator(selector)
                if locator.count():
                    return True
            return False
        except PlaywrightTimeoutError:
            return False

    def _perform_login(self, page: Page) -> None:
        """Submit credentials and wait for an interactive verification if needed."""
        try:
            page.goto(
                "https://www.instagram.com/accounts/login/",
                wait_until="domcontentloaded",
            )
            page.wait_for_timeout(2_000)
            self._accept_cookies(page)
            username = self._find_username_input(page)
            password = self._find_password_input(page)
            username.click()
            username.fill(self.settings.username)
            password.click()
            password.fill(self.settings.password)
            page.wait_for_timeout(500)
            login_button = page.locator('button[type="submit"], input[type="submit"]')
            if not (login_button.count() and login_button.first.is_visible()):
                login_button = page.get_by_role("button", name="Log in")
            if not login_button.count():
                login_button = page.get_by_role("button", name="\u767b\u5165")
            if login_button.count() and login_button.first.is_enabled():
                login_button.first.click()
            else:
                password.press("Enter")
            self._wait_for_login(page)
        except PlaywrightTimeoutError as error:
            screenshot = self.settings.logs_dir / "login_failure.png"
            page.screenshot(path=str(screenshot), full_page=True)
            raise InstagramLoginError(
                f"Instagram login form did not become available. Current URL: {page.url}. "
                f"Check network access; a diagnostic screenshot was saved to {screenshot}."
            ) from error
        if "/accounts/login" in page.url:
            message = self._visible_error(page)
            raise InstagramLoginError(message or "Instagram rejected the login credentials.")

    def _find_username_input(self, page: Page) -> Locator:
        """Locate the username / phone / email field on the login form."""
        selectors = (
            'input[name="email"]',
            'input[name="username"]',
            'input[autocomplete*="username"]',
            'input[type="text"]',
            'input[aria-label*="Phone number"]',
            'input[aria-label*="username"]',
            'input[aria-label*="email"]',
            'input[placeholder*="Phone"]',
            'input[placeholder*="username"]',
            'input[placeholder*="email"]',
        )
        return self._wait_for_visible(page, selectors)

    def _find_password_input(self, page: Page) -> Locator:
        """Locate the password field on the login form."""
        selectors = (
            'input[name="pass"]',
            'input[name="password"]',
            'input[autocomplete*="current-password"]',
            'input[type="password"]',
            'input[aria-label*="Password"]',
            'input[placeholder*="Password"]',
        )
        return self._wait_for_visible(page, selectors)

    def _accept_cookies(self, page: Page) -> None:
        """Dismiss Instagram's optional cookie notice when it is displayed."""
        for label in (
            "Allow all cookies",
            "Accept all",
            "Accept All",
            "接受所有 Cookie",
            "允許所有 Cookie",
        ):
            button = page.get_by_role("button", name=label, exact=False)
            if button.count() and button.first.is_visible():
                button.first.click()
                return

    def _wait_for_visible(self, page: Page, selectors: tuple[str, ...]) -> Locator:
        """Return the first visible locator from alternatives before login timeout."""
        deadline = time.monotonic() + self.settings.timeout_ms / 1_000
        while time.monotonic() < deadline:
            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if locator.count() and locator.is_visible():
                        return locator
                except Exception:
                    continue
            page.wait_for_timeout(300)
        joined = ", ".join(selectors)
        raise PlaywrightTimeoutError(f"No visible login control found: {joined}")

    def _wait_for_login(self, page: Page) -> None:
        """Wait up to three minutes for login or user-completed security verification."""
        deadline = time.monotonic() + max(self.settings.timeout_ms / 1_000, 180)
        challenge_logged = False
        while time.monotonic() < deadline:
            url = page.url
            cookies = page.context.cookies("https://www.instagram.com")
            has_session = any(
                cookie.get("name") == "sessionid" and cookie.get("value")
                for cookie in cookies
            )
            if has_session and "/accounts/login" not in url and "challenge" not in url:
                page.wait_for_timeout(1_500)
                self._dismiss_post_login_prompts(page)
                return
            if "challenge" in url and not challenge_logged:
                logger.warning(
                    "Instagram security verification detected. "
                    "Complete it in the open browser within three minutes."
                )
                challenge_logged = True
            error = self._visible_error(page)
            if error:
                raise InstagramLoginError(error)
            page.wait_for_timeout(1_000)
        raise InstagramLoginError(
            "Login verification did not complete within three minutes. Set HEADLESS=false, "
            "complete the Instagram verification in the browser, then try again."
        )

    def _dismiss_post_login_prompts(self, page: Page) -> None:
        """Dismiss optional notification prompts that can cover the logged-in page."""
        for label in ("Not now", "Not Now", "稍後再說", "現在不要"):
            prompt = page.get_by_text(label, exact=True)
            if prompt.count() and prompt.first.is_visible():
                prompt.first.click()
                return

    def _visible_error(self, page: Page) -> str | None:
        """Return Instagram's visible login error text, if one is present."""
        selectors = ('div[role="alert"]', "#slfErrorAlert", "form p")
        for selector in selectors:
            locator = page.locator(selector)
            for index in range(locator.count()):
                item = locator.nth(index)
                if item.is_visible():
                    text = item.inner_text().strip()
                    lowered = text.lower()
                    if text and (
                        "incorrect" in lowered
                        or "password" in lowered
                        or "sorry" in lowered
                        or "嘗試" in text
                        or "密碼" in text
                        or "登入" in text
                    ):
                        return text
        return None

"""Instagram authentication and saved browser session handling."""

from __future__ import annotations

import time

from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeoutError
from loguru import logger

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
        if self.settings.session_path.exists() and self._session_is_valid(page):
            logger.info("Using saved Instagram session.")
            return page
        if not self.settings.username or not self.settings.password:
            raise InstagramLoginError("Missing IG_USERNAME or IG_PASSWORD in .env")
        self._perform_login(page)
        context.storage_state(path=str(self.settings.session_path))
        logger.info("Instagram session saved to {}", self.settings.session_path)
        return page

    def _session_is_valid(self, page: Page) -> bool:
        """Check whether restored cookies still provide a signed-in session."""
        try:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            page.wait_for_timeout(1_500)
            return "/accounts/login" not in page.url and page.locator(
                'a[href^="/accounts/"]').count() > 0
        except PlaywrightTimeoutError:
            return False

    def _perform_login(self, page: Page) -> None:
        """Submit credentials and wait for an interactive verification if needed."""
        try:
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
            self._accept_cookies(page)
            username = self._wait_for_visible(page, (
                'input[name="username"]', 'input[autocomplete="username"]',
                'input[aria-label*="Phone number"]', 'input[aria-label*="電話"]',
                'input[placeholder*="手機"]', 'input[placeholder*="用戶"]',
                'input:not([type="password"])',
            ))
            password = self._wait_for_visible(page, (
                'input[name="password"]', 'input[autocomplete="current-password"]',
                'input[type="password"]', 'input[placeholder*="密碼"]',
                'input[aria-label*="密碼"]', ':nth-match([role="textbox"], 2)',
            ))
            username.fill(self.settings.username)
            password.fill(self.settings.password)
            page.wait_for_timeout(500)
            if "/accounts/login" in page.url:
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

    def _accept_cookies(self, page: Page) -> None:
        """Dismiss Instagram's optional cookie notice when it is displayed."""
        for label in ("Allow all cookies", "Accept all", "接受所有 Cookie", "允許所有 Cookie"):
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
                if locator.count() and locator.is_visible():
                    return locator
            page.wait_for_timeout(300)
        joined = ", ".join(selectors)
        raise PlaywrightTimeoutError(f"No visible login control found: {joined}")

    def _wait_for_login(self, page: Page) -> None:
        """Wait up to three minutes for login or user-completed security verification."""
        deadline = time.monotonic() + max(self.settings.timeout_ms / 1_000, 180)
        challenge_logged = False
        while time.monotonic() < deadline:
            url = page.url
            if "/accounts/login" not in url and "challenge" not in url:
                page.wait_for_timeout(1_500)
                self._dismiss_post_login_prompts(page)
                return
            if "challenge" in url and not challenge_logged:
                logger.warning("Instagram security verification detected. Complete it in the open browser within three minutes.")
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
        for label in ("Not now", "稍後再說", "現在不要"):
            prompt = page.get_by_text(label, exact=True)
            if prompt.count() and prompt.first.is_visible():
                prompt.first.click()
                return

    def _visible_error(self, page: Page) -> str | None:
        """Return Instagram's visible login error text, if one is present."""
        selectors = ('div[role="alert"]', '#slfErrorAlert', 'form p')
        for selector in selectors:
            locator = page.locator(selector)
            for index in range(locator.count()):
                item = locator.nth(index)
                if item.is_visible():
                    text = item.inner_text().strip()
                    if text and ("incorrect" in text.lower() or "password" in text.lower()
                                 or "嘗試" in text or "登入" in text):
                        return text
        return None

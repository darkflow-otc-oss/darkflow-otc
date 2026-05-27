"""
DARKFLOW OTC — Quotex Browser Manager
Controla o navegador via Playwright.
Responsabilidade: abrir, autenticar e manter sessão ativa na Quotex.
Suporta persistência de cookies para reutilizar sessão.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, UTC
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from config.settings import settings

logger = logging.getLogger("darkflow.capture.browser")

QUOTEX_URL = settings.quotex_url
QUOTEX_EMAIL = settings.quotex_email
QUOTEX_PASSWORD = settings.quotex_password
HEADLESS = settings.capture_headless
TIMEOUT = settings.capture_timeout

SCREENSHOTS_DIR = Path("logs/sessions/screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

COOKIES_DIR = Path("data/session")
COOKIES_DIR.mkdir(parents=True, exist_ok=True)
COOKIES_FILE = COOKIES_DIR / "cookies.json"

MAX_COOKIE_AGE_HOURS = 24


class QuotexBrowser:
    """
    Gerencia o ciclo de vida do navegador Playwright para a Quotex.
    Persiste cookies para reutilizar sessão e evitar login repetido.
    """

    def __init__(self):
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.is_logged_in = False
        self.session_start: datetime | None = None

    # ── Start ────────────────────────────────────────────────────────────────
    async def start(self):
        """Inicia o Playwright e abre o browser."""
        logger.info("🚀 Starting Playwright browser...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )

        # Tenta restaurar cookies salvos
        restored = await self._load_cookies()
        if restored:
            logger.info("🍪 Cookies restored — attempting session reuse...")
            self.page = await self.context.new_page()
            self.session_start = datetime.now(UTC)
            valid = await self._validate_session()
            if valid:
                self.is_logged_in = True
                logger.info("✅ Session restored from cookies — skipping login.")
                return
            else:
                logger.info("⚠️  Session expired — will perform fresh login.")
                await self.page.close()
                self.page = None

        # Fresh page
        self.page = await self.context.new_page()
        self.session_start = datetime.now(UTC)
        logger.info("✅ Browser started.")

    # ── Navigate ─────────────────────────────────────────────────────────────
    async def navigate(self, url: str = QUOTEX_URL):
        """Navega para a URL."""
        logger.info(f"🌐 Navigating to: {url}")
        await self.page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
        await self.screenshot("navigate")
        logger.info(f"✅ Page loaded: {self.page.url}")

    # ── Login ────────────────────────────────────────────────────────────────
    async def login(self):
        """Realiza login na Quotex. Pula se já autenticado."""
        if self.is_logged_in:
            logger.info("🔑 Already authenticated — skipping login.")
            return True

        if not QUOTEX_EMAIL or not QUOTEX_PASSWORD:
            logger.warning("⚠️  Credentials not set in .env — skipping login.")
            return False

        logger.info("🔑 Attempting login...")
        try:
            await self.navigate(f"{QUOTEX_URL}/en/sign-in")
            await self.page.wait_for_selector("input[type='email']", timeout=TIMEOUT)
            await self.page.fill("input[type='email']", QUOTEX_EMAIL)
            await self.page.fill("input[type='password']", QUOTEX_PASSWORD)
            await self.screenshot("before_login")
            await self.page.click("button[type='submit']")
            await self.page.wait_for_load_state("networkidle", timeout=TIMEOUT)
            await self.screenshot("after_login")

            self.is_logged_in = True
            await self._save_cookies()
            logger.info("✅ Login successful — cookies saved.")
            return True
        except Exception as e:
            logger.error(f"❌ Login failed: {e}")
            await self.screenshot("login_error")
            return False

    # ── Trade Screen ─────────────────────────────────────────────────────────
    async def go_to_trade(self):
        """Navega para a tela de trading."""
        logger.info("📊 Navigating to trade screen...")
        await self.navigate(f"{QUOTEX_URL}/en/trade")
        await asyncio.sleep(3)
        await self.screenshot("trade_screen")
        logger.info("✅ Trade screen loaded.")

    # ── Screenshot ───────────────────────────────────────────────────────────
    async def screenshot(self, label: str = "capture"):
        """Salva screenshot para observabilidade."""
        try:
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            path = SCREENSHOTS_DIR / f"{label}_{ts}.png"
            await self.page.screenshot(path=str(path), full_page=False)
            logger.debug(f"📸 Screenshot: {path}")
        except Exception as e:
            logger.warning(f"⚠️  Screenshot failed: {e}")

    # ── Cookie Persistence ───────────────────────────────────────────────────
    async def _save_cookies(self):
        """Salva cookies do contexto em disco."""
        try:
            cookies = await self.context.cookies()
            payload = {
                "saved_at": datetime.now(UTC).isoformat(),
                "cookies": cookies,
            }
            COOKIES_FILE.write_text(json.dumps(payload, indent=2))
            logger.info(f"🍪 Cookies saved: {len(cookies)} entries → {COOKIES_FILE}")
        except Exception as e:
            logger.warning(f"⚠️  Could not save cookies: {e}")

    async def _load_cookies(self) -> bool:
        """Restaura cookies do disco para o contexto. Retorna True se conseguiu."""
        if not COOKIES_FILE.exists():
            logger.info("🍪 No cookies file found.")
            return False

        try:
            payload = json.loads(COOKIES_FILE.read_text())
            cookies = payload.get("cookies", [])
            saved_at_str = payload.get("saved_at", "")

            if not cookies:
                return False

            # Verifica idade máxima dos cookies
            if saved_at_str:
                saved_at = datetime.fromisoformat(saved_at_str)
                age = datetime.now(UTC) - saved_at
                if age > timedelta(hours=MAX_COOKIE_AGE_HOURS):
                    logger.info(f"🍪 Cookies too old ({age.total_seconds()/3600:.1f}h) — will re-login.")
                    return False

            await self.context.add_cookies(cookies)
            logger.info(f"🍪 Cookies loaded: {len(cookies)} entries (age: {saved_at_str})")
            return True
        except Exception as e:
            logger.warning(f"⚠️  Could not load cookies: {e}")
            return False

    async def _validate_session(self) -> bool:
        """Verifica se a sessão restaurada ainda é válida."""
        try:
            await self.navigate(f"{QUOTEX_URL}/en/trade")
            await asyncio.sleep(2)
            url = self.page.url.lower()
            if "sign-in" in url or "login" in url:
                logger.info("🔍 Session validation: REDIRECTED TO LOGIN — expired.")
                return False
            logger.info("🔍 Session validation: VALID.")
            return True
        except Exception as e:
            logger.warning(f"⚠️  Session validation failed: {e}")
            return False

    # ── Close ────────────────────────────────────────────────────────────────
    async def close(self):
        """Fecha browser e libera recursos."""
        logger.info("🛑 Closing browser...")
        if self.is_logged_in:
            await self._save_cookies()
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("✅ Browser closed.")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()


# ── Quick test ─────────────────────────────────────────────────────────────────
async def _test():
    async with QuotexBrowser() as browser:
        await browser.navigate()
        await browser.login()
        await browser.go_to_trade()
        logger.info(f"Session started at: {browser.session_start}")
        await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_test())

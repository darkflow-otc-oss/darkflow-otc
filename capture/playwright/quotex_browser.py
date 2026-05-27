"""
DARKFLOW OTC — Quotex Browser Manager
Controla o navegador via Playwright.
Responsabilidade: abrir, autenticar e manter sessão ativa na Quotex.
Suporta persistência de cookies para reutilizar sessão.
"""

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, UTC
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth
from config.settings import settings

logger = logging.getLogger("darkflow.capture.browser")

QUOTEX_URL = settings.quotex_url
QUOTEX_EMAIL = settings.quotex_email
QUOTEX_PASSWORD = settings.quotex_password
HEADLESS = settings.capture_headless
TIMEOUT = settings.capture_timeout

# ── Proxy Residencial (iProyal BR) ──────────────────────────────────────────
PROXY_SERVER = "http://geo.iproyal.com:12321"
PROXY_USERNAME = "j3LUJ4ZiEaDJFBw2"
PROXY_PASSWORD = "SSeAXAcMPb7sfPv6_country-br_city-saopaulo_session-iqjDNG8n_lifetime-168h"

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
        self._xvfb_proc = None
        self._use_proxy = True  # Será desligado se proxy falhar

    # ── Start ────────────────────────────────────────────────────────────────
    async def start(self):
        """Inicia o Playwright e abre o browser."""
        logger.info("🚀 Starting Playwright browser...")

        # Inicia Xvfb (display virtual) se não estiver rodando
        self._xvfb_proc = None
        if "DISPLAY" not in os.environ:
            try:
                self._xvfb_proc = subprocess.Popen(
                    ["Xvfb", ":99", "-screen", "0", "1366x768x24", "-ac"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                os.environ["DISPLAY"] = ":99"
                logger.info("🖥  Xvfb started on :99")
            except FileNotFoundError:
                logger.warning("⚠️  Xvfb not found — falling back to headless.")

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-gpu",
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
            proxy={
                "server": PROXY_SERVER,
                "username": PROXY_USERNAME,
                "password": PROXY_PASSWORD,
            } if self._use_proxy else None,
        )

        # Tenta restaurar cookies salvos
        restored = await self._load_cookies()
        if restored:
            logger.info("🍪 Cookies restored — attempting session reuse...")
            self.page = await self.context.new_page()
            await Stealth().apply_stealth_async(self.page)
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
        await Stealth().apply_stealth_async(self.page)
        self.session_start = datetime.now(UTC)
        logger.info("✅ Browser started.")

    # ── Navigate ─────────────────────────────────────────────────────────────
    async def navigate(self, url: str = QUOTEX_URL):
        """Navega para a URL com bypass de Cloudflare Turnstile."""
        logger.info(f"🌐 Navigating to: {url}")
        await self.page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
        await self._wait_for_cloudflare(timeout=45)
        logger.info(f"✅ Page loaded: {self.page.url}")

    async def _wait_for_cloudflare(self, timeout: int = 20):
        """Espera o Cloudflare Turnstile resolver, se presente."""
        try:
            title = await self.page.title()
            if "just a moment" in title.lower():
                logger.info("⏳ Cloudflare challenge detected — waiting...")
                for i in range(timeout):
                    await asyncio.sleep(1)
                    title = await self.page.title()
                    if "just a moment" not in title.lower():
                        logger.info(f"✅ Cloudflare bypassed after {i+1}s.")
                        await asyncio.sleep(2)
                        return
                logger.warning("⚠️  Cloudflare timeout — reloading page...")
                await self.page.reload(wait_until="networkidle")
                await asyncio.sleep(3)
                title = await self.page.title()
                if "just a moment" in title.lower():
                    logger.error("❌ Cloudflare persists after reload — page blocked.")
            else:
                logger.debug("✅ No Cloudflare challenge detected.")
            await self.screenshot("navigate")
        except Exception as e:
            logger.debug(f"Cloudflare check: {e}")

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
            await asyncio.sleep(3)
            email_input = self.page.locator("input[name='email']").first
            await email_input.wait_for(state="attached", timeout=TIMEOUT)
            await email_input.fill(QUOTEX_EMAIL, force=True)
            await self.page.locator("input[name='password']").first.fill(QUOTEX_PASSWORD, force=True)
            await self.screenshot("before_login")
            await self.page.locator("button:has-text('Sign in')").click()
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
            title = await self.page.title()
            if "just a moment" in title.lower():
                logger.info("🔍 Session validation: CLOUDFLARE BLOCK — session invalid.")
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
        if self._xvfb_proc:
            self._xvfb_proc.terminate()
            self._xvfb_proc.wait()
            self._xvfb_proc = None
            os.environ.pop("DISPLAY", None)
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

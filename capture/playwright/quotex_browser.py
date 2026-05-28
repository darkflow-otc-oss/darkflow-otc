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

    # ── Proxy Fallback ─────────────────────────────────────────────────────
    async def _recreate_context_without_proxy(self):
        """Recria o browser context sem proxy (fallback)."""
        logger.warning("🔄 Recreating browser context WITHOUT proxy...")
        if self.page:
            await self.page.close()
            self.page = None
        if self.context:
            await self.context.close()
            self.context = None
        self._use_proxy = False
        self.context = await self.browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        self.is_logged_in = False  # force fresh login since context changed

    # ── Navigate ─────────────────────────────────────────────────────────────
    async def navigate(self, url: str = QUOTEX_URL):
        """Navega para a URL com bypass de Cloudflare Turnstile."""
        logger.info(f"🌐 Navigating to: {url}")
        try:
            await self.page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
        except Exception as e:
            err_msg = str(e).lower()
            if ("tunnel" in err_msg or "proxy" in err_msg) and self._use_proxy:
                logger.warning(f"⚠️  Proxy connection failed, retrying without proxy...")
                await self._recreate_context_without_proxy()
                self.page = await self.context.new_page()
                await Stealth().apply_stealth_async(self.page)
                await self.page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
            else:
                raise
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

    # ── Login Tab Handler ───────────────────────────────────────────────────
    async def _click_login_tab(self):
        """Clicks the 'Login' tab if the page shows Login | Registration tabs.
        The email/password form is hidden when the Registration tab is active.
        """
        tab_selectors = [
            "button:has-text('Log in')",
            "button:has-text('Login')",
            "button:has-text('Sign in')",
            "button:has-text('Sign In')",
            "a:has-text('Log in')",
            "a:has-text('Login')",
            "a:has-text('Sign in')",
            "a:has-text('Sign In')",
            "span:has-text('Log in')",
            "span:has-text('Login')",
            "[role='tab']:has-text('Log')",
            "[role='tab']:has-text('Sign')",
            ".tab:has-text('Log in')",
            ".tab:has-text('Login')",
            ".nav-link:has-text('Log in')",
            ".nav-link:has-text('Login')",
        ]
        for sel in tab_selectors:
            try:
                el = self.page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    logger.info(f"🖱  Clicked Login tab: '{sel}'")
                    await asyncio.sleep(2)
                    return
            except Exception:
                continue

        # Fallback: try clicking any element containing "Login" text
        try:
            login_text_el = self.page.locator("text=Log in").first
            if await login_text_el.count() > 0 and await login_text_el.is_visible():
                await login_text_el.click()
                logger.info("🖱  Clicked Login tab via text match")
                await asyncio.sleep(2)
                return
        except Exception:
            pass

        # Fallback: try "Login" without space
        try:
            login_text_el = self.page.locator("text=Login").first
            if await login_text_el.count() > 0 and await login_text_el.is_visible():
                await login_text_el.click()
                logger.info("🖱  Clicked Login tab via 'Login' text match")
                await asyncio.sleep(2)
                return
        except Exception:
            pass

        logger.debug("🔍 No Login tab found — form may already be visible.")

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

            title = await self.page.title()
            logger.info(f"📄 Sign-in page title: '{title}' | url: {self.page.url}")

            # ── Step 1: Click header "Log in" button to open the modal ─────
            # The sign-in page has a header button that opens a modal with the form.
            # The form elements exist in DOM but are hidden until modal opens.
            modal_opened = False
            header_login_selectors = [
                ".header__button-log-in",
                "a:has-text('Log in')",
                "button:has-text('Log in')",
                "[class*='header'] a:has-text('Log')",
            ]
            for sel in header_login_selectors:
                try:
                    el = self.page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        await el.click()
                        logger.info(f"🖱  Clicked header login button: '{sel}'")
                        modal_opened = True
                        await asyncio.sleep(2)
                        break
                except Exception:
                    continue

            if not modal_opened:
                logger.warning("⚠️  Could not find header login button — trying form anyway.")

            # ── Step 2: Force-show ALL form elements ──────────────────────────
            # The Quotex modal hides elements behind tabs and nested divs.
            # We aggressively make everything visible before interacting.
            await self.page.evaluate("""() => {
                // Force show ALL potentially hidden inputs and their ancestors
                const allInputs = document.querySelectorAll('input');
                allInputs.forEach(el => {
                    let p = el;
                    while (p && p !== document.body) {
                        if (p.style && p.style.display === 'none') p.style.display = '';
                        if (p.style && p.style.visibility === 'hidden') p.style.visibility = 'visible';
                        if (p.style && p.style.opacity === '0') p.style.opacity = '1';
                        // Remove aria-hidden
                        if (p.getAttribute && p.getAttribute('aria-hidden') === 'true') {
                            p.setAttribute('aria-hidden', 'false');
                        }
                        // Remove hidden attribute
                        if (p.hasAttribute && p.hasAttribute('hidden')) {
                            p.removeAttribute('hidden');
                        }
                        p = p.parentElement;
                    }
                    // Remove HTML5 validation from registration fields
                    if (el.id && el.id.includes('registration')) {
                        el.removeAttribute('required');
                        el.removeAttribute('data-required');
                    }
                    if (el.name && el.name.toLowerCase().includes('registration')) {
                        el.removeAttribute('required');
                    }
                });
                return 'done';
            }""")
            await asyncio.sleep(0.5)

            # ── Step 3: Debug DOM state ────────────────────────────────────
            debug_info = await self.page.evaluate("""() => {
                const info = {};
                const emailEl = document.querySelector('#emailInput, input[name="email"], input[type="email"]');
                if (emailEl) info.email = {id: emailEl.id, visible: emailEl.offsetParent !== null};
                const allPwds = document.querySelectorAll('input[type="password"]');
                info.passwordCount = allPwds.length;
                allPwds.forEach((el, i) => {
                    info['pwd' + i] = {id: el.id, name: el.name, visible: el.offsetParent !== null};
                });
                info.loginTabActive = !!document.querySelector('.modal-sign__tab.active');
                info.regTabActive = !!document.querySelector('.modal-sign__tab:not(.active)');
                return info;
            }""")
            logger.info(f"🔍 DOM state: {json.dumps(debug_info, ensure_ascii=False)}")

            # ── Step 4: Fill using Playwright native locator methods ───────
            # Prefer native Playwright fill() which triggers framework events properly
            filled = False
            try:
                # Try filling email via Playwright (requires visibility)
                email_locator = self.page.locator("#emailInput")
                if await email_locator.count() > 0:
                    await email_locator.fill(QUOTEX_EMAIL)
                    logger.info("✅ Email filled via Playwright")
                    filled = True
            except Exception as e:
                logger.debug(f"Playwright email fill failed: {e}")

            if not filled:
                # Fallback: JS fill
                logger.info("⚠️  Playwright fill failed — using JS fallback")
                js_result = await self.page.evaluate("""(args) => {
                    const email = args.email;
                    const pwd = args.password;
                    const emailEl = document.querySelector('#emailInput, input[name="email"], input[type="email"]');
                    const pwdEl = document.querySelector('#password-input, input[name="password"]:not([id*="registration"])');
                    const regPwd = document.querySelector('#password-input-registration');
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    if (emailEl) {
                        nativeSetter.call(emailEl, email);
                        emailEl.dispatchEvent(new Event('input', {bubbles: true}));
                        emailEl.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                    if (pwdEl) {
                        nativeSetter.call(pwdEl, pwd);
                        pwdEl.dispatchEvent(new Event('input', {bubbles: true}));
                        pwdEl.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                    if (regPwd) {
                        nativeSetter.call(regPwd, 'Pass123!@#');
                        regPwd.dispatchEvent(new Event('input', {bubbles: true}));
                        regPwd.removeAttribute('required');
                    }
                    // Fill any other required inputs
                    document.querySelectorAll('input[required]').forEach(el => {
                        if (!el.value && el !== emailEl && el !== pwdEl && el !== regPwd) {
                            if (el.type === 'email' || (el.name && el.name.includes('email')))
                                nativeSetter.call(el, 'placeholder@example.com');
                            else
                                nativeSetter.call(el, 'Pass123!@#');
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.removeAttribute('required');
                        }
                    });
                    return JSON.stringify({
                        ok: true,
                        emailFilled: !!emailEl,
                        pwdFilled: !!pwdEl
                    });
                }""", {"email": QUOTEX_EMAIL, "password": QUOTEX_PASSWORD})
                logger.info(f"🔍 JS fill: {js_result}")

            await self.screenshot("before_login")

            # ── Step 5: Click "Sign in" button ─────────────────────────────
            submitted = False
            submit_selectors = [
                "button:has-text('Sign in')",
                "button:has-text('Sign In')",
                "button:has-text('Log in')",
                "button:has-text('Login')",
                ".modal-sign__block-button",
            ]
            for sel in submit_selectors:
                try:
                    btn = self.page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        logger.info(f"🖱  Clicked submit: '{sel}'")
                        submitted = True
                        break
                except Exception as e:
                    logger.debug(f"Submit click {sel}: {e}")

            if not submitted:
                try:
                    await self.page.locator("#password-input").press("Enter")
                    logger.info("⌨  Pressed Enter on password")
                    submitted = True
                except Exception as e:
                    logger.debug(f"Enter press: {e}")

            if not submitted:
                logger.warning("⚠️  JS form submit as last resort")
                await self.page.evaluate("""() => {
                    const form = document.querySelector('form, .modal-sign__form');
                    if (form && form.requestSubmit) form.requestSubmit();
                    else if (form && form.submit) form.submit();
                }""")

            await asyncio.sleep(6)
            await self.screenshot("after_login")

            # ── Step 6: Verify ─────────────────────────────────────────────
            current_url = self.page.url.lower()
            if "sign-in" in current_url or "login" in current_url:
                error_text = await self.page.evaluate("""() => {
                    const results = [];
                    document.querySelectorAll('input').forEach(el => {
                        if (el.validationMessage) results.push(el.id + ': ' + el.validationMessage);
                    });
                    document.querySelectorAll(
                        '[class*="error"], [class*="alert"], .toast, [role="alert"], ' +
                        '.notification, .message, [class*="message"], [class*="notify"]'
                    ).forEach(el => {
                        const t = el.textContent.trim();
                        if (t && t.length < 500) results.push(t);
                    });
                    const captcha = document.querySelector(
                        '.g-recaptcha, [src*="captcha"], [src*="recaptcha"], iframe[src*="captcha"]'
                    );
                    if (captcha) results.push('CAPTCHA_DETECTED');
                    // Get page body text for clues
                    const bodyText = document.body.innerText.substring(0, 500);
                    results.push('BODY: ' + bodyText);
                    return results.filter(r => r).join(' | ') || 'no error text found';
                }""")
                logger.error(f"❌ Login error/state: {error_text}")
                logger.error(f"❌ Login failed — still on sign-in (url={current_url})")
                return False

            self.is_logged_in = True
            await self._save_cookies()
            logger.info("✅ Login successful — cookies saved. (url=%s)", current_url)
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

        current_url = self.page.url.lower()
        if "sign-in" in current_url or "login" in current_url:
            logger.error(
                "❌ Trade screen blocked — redirected to sign-in (url=%s). "
                "Login may have failed silently.",
                current_url,
            )
        else:
            logger.info("✅ Trade screen loaded. (url=%s)", current_url)

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

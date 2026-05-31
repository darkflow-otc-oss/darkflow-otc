#!/usr/bin/env python3
"""
ws_proxy.py — Quotex WebSocket Tick Capture via Playwright
Captures ticks from qxbroker.com WebSocket and forwards to DARKFLOW API.
Runs on WSL host, connects via iProyal proxy.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from aiohttp import web

# ── Config ──────────────────────────────────────────────────────────────
PROXY_URL = "http://j3LUJ4ZiEaDJFBw2:SSeAXAcMPb7sfPv6_country-br_city-saopaulo_session-iqjDNG8n_lifetime-168h@geo.iproyal.com:12321"
COOKIES_PATH = Path.home() / "darkflow_otc" / "data" / "session" / "cookies.json"
API_URL = "http://localhost:8000/api/ingest/tick"
ASSETS = [
    "BTCUSD_otc", "BCHUSD_otc", "ETHUSD_otc", "EURUSD_otc", "LTCUSD_otc",
    "EURCAD_otc", "USDDZD_otc", "AUDJPY_otc", "USDCHF_otc", "USDCOP_otc",
    "EURAUD_otc", "GBPJPY_otc", "GBPNZD_otc", "NZDUSD_otc", "AUDCHF_otc",
    "AUDUSD_otc", "USDINR_otc", "USDCAD_otc", "USDPKR_otc", "GBPAUD_otc",
    "GBPCAD_otc", "NZDCHF_otc", "USDARS_otc", "USDMXN_otc", "USDEGP_otc",
    "AUDCAD_otc", "EURCHF_otc", "EURGBP_otc", "EURJPY_otc", "NZDCAD_otc",
    "NZDJPY_otc", "USDBDT_otc", "USDIDR_otc", "USDJPY_otc", "USDNGN_otc",
    "USDPHP_otc", "KRAUDNZD_otc", "CADCHF_otc", "GBPCHF_otc", "CADJPY_otc",
    "USDZAR_otc", "GBPUSD_otc", "REURNZD_otc",
]
TARGET_URL = "https://qxbroker.com/en/trade"
WS_FILTER = "ws2.qxbroker.com"
INACTIVITY_TIMEOUT = 30
INITIAL_WS_TIMEOUT = 45
LOG_FILE = "/tmp/ws_proxy.log"

# ── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ws_proxy — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE),
    ],
)
logger = logging.getLogger("ws_proxy")

# ── Socket.IO / Quotex frame parser ─────────────────────────────────────
_SIO_PREFIX = re.compile(rb"^[\x00-\x08]")
_SIO_COUNTER = re.compile(rb"^\d+-?")


# ── Sentiment Extraction (indicador de volume da Quotex) ─────────────────
async def get_sentiment(page) -> dict | None:
    """Extrai o indicador de sentimento BUY/SELL da interface Quotex.
       Formato real: div.MDytE ou div.z6UEz contendo \"X%\\nY%\" (BUY primeiro, SELL depois)."""
    try:
        selectors = [".MDytE", ".z6UEz", ".L3ZaP", "[class*='sentiment']"]
        for sel in selectors:
            elem = await page.query_selector(sel)
            if elem:
                text = await elem.inner_text()
                # Formato: "4%\n96%" — primeiro numero = BUY, segundo = SELL
                match = re.search(r'(\d+)\s*%\s*[\n\s]+(\d+)\s*%', text)
                if match:
                    buy_pct = int(match.group(1))
                    sell_pct = int(match.group(2))
                    majority = "BUY" if buy_pct > sell_pct else "SELL"
                    return {
                        "buy_percent": buy_pct,
                        "sell_percent": sell_pct,
                        "majority": majority,
                        "majority_percent": max(buy_pct, sell_pct),
                        "asset": "BTCUSD_otc",
                    }
        # Fallback: busca qualquer elemento com duas porcentagens
        result = await page.evaluate('''() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const t = (el.innerText || '').trim();
                const m = t.match(/^(\\d+)%\\s+(\\d+)%$/m);
                if (m) return { buy: parseInt(m[1]), sell: parseInt(m[2]) };
            }
            return null;
        }''')
        if result:
            majority = "BUY" if result['buy'] > result['sell'] else "SELL"
            return {
                "buy_percent": result['buy'],
                "sell_percent": result['sell'],
                "majority": majority,
                "majority_percent": max(result['buy'], result['sell']),
                "asset": "BTCUSD_otc",
            }
    except Exception as e:
        logger.debug(f"Sentiment extraction error: {e}")
    return None


def parse_raw_frame(payload: bytes) -> list[dict] | None:
    """Parse raw WebSocket frame into tick dicts."""
    if not payload:
        return None

    cleaned = _SIO_PREFIX.sub(b"", payload)
    cleaned = _SIO_COUNTER.sub(b"", cleaned, count=1)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    # Unwrap Socket.IO event envelope: ["event_name", actual_data]
    if isinstance(data, list) and len(data) == 2 and isinstance(data[0], str):
        data = data[1]

    if not isinstance(data, list):
        return None

    ticks = []
    items = data if (data and isinstance(data[0], list)) else [data]

    for item in items:
        if not isinstance(item, list) or len(item) < 4:
            continue
        symbol, ts_raw, price_raw, direction_raw = item[0], item[1], item[2], item[3]
        if not isinstance(symbol, str) or "_otc" not in symbol.lower():
            continue

        ts_iso = (
            datetime.utcfromtimestamp(float(ts_raw)).isoformat()
            if isinstance(ts_raw, (int, float))
            else datetime.now(timezone.utc).isoformat()
        )
        ticks.append({
            "ts": ts_iso,
            "asset": symbol,
            "price": float(price_raw) if isinstance(price_raw, (int, float)) else 0.0,
            "direction": int(direction_raw) if isinstance(direction_raw, (int, float)) else -1,
        })

    return ticks if ticks else None


class TickProxy:
    """Main proxy: launches browser, intercepts WS, forwards ticks to API."""

    def __init__(self):
        self.last_tick_time = time.monotonic()
        self.tick_count = 0
        self.error_count = 0
        self.ws_connected = False
        self._client: httpx.AsyncClient | None = None
        self._xvfb_proc: subprocess.Popen | None = None
        self._use_proxy = False  # Start without proxy to bypass Cloudflare; enable if needed

    def _ensure_display(self):
        """Start Xvfb virtual display if no DISPLAY available (needed for non-headless)."""
        if "DISPLAY" not in os.environ:
            try:
                self._xvfb_proc = subprocess.Popen(
                    ["Xvfb", ":99", "-screen", "0", "1366x768x24", "-ac"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                os.environ["DISPLAY"] = ":99"
                logger.info("🖥  Xvfb started on :99")
            except FileNotFoundError:
                logger.warning("Xvfb not found — falling back to headless")

    async def _post_tick(self, tick: dict):
        """POST a single tick to the DARKFLOW API."""
        try:
            resp = await self._client.post(API_URL, json=tick, timeout=5)
            if resp.status_code != 200:
                logger.warning("API returned %s: %s", resp.status_code, resp.text)
        except httpx.ConnectError:
            self.error_count += 1
            if self.error_count == 1 or self.error_count % 500 == 0:
                logger.warning("API unreachable (darkflow_api not running?)")
        except Exception:
            self.error_count += 1

    async def _on_frame_received(self, payload: bytes | str):
        """Handle incoming WebSocket frame."""
        self.last_tick_time = time.monotonic()
        self.error_count = 0

        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        ticks = parse_raw_frame(payload)
        if not ticks:
            return

        for tick in ticks:
            self.tick_count += 1
            if self.tick_count % 100 == 0:
                logger.info(
                    "📊 %s ticks forwarded | last: %s @ %.4f",
                    self.tick_count, tick["asset"], tick["price"],
                )
            await self._post_tick(tick)

    async def _post_sentiment(self, sentiment: dict):
        """Envia o sentimento para a API."""
        try:
            resp = await self._client.post(API_URL.replace('/ingest/tick', '/ingest/sentiment'), json=sentiment, timeout=5)
            if resp.status_code != 200:
                logger.warning("API returned %s for sentiment", resp.status_code)
        except Exception as e:
            logger.debug(f"Sentiment post error: {e}")

    async def _sentiment_loop(self, page):
        """Captura o indicador de sentimento a cada 10 segundos e envia para a API."""
        while True:
            await asyncio.sleep(10)
            sentiment = await get_sentiment(page)
            if sentiment:
                await self._post_sentiment(sentiment)

    async def _handle_ws(self, ws):
        """Handle new WebSocket connection."""
        logger.info("🔌 WS detected: %s", ws.url)

        if WS_FILTER not in ws.url:
            logger.info("ℹ️  Ignoring WS (not quotex): %s", ws.url)
            return

        logger.info("🔌 Quotex WebSocket connected: %s", ws.url)
        self.ws_connected = True
        self.last_tick_time = time.monotonic()

        ws.on("framereceived", self._on_frame_received)

        try:
            # Keep connection alive until WS actually closes
            while True:
                await asyncio.sleep(30)
                if ws.is_closed():
                    break
        except Exception:
            pass

        logger.warning("⚠️  WebSocket closed")
        self.ws_connected = False

    async def run(self):
        """Main loop: launch browser, intercept WS, reconnect on failure."""
        self._client = httpx.AsyncClient()

        if not COOKIES_PATH.exists():
            logger.error("Cookies file not found: %s", COOKIES_PATH)
            return

        raw_cookies = json.loads(COOKIES_PATH.read_text())
        cookies = [
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".qxbroker.com"),
                "path": c.get("path", "/"),
                "expires": c.get("expires", -1) if c.get("expires", -1) != -1 else None,
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
                "sameSite": c.get("sameSite", "Lax"),
            }
            for c in raw_cookies
        ]
        logger.info("Loaded %d cookies from %s", len(cookies), COOKIES_PATH)

        self._ensure_display()
        stealth = Stealth()

        while True:
            try:
                await self._run_browser(stealth, cookies)
            except Exception as e:
                logger.error("Browser session crashed: %s", e)

            logger.info("🔄 Reconnecting in 5s...")
            await asyncio.sleep(5)

    def _build_proxy_config(self) -> dict | None:
        """Parse PROXY_URL into Playwright proxy config."""
        if not PROXY_URL:
            return None
        proxy_match = re.match(
            r"https?://([^:]+):([^@]+)@(.+):(\d+)", PROXY_URL
        )
        if proxy_match:
            return {
                "server": f"http://{proxy_match.group(3)}:{proxy_match.group(4)}",
                "username": proxy_match.group(1),
                "password": proxy_match.group(2),
            }
        return {"server": PROXY_URL}

    def _sanitize_cookies(self, raw_cookies: list[dict]) -> list[dict]:
        """Keep only valid cookie fields that Playwright accepts. Ensure expires is float or omitted."""
        valid_fields = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
        clean = []
        for c in raw_cookies:
            cookie = {k: v for k, v in c.items() if k in valid_fields}
            expires = cookie.get("expires")
            if expires is not None and isinstance(expires, (int, float)) and expires > 0:
                cookie["expires"] = float(expires)
            else:
                cookie.pop("expires", None)
            clean.append(cookie)
        return clean

    async def _wait_cloudflare(self, page, timeout: int = 45):
        """Wait for Cloudflare Turnstile to resolve. Returns True if passed."""
        try:
            title = await page.title()
            if "just a moment" not in title.lower():
                logger.info("✅ No Cloudflare — title: %s", title)
                return True

            logger.info("⏳ Cloudflare challenge detected — waiting...")
            for i in range(timeout):
                await asyncio.sleep(1)
                title = await page.title()
                if "just a moment" not in title.lower():
                    logger.info("✅ Cloudflare bypassed after %ds", i + 1)
                    await asyncio.sleep(2)
                    return True
                if (i + 1) % 10 == 0:
                    logger.info("⏳ Cloudflare waiting... %ds", i + 1)

            # Timeout — try reload
            logger.warning("Cloudflare timeout — reloading page...")
            await page.reload(wait_until="networkidle")
            await asyncio.sleep(3)
            title = await page.title()
            if "just a moment" not in title.lower():
                logger.info("✅ Cloudflare passed after reload")
                return True
            logger.error("Cloudflare persists after reload")
            return False
        except Exception as e:
            logger.debug("Cloudflare check error: %s", e)
            return True

    async def _run_browser(self, stealth: Stealth, cookies: list[dict]):
        """Single browser session — exits on crash or inactivity timeout."""
        self.last_tick_time = time.monotonic()
        self.ws_connected = False

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-gpu",
                ],
                proxy=self._build_proxy_config() if self._use_proxy else None,
            )

            safe_cookies = self._sanitize_cookies(cookies)

            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            await context.add_cookies(safe_cookies)

            page = await context.new_page()

            # Apply stealth evasions
            try:
                await stealth.apply_stealth_async(page)
                logger.info("🛡️  playwright-stealth applied")
            except Exception as e:
                logger.warning("stealth apply failed: %s", e)

            # Intercept WebSocket connections
            page.on("websocket", lambda ws: asyncio.create_task(self._handle_ws(ws)))

            # Start sentiment capture loop (every 10 seconds)
            sentiment_task = asyncio.create_task(self._sentiment_loop(page))
            logger.info("📊 Sentiment capture started")
            # Start asset rotation loop (every 120 seconds)
            rotation_task = asyncio.create_task(self._asset_rotation_loop(page))
            logger.info("🔄 Asset rotation started")
            # Initialize trade executor
            global _trade_executor
            _trade_executor = TradeExecutor(page)
            asyncio.create_task(start_http_server())
            logger.info("Trade executor ready on :8002")

            logger.info("🌐 Navigating to %s ...", TARGET_URL)
            try:
                await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logger.error("Navigation failed: %s", e)
                await browser.close()
                return

            # Wait for Cloudflare to clear
            cf_ok = await self._wait_cloudflare(page, timeout=45)
            if cf_ok:
                logger.info("✅ Page ready — url: %s, title: %s", page.url, await page.title())
            else:
                logger.warning("⚠️  Cloudflare still active — page may not work")

            # Debug screenshot
            try:
                await page.screenshot(path="/tmp/ws_proxy_debug.png")
                logger.info("📸 Screenshot saved")
            except Exception:
                pass

            # Inactivity monitor loop
            while True:
                idle = time.monotonic() - self.last_tick_time

                if not self.ws_connected:
                    if idle > INITIAL_WS_TIMEOUT:
                        logger.warning("No Quotex WS after %ds — restarting", INITIAL_WS_TIMEOUT)
                        break
                elif idle > INACTIVITY_TIMEOUT:
                    logger.warning("No ticks for %ds — restarting", INACTIVITY_TIMEOUT)
                    break

                await asyncio.sleep(1)

            rotation_task.cancel()
            await browser.close()

    async def _asset_rotation_loop(self, page):
        """Muda o ativo na interface a cada 60 segundos.
        Usa múltiplas estratégias de seletores — classes CSS da Quotex mudam dinamicamente.
        NUNCA usa navegação direta por URL — isso mata o WebSocket e força restart."""
        asset_index = 0
        while True:
            await asyncio.sleep(60)
            try:
                asset = ASSETS[asset_index % len(ASSETS)]
                asset_index += 1

                # Formata termo de busca: EURUSD_otc -> EUR/USD
                name = asset.replace("_otc", "")
                if len(name) == 6 and name.isalpha():
                    search_text = f"{name[:3]}/{name[3:]}"
                elif "USD" in name and name != "USD":
                    search_text = name.replace("USD", "/USD").replace("//", "/")
                else:
                    search_text = name

                # ── Abrir seletor de ativos ──
                clicked = False
                opener_selectors = [
                    # Text-based (mais robustos — classes Quotex mudam)
                    page.get_by_text("OTC", exact=False),
                    page.locator("text=/[A-Z]{3}\s*/\s*[A-Z]{3}"),
                    # Data attributes (se existirem)
                    page.locator("[data-testid*='asset']").first,
                    page.locator("[data-testid*='symbol']").first,
                    # Class patterns (menos frágeis que nomes exatos)
                    page.locator("[class*='asset']").first,
                    page.locator("[class*='current']").first,
                    page.locator("[class*='selected']").first,
                    page.locator("[class*='symbol']").first,
                    page.locator("[class*='instrument']").first,
                    # Structural: qualquer div contendo SVG + texto de 6 letras
                    page.locator("div:has(> svg) >> text=/[A-Z]{6}/"),
                ]
                for sel in opener_selectors:
                    try:
                        await sel.first.click(timeout=2000)
                        clicked = True
                        logger.info("🔄 Opened asset selector via: %s", sel)
                        break
                    except Exception:
                        continue

                if not clicked:
                    logger.warning("🔄 Rotation: could not open asset selector — skipping cycle")
                    continue

                await asyncio.sleep(1.5)

                # ── Digitar termo de busca ──
                typed = False
                search_input_selectors = [
                    page.locator("input[type='text']").first,
                    page.locator("input[type='search']").first,
                    page.locator("input:not([type='hidden'])").first,
                ]
                for inp in search_input_selectors:
                    try:
                        await inp.fill(search_text, timeout=2000)
                        typed = True
                        break
                    except Exception:
                        continue

                if not typed:
                    logger.warning("🔄 Rotation: could not type search for %s", search_text)
                    # Press Escape to close dropdown if it opened
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass
                    continue

                await asyncio.sleep(0.5)

                # ── Clicar resultado ──
                item = page.locator(f"text={search_text}").first
                await item.click(timeout=5000)
                logger.info("✅ Rotated to %s (%s)", asset, search_text)
            except Exception as e:
                logger.warning("Asset rotation failed for %s: %s", asset, str(e)[:120])


# ── Trade Executor (recebe ordens da API e executa na Quotex) ────────────
class TradeExecutor:
    def __init__(self, page):
        self.page = page
        self.current_asset = None

    async def switch_asset(self, target_asset_display: str):
        if self.current_asset == target_asset_display:
            return True
        try:
            # Clica no seletor de ativos (div que mostra o ativo atual)
            btn = await self.page.query_selector("div.h9gji") or await self.page.query_selector("div.ifu_i")
            if btn:
                await btn.click()
                await asyncio.sleep(0.8)
            # Procura e clica no ativo desejado pelo texto
            await self.page.click(f"text={target_asset_display}", timeout=5000)
            await asyncio.sleep(1)
            self.current_asset = target_asset_display
            logger.info("Asset switched to %s", target_asset_display)
            return True
        except Exception as e:
            logger.warning("Failed to switch asset: %s", e)
            return False

    async def execute_trade(self, data: dict) -> dict:
        try:
            asset_display = data.get("asset_display", "")
            direction = data.get("direction", "")  # CALL or PUT
            amount = str(data.get("amount", 100))

            if direction not in ("CALL", "PUT"):
                return {"error": "Invalid direction"}

            if not await self.switch_asset(asset_display):
                return {"error": "Failed to switch asset", "asset": asset_display}

            # Preencher valor no input de investimento
            amount_input = await self.page.query_selector("div.deal-amount-input input")
            if amount_input:
                await amount_input.click()
                await asyncio.sleep(0.2)
                # Limpa e preenche
                await amount_input.fill("")
                await amount_input.fill(amount)
                await asyncio.sleep(0.5)

            # Clicar CALL (Up) ou PUT (Down)
            if direction == "CALL":
                btn = await self.page.query_selector('button:has-text("Up")')
            else:
                btn = await self.page.query_selector('button:has-text("Down")')

            if btn:
                await btn.click()
                logger.info("Trade executed: %s %s R$%s", asset_display, direction, amount)
                return {"status": "executed", "asset": asset_display, "direction": direction}
            return {"error": "Button not found for %s" % direction}
        except Exception as e:
            logger.error("Trade execution error: %s", e)
            return {"error": str(e)}


_trade_executor: TradeExecutor | None = None


async def handle_trade(request):
    global _trade_executor
    if not _trade_executor:
        return web.Response(status=503, text="Trade executor not ready")
    try:
        data = await request.json()
        result = await _trade_executor.execute_trade(data)
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def start_http_server():
    app = web.Application()
    app.router.add_post("/trade", handle_trade)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 8002)
    await site.start()
    logger.info("Trade execution HTTP server running on http://localhost:8002")
    while True:
        await asyncio.sleep(3600)


async def main():
    proxy = TickProxy()
    await proxy.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 ws_proxy stopped by user")

#!/usr/bin/env python3
"""
ws_proxy.py — Quotex WebSocket Tick Capture via Playwright
Captures ticks from qxbroker.com WebSocket and forwards to DARKFLOW API.
Runs on WSL host, connects via iProyal proxy.
"""

import asyncio
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# ── Config ──────────────────────────────────────────────────────────────
PROXY_URL = "http://j3LUJ4ZiEaDJFBw2:SSeAXAcMPb7sfPv6_country-br_city-saopaulo_session-iqjDNG8n_lifetime-168h@geo.iproyal.com:12321"
COOKIES_PATH = Path.home() / "darkflow_otc" / "data" / "session" / "cookies.json"
API_URL = "http://localhost:8000/api/ingest/tick"
TARGET_URL = "https://qxbroker.com/en/trade"
WS_FILTER = "ws2.qxbroker.com"
INACTIVITY_TIMEOUT = 30
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

    async def _handle_ws(self, ws):
        """Handle new WebSocket connection — filter by ws2.qxbroker.com."""
        if WS_FILTER not in ws.url:
            return

        logger.info("🔌 WebSocket connected: %s", ws.url)
        self.ws_connected = True
        self.last_tick_time = time.monotonic()

        ws.on("framereceived", self._on_frame_received)

        try:
            await ws.wait_for_event("close", timeout=300)
        except asyncio.TimeoutError:
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
        # Normalize cookies: keep only standard fields playwright accepts
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
            # Playwright requires expires to be a positive float; session cookies omit it
            expires = cookie.get("expires")
            if expires is not None and isinstance(expires, (int, float)) and expires > 0:
                cookie["expires"] = float(expires)
            else:
                cookie.pop("expires", None)
            clean.append(cookie)
        return clean

    async def _run_browser(self, stealth: Stealth, cookies: list[dict]):
        """Single browser session — exits on crash or inactivity timeout."""
        self.last_tick_time = time.monotonic()
        self.ws_connected = False

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
                proxy=self._build_proxy_config(),
            )

            safe_cookies = self._sanitize_cookies(cookies)

            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
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

            logger.info("🌐 Navigating to %s ...", TARGET_URL)
            try:
                await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logger.error("Navigation failed: %s", e)
                await browser.close()
                return

            logger.info("✅ Page loaded — waiting for WebSocket ticks...")

            # Inactivity monitor loop
            while True:
                idle = time.monotonic() - self.last_tick_time

                if not self.ws_connected:
                    if idle > 15:
                        logger.warning("No WebSocket after 15s — restarting")
                        break
                elif idle > INACTIVITY_TIMEOUT:
                    logger.warning("No ticks for %ds — restarting", INACTIVITY_TIMEOUT)
                    break

                await asyncio.sleep(1)

            await browser.close()


async def main():
    proxy = TickProxy()
    await proxy.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 ws_proxy stopped by user")

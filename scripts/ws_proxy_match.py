#!/usr/bin/env python3
"""ws_proxy_match.py — Multi-asset tick capture with substring symbol matching."""
import asyncio, json, logging, argparse, re, time, httpx
from pathlib import Path
from datetime import datetime, timezone
from aiohttp import web
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

parser = argparse.ArgumentParser()
parser.add_argument('--asset', default='BTCUSD_otc')
parser.add_argument('--profile', default='/tmp/playwright_profile')
parser.add_argument('--port', type=int, default=8002)
args = parser.parse_args()

ASSET = args.asset
PROFILE = Path(args.profile)
TRADE_PORT = args.port
PROFILE.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format=f'%(asctime)s [%(levelname)s] {ASSET} - %(message)s')
logger = logging.getLogger(ASSET)

COOKIES_PATH = Path.home() / "darkflow_otc" / "data" / "session" / "cookies.json"
API_URL = "http://localhost:8000/api/ingest/tick"
TARGET_URL = "https://qxbroker.com/en/trade"
_SIO_PREFIX = re.compile(rb'^[\x00-\x08]')
_SIO_COUNTER = re.compile(rb'^\d+-?')

BASE = ASSET.replace('_otc', '')

def parse_frame(payload):
    if not payload: return None
    cleaned = _SIO_PREFIX.sub(b'', payload)
    cleaned = _SIO_COUNTER.sub(b'', cleaned, count=1)
    try: data = json.loads(cleaned)
    except: return None
    if isinstance(data, list) and len(data) == 2 and isinstance(data[0], str):
        data = data[1]
    if not isinstance(data, list): return None
    ticks = []
    items = data if (data and isinstance(data[0], list)) else [data]
    for item in items:
        if not isinstance(item, list) or len(item) < 4: continue
        sym = str(item[0])
        if BASE.lower() not in sym.lower(): continue
        ts_raw, price_raw, dir_raw = item[1], item[2], item[3]
        ts_iso = datetime.utcfromtimestamp(float(ts_raw)).isoformat() if isinstance(ts_raw, (int, float)) else datetime.now(timezone.utc).isoformat()
        ticks.append({"ts": ts_iso, "asset": ASSET, "price": float(price_raw), "direction": int(dir_raw)})
    return ticks

async def process_frame(payload):
    if isinstance(payload, str): payload = payload.encode()
    ticks = parse_frame(payload)
    if not ticks: return
    async with httpx.AsyncClient() as cl:
        for t in ticks:
            try: await cl.post(API_URL, json=t, timeout=5)
            except: pass

async def handle_ws(ws):
    if 'ws2.qxbroker.com' not in ws.url: return
    logger.info("WebSocket connected")
    ws.on('framereceived', lambda p: asyncio.create_task(process_frame(p)))
    while True:
        await asyncio.sleep(30)
        if ws.is_closed(): break
    logger.warning("WebSocket closed")

class TradeExecutor:
    def __init__(self, page): self.page = page
    async def execute(self, data):
        amt = str(data.get('amount', 100)); direction = data.get('direction')
        if direction not in ('CALL', 'PUT'): return {'error': 'invalid direction'}
        try:
            inp = await self.page.query_selector('div.deal-amount-input input')
            if inp: await inp.fill(amt); await asyncio.sleep(0.5)
            btn = await self.page.query_selector('button:has-text("Up")') if direction == 'CALL' else await self.page.query_selector('button:has-text("Down")')
            if btn: await btn.click(); logger.info(f"Trade executed: {direction} R${amt}")
            return {'status': 'executed', 'asset': ASSET, 'direction': direction}
            return {'error': 'button not found'}
        except Exception as e: return {'error': str(e)}

_trade_exec = None
async def handle_trade(req):
    global _trade_exec
    if not _trade_exec: return web.Response(status=503, text='not ready')
    data = await req.json()
    return web.json_response(await _trade_exec.execute(data))

async def start_http():
    app = web.Application(); app.router.add_post('/trade', handle_trade)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, 'localhost', TRADE_PORT).start()
    logger.info(f"HTTP trade on :{TRADE_PORT}")
    await asyncio.Event().wait()

async def sentiment_loop(page):
    while True:
        await asyncio.sleep(10)
        try:
            sel = await page.query_selector('.MDytE, .z6UEz')
            if sel:
                txt = await sel.inner_text()
                m = re.search(r'(\d+)%\s*[\n\s]+(\d+)%', txt)
                if m:
                    buy, sell = int(m.group(1)), int(m.group(2))
                    maj = "BUY" if buy > sell else "SELL"
                    async with httpx.AsyncClient() as cl:
                        await cl.post('http://localhost:8000/api/ingest/sentiment',
                                       json={'majority': maj, 'majority_percent': max(buy, sell), 'asset': ASSET}, timeout=5)
        except: pass

async def run_browser():
    if not COOKIES_PATH.exists(): logger.error("Cookies missing"); return
    raw = json.loads(COOKIES_PATH.read_text())
    cookies = [{'name': c['name'], 'value': c['value'], 'domain': c.get('domain', '.qxbroker.com'),
                'path': c.get('path', '/'), 'expires': c.get('expires') if isinstance(c.get('expires'), (int, float)) and c.get('expires', 0) > 0 else None,
                'httpOnly': c.get('httpOnly', False), 'secure': c.get('secure', False), 'sameSite': c.get('sameSite', 'Lax')} for c in raw]
    logger.info(f"Loaded {len(cookies)} cookies")
    stealth = Stealth()
    while True:
        try:
            async with async_playwright() as p:
                ctx = await p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE), headless=False,
                    args=['--no-sandbox', '--disable-blink-features=AutomationControlled', '--disable-infobars', '--disable-gpu'])
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await stealth.apply_stealth_async(page)
                page.on('websocket', lambda ws: asyncio.create_task(handle_ws(ws)))
                asyncio.create_task(sentiment_loop(page))
                global _trade_exec; _trade_exec = TradeExecutor(page)
                asyncio.create_task(start_http())
                await page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=60000)
                logger.info("Page loaded")
                while True: await asyncio.sleep(30)
        except Exception as e: logger.error(f"Browser crashed: {e}")
        await asyncio.sleep(5)

if __name__ == '__main__':
    asyncio.run(run_browser())

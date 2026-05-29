#!/usr/bin/env python3
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

COOKIES_PATH = Path.home() / "darkflow_otc/data/session/cookies.json"
API_URL = "http://localhost:8000/api/ingest/tick"

ASSET_ALIASES = {
    "BTCUSD_otc": ["btcusd_otc","btcusd","btc/usd","bitcoin"],
    "BCHUSD_otc": ["bchusd_otc","bchusd","bch/usd","bitcoin cash"],
    "EURUSD_otc": ["eurusd_otc","eurusd","eur/usd"],
    "USDJPY_otc": ["usdjpy_otc","usdjpy","usd/jpy"],
    "TRUMPUSD_otc": ["trumpusd_otc","trumpusd","trump/usd","trump"],
    "GBPUSD_otc": ["gbpusd_otc","gbpusd","gbp/usd"],
    "AVAUSD_otc": ["avausd_otc","avausd","ava/usd","avalanche"],
}

def match(sym):
    s = str(sym).lower()
    return any(a in s for a in ASSET_ALIASES.get(ASSET, [ASSET.lower()]))

_PRE = re.compile(rb'^[\x00-\x08]')
_CTR = re.compile(rb'^\d+-?')

def parse_frame(payload):
    if isinstance(payload, str): payload = payload.encode()
    c = _PRE.sub(b'', payload)
    c = _CTR.sub(b'', c, count=1)
    try: data = json.loads(c)
    except: return None
    if isinstance(data, list) and len(data)==2 and isinstance(data[0], str): data = data[1]
    if not isinstance(data, list): return None
    ticks = []
    items = data if (data and isinstance(data[0], list)) else [data]
    for item in items:
        if not isinstance(item, list) or len(item)<4: continue
        sym, ts_raw, price_raw, dir_raw = item[0], item[1], item[2], item[3]
        if not match(sym): continue
        ts = datetime.utcfromtimestamp(float(ts_raw)).isoformat() if isinstance(ts_raw,(int,float)) else datetime.now(timezone.utc).isoformat()
        ticks.append({"ts":ts,"asset":ASSET,"price":float(price_raw),"direction":int(dir_raw)})
    return ticks

_executor = None
async def handle_trade(req):
    global _executor
    if not _executor: return web.Response(status=503, text='not ready')
    try:
        data = await req.json()
        return web.json_response(await _executor(data))
    except Exception as e: return web.json_response({'error':str(e)}, status=500)

async def start_http():
    app = web.Application()
    app.router.add_post('/trade', handle_trade)
    r = web.AppRunner(app); await r.setup()
    await web.TCPSite(r, 'localhost', TRADE_PORT).start()
    logger.info(f"Trade server :{TRADE_PORT}")
    await asyncio.Event().wait()

async def sentiment_loop(page):
    while True:
        await asyncio.sleep(10)
        try:
            el = await page.query_selector('.MDytE, .z6UEz')
            if el:
                txt = await el.inner_text()
                m = re.search(r'(\d+)%\s*(BUY|SELL)', txt, re.I)
                if m:
                    async with httpx.AsyncClient() as cl:
                        await cl.post('http://localhost:8000/api/ingest/sentiment',
                            json={'majority':m.group(2).upper(),'majority_percent':int(m.group(1)),'asset':ASSET}, timeout=5)
        except: pass

async def select_asset(page):
    """Tenta selecionar o ativo via JavaScript no localStorage e clique no seletor."""
    try:
        await page.evaluate(f"""
            localStorage.setItem('selected-asset', '{ASSET}');
            localStorage.setItem('currentAsset', '{ASSET}');
        """)
        logger.info(f"localStorage definido para {ASSET}")
        await asyncio.sleep(3)
        dropdowns = await page.query_selector_all('[class*="asset"], [class*="pair"], .asset-select, .pair-name')
        for dropdown in dropdowns:
            try:
                await dropdown.click()
                await asyncio.sleep(1)
                break
            except: continue
        asset_base = ASSET.replace('_otc','').replace('USD','')
        items = await page.query_selector_all('[class*="option"], [class*="asset-item"], li, .pPomf, .rKkq0')
        for item in items:
            try:
                txt = await item.inner_text()
                if asset_base.lower() in txt.lower() or ASSET.lower() in txt.lower():
                    await item.click()
                    logger.info(f"✅ Ativo {ASSET} selecionado via clique em '{txt.strip()}'")
                    return True
            except: continue
        logger.info("Dropdown nao encontrado — aguardando selecao manual")
    except Exception as e:
        logger.warning(f"select_asset: {e}")
    return False

async def run():
    if not COOKIES_PATH.exists(): logger.error("Cookies missing"); return
    raw = json.loads(COOKIES_PATH.read_text())
    cookies = [{'name':c['name'],'value':c['value'],'domain':c.get('domain','.qxbroker.com'),
        'path':c.get('path','/'),'httpOnly':c.get('httpOnly',False),'secure':c.get('secure',False)} for c in raw]
    stealth = Stealth()
    while True:
        try:
            async with async_playwright() as p:
                ctx = await p.chromium.launch_persistent_context(
                    str(PROFILE), headless=False,
                    args=['--no-sandbox','--disable-blink-features=AutomationControlled','--disable-gpu'])
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await stealth.apply_stealth_async(page)
                await ctx.add_cookies(cookies)

                def on_ws(ws):
                    if 'ws2.qxbroker.com' not in ws.url: return
                    logger.info("WebSocket connected")
                    def on_frame(payload):
                        asyncio.create_task(process_frame(payload))
                    ws.on('framereceived', on_frame)
                page.on('websocket', on_ws)

                asyncio.create_task(sentiment_loop(page))
                asyncio.create_task(start_http())

                global _executor
                async def do_trade(data):
                    amt = str(data.get('amount',100)); d = data.get('direction')
                    if d not in ('CALL','PUT'): return {'error':'invalid'}
                    try:
                        inp = await page.query_selector('div.deal-amount-input input')
                        if inp: await inp.fill(amt); await asyncio.sleep(0.3)
                        btn = await page.query_selector('button:has-text("Up")') if d=='CALL' else await page.query_selector('button:has-text("Down")')
                        if btn: await btn.click(); return {'status':'ok','asset':ASSET,'direction':d}
                        return {'error':'btn not found'}
                    except Exception as e: return {'error':str(e)}
                _executor = do_trade

                await page.goto("https://qxbroker.com/en/trade", wait_until='domcontentloaded', timeout=60000)
                await select_asset(page)
                logger.info("Aguardando ticks...")
                while True: await asyncio.sleep(2)
        except Exception as e: logger.error(f"Crash: {e}")
        await asyncio.sleep(5)

async def process_frame(payload):
    ticks = parse_frame(payload)
    if not ticks: return
    async with httpx.AsyncClient() as cl:
        for t in ticks:
            try: await cl.post(API_URL, json=t, timeout=5)
            except: pass

if __name__ == '__main__':
    asyncio.run(run())

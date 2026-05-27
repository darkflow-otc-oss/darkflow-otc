"""
DARKFLOW OTC — ChromaDB Seed Script
Lê ticks do JSONL, agrupa em janelas, gera embeddings e popula ChromaDB.
"""

import json
import logging
import re
import sys
from pathlib import Path
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger("darkflow.seed")

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from patterns.clustering.embedding_generator import EmbeddingGenerator
from patterns.features.sequence_encoder import SequenceEncoder
from database.vectors.chroma_manager import ChromaManager

WINDOW = 10
SIO_PREFIX = re.compile(r"^[\x00-\x08]")
SIO_COUNTER = re.compile(r"^\d+-")


def parse_jsonl(jsonl_path: str) -> list[dict]:
    """Extract price data points from JSONL. Returns list of [ts, price, direction]."""
    all_ticks: list[dict] = []

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            data = entry.get("data", {})
            if not isinstance(data, dict):
                continue
            raw = data.get("raw", "")
            if not isinstance(raw, str):
                continue

            cleaned = SIO_PREFIX.sub("", raw)
            cleaned = SIO_COUNTER.sub("", cleaned, count=1)

            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                continue

            # History messages: {"asset":"BTCUSD_otc","period":60,"history":[[ts,price,dir],...]}
            if isinstance(parsed, dict) and "history" in parsed:
                asset = parsed.get("asset", "unknown")
                for point in parsed["history"]:
                    if isinstance(point, list) and len(point) >= 3:
                        all_ticks.append({
                            "asset": asset,
                            "ts": point[0],
                            "price": float(point[1]),
                            "direction": int(point[2]),
                        })

            # Price updates: [{"id":"...","price":74450.61,"asset":"BTCUSD_otc"}]
            elif isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
                obj = parsed[0]
                if "price" in obj and "asset" in obj:
                    all_ticks.append({
                        "asset": obj["asset"],
                        "ts": parsed[0].get("id", ""),
                        "price": float(obj["price"]),
                        "direction": 0,
                    })

    return all_ticks


def ticks_to_candles(ticks: list[dict]) -> list[dict]:
    """Convert consecutive ticks into OHLC candles."""
    candles = []
    for i in range(len(ticks) - 1):
        t0 = ticks[i]
        t1 = ticks[i + 1]
        if t0["asset"] != t1["asset"]:
            continue
        o_price = t0["price"]
        c_price = t1["price"]
        candles.append({
            "asset": t0["asset"],
            "ts": t0["ts"],
            "timeframe": 60,
            "open": o_price,
            "high": max(o_price, c_price),
            "low": min(o_price, c_price),
            "close": c_price,
        })
    return candles


def main():
    jsonl_files = sorted(Path("data/raw").glob("*.jsonl"))
    if not jsonl_files:
        logger.error("No JSONL files found in data/raw/")
        return

    logger.info(f"Found {len(jsonl_files)} JSONL file(s)")

    all_ticks = []
    for fp in jsonl_files:
        ticks = parse_jsonl(str(fp))
        logger.info(f"  {fp.name}: {len(ticks)} ticks extracted")
        all_ticks.extend(ticks)

    logger.info(f"Total ticks: {len(all_ticks)}")

    # Group by asset
    by_asset: dict[str, list] = {}
    for t in all_ticks:
        by_asset.setdefault(t["asset"], []).append(t)

    for asset, ticks in sorted(by_asset.items()):
        logger.info(f"  {asset}: {len(ticks)} ticks")

    # Convert to candles per asset
    encoder = SequenceEncoder(window=WINDOW)
    generator = EmbeddingGenerator()
    chroma = ChromaManager(persist_path="./chroma_data")

    total_indexed = 0

    for asset, ticks in by_asset.items():
        candles = ticks_to_candles(ticks)
        logger.info(f"🕯  {asset}: {len(candles)} candles from {len(ticks)} ticks")

        if len(candles) < WINDOW:
            logger.warning(f"  ⚠️  {asset}: only {len(candles)} candles, skipping (need {WINDOW})")
            continue

        # Slide window
        batch_count = 0
        for start in range(0, len(candles) - WINDOW + 1, WINDOW // 2):
            window = candles[start:start + WINDOW]
            if len(window) < WINDOW:
                break

            seq_vector = encoder.encode_vector(window)
            if not seq_vector:
                continue

            embedding = generator.generate(seq_vector)
            if not embedding:
                continue

            pattern_id = f"{asset}_{start}_{uuid4().hex[:6]}"
            first_ts = window[0].get("ts", "")
            last_ts = window[-1].get("ts", "")

            # Determine pattern type based on price movement
            first_price = window[0]["close"]
            last_price = window[-1]["close"]
            price_change = (last_price - first_price) / first_price if first_price else 0

            if price_change > 0.002:
                pattern_type = "bullish_breakout"
                signal = "CALL"
            elif price_change < -0.002:
                pattern_type = "bearish_breakdown"
                signal = "PUT"
            else:
                # Check for compression/consolidation
                ranges = [c["high"] - c["low"] for c in window]
                avg_range = sum(ranges) / len(ranges)
                if avg_range < first_price * 0.0005:
                    pattern_type = "liquidity_hunt"
                    signal = "CALL" if window[-1]["close"] >= window[0]["close"] else "PUT"
                else:
                    pattern_type = "consolidation"
                    signal = "CALL"

            metadata = {
                "asset": asset,
                "pattern_type": pattern_type,
                "signal": signal,
                "confidence": round(min(abs(price_change) * 100, 1.0), 4),
                "direction": 1 if price_change >= 0 else -1,
                "detected_at": str(first_ts),
                "indexed_at": str(last_ts),
                "outcome": "UNKNOWN",
            }

            try:
                chroma.add_pattern(pattern_id, embedding, metadata)
                batch_count += 1
            except Exception as e:
                logger.warning(f"  ⚠️  Failed to index {pattern_id}: {e}")

        total_indexed += batch_count
        logger.info(f"  ✅ {asset}: {batch_count} patterns indexed")

    logger.info(f"\n{'═' * 50}")
    logger.info(f"✅ Seed complete — {total_indexed} patterns indexed in ChromaDB")
    logger.info(f"   Collection: darkflow_patterns")
    logger.info(f"   Total docs : {chroma.count()}")


if __name__ == "__main__":
    main()

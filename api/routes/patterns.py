"""
DARKFLOW OTC — API Routes: Patterns + Realtime Detection
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from patterns.detectors.pattern_pipeline import PatternPipeline

logger = logging.getLogger("darkflow.api.patterns")
router = APIRouter(prefix="/api/patterns", tags=["Patterns"])

# Pipeline singleton por asset
_pipelines: dict[str, PatternPipeline] = {}

# ChromaDB singleton (lazy init)
_chroma = None


def _get_chroma():
    global _chroma
    if _chroma is None:
        from database.vectors.chroma_manager import ChromaManager
        _chroma = ChromaManager(persist_path="./chroma_data")
    return _chroma


def get_pipeline(asset: str) -> PatternPipeline:
    if asset not in _pipelines:
        _pipelines[asset] = PatternPipeline(asset=asset)
    return _pipelines[asset]


class CandleInput(BaseModel):
    asset: str = "EURUSD_otc"
    candles: list[dict]


@router.post("/detect")
async def detect_pattern(payload: CandleInput):
    """
    Recebe janela de candles e roda o pipeline de detecção.
    Retorna o padrão detectado com probabilidade histórica.
    """
    if len(payload.candles) < 3:
        raise HTTPException(status_code=400, detail="Minimum 3 candles required.")

    pipeline = get_pipeline(payload.asset)
    detection = pipeline.run(payload.candles)

    if not detection:
        return {"asset": payload.asset, "detected": False, "pattern": None}

    return {"asset": payload.asset, "detected": True, "pattern": detection}


@router.post("/record-outcome")
async def record_outcome(
    asset: str,
    pattern_type: str,
    signal: str,
    outcome: str,
):
    """
    Registra resultado real de um padrão (WIN/LOSS).
    Alimenta o ProbabilityEngine com dados históricos reais.
    """
    if outcome not in ("WIN", "LOSS"):
        raise HTTPException(status_code=400, detail="outcome must be WIN or LOSS")
    if signal not in ("CALL", "PUT"):
        raise HTTPException(status_code=400, detail="signal must be CALL or PUT")

    pipeline = get_pipeline(asset)
    pipeline.probability.record(pattern_type, signal, outcome)

    return {
        "recorded": True,
        "asset": asset,
        "pattern_type": pattern_type,
        "signal": signal,
        "outcome": outcome,
    }


@router.get("/stats")
async def pattern_stats(asset: str = "EURUSD_otc"):
    """Retorna estatísticas acumuladas do pipeline."""
    pipeline = get_pipeline(asset)
    return pipeline.stats()


@router.get("/probability")
async def get_probability(
    asset: str = "EURUSD_otc",
    pattern_type: str = "liquidity_hunt",
    signal: str = "CALL",
):
    """Consulta probabilidade histórica de um padrão."""
    pipeline = get_pipeline(asset)
    return pipeline.probability.get_probability(pattern_type, signal)


@router.get("/similar")
async def get_similar_patterns(
    asset: str = Query("EURUSD_otc", description="Asset symbol"),
    limit: int = Query(5, ge=1, le=50, description="Max results"),
):
    """Retorna padrões similares do ChromaDB para um ativo."""
    try:
        chroma = _get_chroma()
        all_patterns = chroma.get_all(limit=100)
    except Exception as e:
        logger.warning(f"ChromaDB unavailable: {e}")
        return []

    matches = []
    for p in all_patterns:
        meta = p.get("metadata", {})
        if isinstance(meta, dict) and meta.get("asset") == asset:
            matches.append({
                "id": p["id"],
                "cosine_score": 1.0 - (p.get("distance") or 0),
                "pattern_type": meta.get("pattern_type", "unknown"),
                "asset": meta.get("asset", asset),
                "signal": meta.get("signal", ""),
                "confidence": meta.get("confidence", 0),
                "detected_at": meta.get("indexed_at", ""),
                "outcome": meta.get("outcome", "UNKNOWN"),
            })

    # Sort by recency (id order as proxy) and limit
    matches.sort(key=lambda x: x["id"], reverse=True)
    return matches[:limit]


@router.get("/detect")
async def get_latest_detection(
    asset: str = Query("EURUSD_otc", description="Asset symbol"),
):
    """Retorna a detecção mais recente ou status de espera."""
    pipeline = get_pipeline(asset)
    stats = pipeline.stats()
    last = stats.get("last_detection")

    if not last:
        return {
            "asset": asset,
            "detected": False,
            "pattern_type": None,
            "confidence": 0,
            "signal": None,
            "detected_at": None,
            "message": "No pattern detected yet — awaiting data.",
        }

    return {
        "asset": asset,
        "detected": True,
        **last,
    }

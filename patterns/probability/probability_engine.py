"""
DARKFLOW OTC — Probability Engine
Transforma histórico de padrões em probabilidades reais.
Responsabilidade: medir repetição e gerar scores confiáveis.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

logger = logging.getLogger("darkflow.probability")

PROB_DATA_DIR = Path("data/probabilities")
PROB_DATA_DIR.mkdir(parents=True, exist_ok=True)


class ProbabilityEngine:
    """
    Mantém contadores de ocorrências por padrão/ativo
    e calcula probabilidades baseadas em histórico real.
    """

    def __init__(self, asset: str = "EURUSD_otc"):
        self.asset = asset
        self._data: dict = defaultdict(lambda: {
            "total": 0,
            "CALL": 0,
            "PUT": 0,
            "wins": 0,
            "losses": 0,
        })
        self._load()

    def _path(self) -> Path:
        return PROB_DATA_DIR / f"prob_{self.asset}.json"

    def _load(self):
        try:
            if self._path().exists():
                with open(self._path()) as f:
                    raw = json.load(f)
                    self._data.update(raw)
                logger.info(f"📂 Probability data loaded: {self._path()}")
        except Exception as e:
            logger.warning(f"⚠️  Could not load probability data: {e}")

    def _save(self):
        try:
            with open(self._path(), "w") as f:
                json.dump(dict(self._data), f, indent=2)
        except Exception as e:
            logger.warning(f"⚠️  Could not save probability data: {e}")

    def record(self, pattern_type: str, signal: str, outcome: str):
        """
        Registra resultado de um padrão.
        signal: 'CALL' | 'PUT'
        outcome: 'WIN' | 'LOSS'
        """
        key = f"{pattern_type}"
        self._data[key]["total"] += 1
        self._data[key][signal] = self._data[key].get(signal, 0) + 1
        if outcome == "WIN":
            self._data[key]["wins"] += 1
        else:
            self._data[key]["losses"] += 1
        self._save()

    def get_probability(self, pattern_type: str, signal: str) -> dict:
        """Retorna probabilidade de win para um padrão + direção."""
        key = pattern_type
        d = self._data.get(key, {})
        total = d.get("total", 0)
        wins = d.get("wins", 0)

        if total < 5:
            return {
                "pattern_type": pattern_type,
                "signal": signal,
                "probability": 0.50,
                "sample_size": total,
                "reliable": False,
                "note": "insufficient data",
            }

        prob = wins / total
        return {
            "pattern_type": pattern_type,
            "signal": signal,
            "probability": round(prob, 4),
            "sample_size": total,
            "wins": wins,
            "losses": d.get("losses", 0),
            "reliable": total >= 20,
        }

    def enrich_detection(self, detection: dict) -> dict:
        """Adiciona probabilidade histórica a um detection result."""
        pattern_type = detection.get("pattern_type", "unknown")
        signal = detection.get("signal", "CALL")
        prob = self.get_probability(pattern_type, signal)
        detection["historical_probability"] = prob
        detection["enriched_at"] = datetime.now(UTC).isoformat()
        return detection

    def summary(self) -> dict:
        """Resumo de todos os padrões registrados."""
        out = {}
        for key, d in self._data.items():
            total = d.get("total", 0)
            wins = d.get("wins", 0)
            out[key] = {
                "total": total,
                "win_rate": round(wins / total, 4) if total > 0 else 0,
                "reliable": total >= 20,
            }
        return out

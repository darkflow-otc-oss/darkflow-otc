"""
DARKFLOW OTC — Pattern Pipeline
Orquestra todos os detectores em sequência sobre uma janela de candles.
Responsabilidade: ponto de entrada único para detecção de padrões.
Persiste padrões detectados no banco via repositories.
"""

import logging
from typing import Optional
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import AsyncSession

from patterns.detectors.continuation_detector import ContinuationDetector
from patterns.detectors.reversal_detector import ReversalDetector
from patterns.detectors.fake_break_detector import FakeBreakDetector
from patterns.probability.probability_engine import ProbabilityEngine
from patterns.features.sequence_encoder import SequenceEncoder
from database.postgres.repositories import insert_pattern

logger = logging.getLogger("darkflow.patterns.pipeline")


class PatternPipeline:
    """
    Roda todos os detectores sobre uma janela de candles.
    Retorna a primeira detecção com maior confidence,
    enriquecida com probabilidade histórica.
    Opcionalmente persiste no banco via repositório.
    """

    def __init__(self, asset: str = "EURUSD_otc", window: int = 5):
        self.asset = asset
        self.window = window
        self.continuation = ContinuationDetector(window=window)
        self.reversal = ReversalDetector(window=window)
        self.fake_break = FakeBreakDetector(window=window)
        self.probability = ProbabilityEngine(asset=asset)
        self.encoder = SequenceEncoder(window=window)
        self._detections_total = 0

    def run(
        self,
        candles: list[dict],
        session: Optional[AsyncSession] = None,
    ) -> Optional[dict]:
        """
        Executa pipeline completo sobre janela de candles.

        Args:
            candles: lista de dicionários OHLC
            session: AsyncSession opcional para persistir no banco

        Prioridade: FakeBreak > Reversal > Continuation
        """
        if len(candles) < self.window:
            return None

        detection = (
            self.fake_break.detect(candles)
            or self.reversal.detect(candles)
            or self.continuation.detect(candles)
        )

        if not detection:
            return None

        self._detections_total += 1

        # Enriquece com probabilidade histórica
        detection = self.probability.enrich_detection(detection)

        # Adiciona contexto
        detection["asset"] = self.asset
        detection["detected_at"] = datetime.now(UTC).isoformat()
        detection["sequence_text"] = self.encoder.encode_text(candles)
        detection["sequence_summary"] = self.encoder.encode_summary(candles)
        detection["detection_id"] = self._detections_total

        # Features snapshot para persistência
        detection["features_snapshot"] = {
            "candles": candles[-self.window:],
            "summary": detection.get("sequence_summary", {}),
        }

        logger.info(
            f"🎯 [{self._detections_total}] Pattern: {detection['pattern_type']} | "
            f"Signal: {detection.get('signal')} | "
            f"Confidence: {detection.get('confidence', 'N/A')} | "
            f"Asset: {self.asset}"
        )

        # Persiste no banco se session fornecida
        if session is not None:
            self._persist_detection(session, detection)

        return detection

    def _persist_detection(self, session: AsyncSession, detection: dict):
        """Persiste padrão detectado no banco via repositório (fire-and-forget async)."""
        import asyncio

        async def _do_persist():
            try:
                pattern_data = {
                    "pattern_type": detection.get("pattern_type", "unknown"),
                    "asset": self.asset,
                    "detected_at": datetime.now(UTC),
                    "features": detection.get("features_snapshot"),
                    "continuation_rate": detection.get("historical_probability", {}).get("probability", 0),
                    "strength": detection.get("confidence", 0),
                    "frequency": 1,
                    "confirmed": False,
                }
                await insert_pattern(session, pattern_data)
            except Exception as e:
                logger.error(f"❌ Failed to persist pattern: {e}")

        asyncio.create_task(_do_persist())

    def stats(self) -> dict:
        return {
            "asset": self.asset,
            "window": self.window,
            "detections_total": self._detections_total,
            "probability_summary": self.probability.summary(),
        }

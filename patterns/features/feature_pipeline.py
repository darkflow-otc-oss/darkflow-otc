"""
DARKFLOW OTC — Feature Pipeline
Integra banco de dados com extração de features e encoding.
Pipeline: DB candles → CandleFeatures → SequenceEncoder → vector/text/summary
"""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.postgres.repositories import get_latest_candles
from patterns.features.candle_features import CandleFeatureExtractor, CandleFeatures
from patterns.features.sequence_encoder import SequenceEncoder

logger = logging.getLogger("darkflow.features.pipeline")


class FeaturePipeline:
    """
    Pipeline completo de features:
    1. Busca últimos N candles do banco
    2. Extrai features por candle
    3. Encoda sequência em vetor + texto + resumo
    """

    def __init__(self, window: int = 5):
        self.window = window
        self.extractor = CandleFeatureExtractor()
        self.encoder = SequenceEncoder(window=window)

    async def run(
        self,
        session: AsyncSession,
        asset: str,
        timeframe: int = 60,
        limit: int | None = None,
    ) -> dict:
        """
        Executa o pipeline completo para um ativo.

        Returns:
            dict com:
                - candles: lista de dicionários OHLC brutos
                - features: lista de CandleFeatures (dataclasses)
                - vector: vetor numérico plano (list[float])
                - text: descrição textual da sequência
                - summary: dicionário com resumo agregado
                - asset: nome do ativo
                - window: tamanho da janela
        """
        n = limit or self.window
        logger.info(f"🔬 FeaturePipeline: {asset} tf={timeframe}s window={self.window}")

        raw_candles = await get_latest_candles(
            session, asset=asset, timeframe=timeframe, limit=n
        )

        candles_dicts = [c.to_dict() for c in raw_candles]
        candles_dicts.reverse()  # mais antigo → mais recente

        if len(candles_dicts) < self.window:
            logger.warning(
                f"⚠️  Only {len(candles_dicts)} candles available "
                f"(need {self.window}) — window shrunk."
            )

        features = self.extractor.extract_sequence(candles_dicts)
        vector = self.encoder.encode_vector(candles_dicts)
        text = self.encoder.encode_text(candles_dicts)
        summary = self.encoder.encode_summary(candles_dicts)

        logger.info(
            f"✅ FeaturePipeline done: {len(features)} features, "
            f"vector={len(vector or [])}d, consensus={summary.get('consensus', 'N/A')}"
        )

        return {
            "asset": asset,
            "window": self.window,
            "candles": candles_dicts,
            "features": [f.to_dict() for f in features],
            "vector": vector,
            "text": text,
            "summary": summary,
        }

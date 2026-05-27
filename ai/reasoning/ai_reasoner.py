"""
DARKFLOW OTC — AI Reasoner
Usa LLM para raciocinar sobre padrões OTC detectados.
Responsabilidade: não gerar sinais — classificar, resumir e contextualizar.

Modelos DeepSeek configurados:
- deepseek-chat   (V4 Pro): chamadas normais de classificação e JSON output
- deepseek-reasoner (R1)  : analyze_batch() e análises com 3+ padrões
- Fallback: deepseek-chat com prompt simplificado se qualquer modelo falhar

API: base_url = https://api.deepseek.com (OpenAI-compatible)
"""

import json
import logging
from datetime import datetime, UTC
from typing import Optional
from openai import AsyncOpenAI
from config.settings import settings

logger = logging.getLogger("darkflow.ai.reasoner")

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

SYSTEM_PROMPT = """
You are DARKFLOW OTC Analyst — a specialized AI for behavioral analysis of OTC binary options feed.

Your role:
- Analyze detected candle patterns and sequences
- Classify behavioral context (trending, compressed, trapping, exhausting)
- Identify if the setup looks like a liquidity trap or genuine momentum
- Rate pattern confidence based on features provided
- Never invent data — only analyze what is given

Output format: always respond in valid JSON with these fields:
{
  "context": "brief behavioral context description",
  "pattern_quality": "HIGH | MEDIUM | LOW",
  "trap_risk": "HIGH | MEDIUM | LOW",
  "momentum_quality": "HIGH | MEDIUM | LOW",
  "reasoning": "2-3 sentence analysis",
  "recommendation": "PROCEED | CAUTION | SKIP",
  "confidence_adjustment": float between -0.15 and +0.15
}
"""

FALLBACK_PROMPT = """
You are a trading pattern analyst. Analyze this OTC pattern detection briefly.

Respond only in JSON:
{
  "context": "short context",
  "pattern_quality": "HIGH | MEDIUM | LOW",
  "trap_risk": "HIGH | MEDIUM | LOW",
  "momentum_quality": "HIGH | MEDIUM | LOW",
  "reasoning": "1-2 sentences",
  "recommendation": "PROCEED | CAUTION | SKIP",
  "confidence_adjustment": 0.0
}
"""


class AIReasoner:
    """
    Raciocina sobre detecções usando modelos DeepSeek.
    Dual-client: deepseek-chat (normal) + deepseek-reasoner (complexo).
    Não gera sinais — enriquece detecções com contexto comportamental.
    """

    def __init__(self):
        self._api_key = settings.deepseek_api_key
        self._main_model = settings.deepseek_model_main
        self._reasoner_model = settings.deepseek_model_reasoner

        self._main_client = None
        self._reasoner_client = None
        self._call_count = 0

        if self._api_key:
            self._main_client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=DEEPSEEK_BASE_URL,
                timeout=15.0,
            )
            self._reasoner_client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=DEEPSEEK_BASE_URL,
                timeout=45.0,
            )

    @property
    def enabled(self) -> bool:
        return self._api_key != ""

    async def analyze(self, detection: dict, candle_sequence_text: str) -> Optional[dict]:
        """
        Analisa uma detecção e retorna raciocínio estruturado.
        Usa deepseek-chat (modelo principal, 15s timeout).
        detection: output de qualquer detector
        candle_sequence_text: output de SequenceEncoder.encode_text()
        """
        if not self.enabled:
            logger.warning("⚠️  DeepSeek key not set — skipping AI reasoning.")
            return None

        prompt = self._build_prompt(detection, candle_sequence_text)

        try:
            self._call_count += 1
            response = await self._main_client.chat.completions.create(
                model=self._main_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=400,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            reasoning = json.loads(raw)
            reasoning["analyzed_at"] = datetime.now(UTC).isoformat()
            reasoning["model"] = self._main_model
            reasoning["call_count"] = self._call_count

            logger.info(
                f"🧠 AI Reasoning [{self._main_model}]: {reasoning.get('recommendation')} | "
                f"quality={reasoning.get('pattern_quality')} | "
                f"trap_risk={reasoning.get('trap_risk')}"
            )
            return reasoning

        except Exception as e:
            logger.error(f"❌ Main model error: {e} — falling back to simplified prompt")
            return await self._fallback_analyze(detection, candle_sequence_text)

    async def batch_analyze(self, detections: list[dict], texts: list[str]) -> list[dict]:
        """
        Analisa múltiplas detecções.
        Usa deepseek-reasoner (45s timeout) para 3+ padrões.
        """
        if not self.enabled:
            logger.warning("⚠️  DeepSeek key not set — skipping batch AI reasoning.")
            return []

        n = len(detections)
        use_reasoner = n >= 3

        if use_reasoner:
            logger.info(f"🧠 Batch analyze: {n} detections → using REASONER model")
            return await self._batch_with_reasoner(detections, texts)
        else:
            results = []
            for detection, text in zip(detections, texts):
                result = await self.analyze(detection, text)
                if result:
                    results.append(result)
            return results

    async def _batch_with_reasoner(self, detections: list[dict], texts: list[str]) -> list[dict]:
        """Usa deepseek-reasoner para batch com múltiplos padrões."""
        combined_prompt = self._build_batch_prompt(detections, texts)

        try:
            self._call_count += 1
            response = await self._reasoner_client.chat.completions.create(
                model=self._reasoner_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": combined_prompt},
                ],
                temperature=0.2,
                max_tokens=1200,
            )

            raw = response.choices[0].message.content
            batch = json.loads(raw)

            results = []
            if isinstance(batch, dict) and "analyses" in batch:
                analyses = batch["analyses"]
            elif isinstance(batch, list):
                analyses = batch
            else:
                analyses = [batch]

            for item in analyses:
                item["analyzed_at"] = datetime.now(UTC).isoformat()
                item["model"] = self._reasoner_model
                item["call_count"] = self._call_count
                results.append(item)

            logger.info(
                f"🧠 Batch Reasoning [{self._reasoner_model}]: "
                f"{len(results)}/{len(detections)} analyzed"
            )
            return results

        except Exception as e:
            logger.error(f"❌ Reasoner model error: {e} — falling back to main model")
            return await self._fallback_batch(detections, texts)

    async def _fallback_analyze(self, detection: dict, candle_sequence_text: str) -> Optional[dict]:
        """Fallback: deepseek-chat com prompt simplificado."""
        prompt = f"""
DETECTED PATTERN:
{json.dumps(detection, indent=2)}

CANDLE SEQUENCE:
{candle_sequence_text}

Analyze briefly.
"""
        try:
            self._call_count += 1
            response = await self._main_client.chat.completions.create(
                model=self._main_model,
                messages=[
                    {"role": "system", "content": FALLBACK_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=300,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            reasoning = json.loads(raw)
            reasoning["analyzed_at"] = datetime.now(UTC).isoformat()
            reasoning["model"] = f"{self._main_model} (fallback)"
            reasoning["call_count"] = self._call_count
            reasoning["fallback"] = True

            logger.info(f"🧠 AI Reasoning [FALLBACK]: {reasoning.get('recommendation')}")
            return reasoning

        except Exception as e:
            logger.error(f"❌ Fallback also failed: {e}")
            return None

    async def _fallback_batch(self, detections: list[dict], texts: list[str]) -> list[dict]:
        """Fallback batch: usa deepseek-chat individualmente para cada detecção."""
        logger.info("🔄 Retrying batch with main model (sequential)...")
        results = []
        for detection, text in zip(detections, texts):
            result = await self._fallback_analyze(detection, text)
            if result:
                results.append(result)
        return results

    def _build_prompt(self, detection: dict, sequence_text: str) -> str:
        return f"""
DETECTED PATTERN:
{json.dumps(detection, indent=2)}

CANDLE SEQUENCE:
{sequence_text}

Analyze this OTC pattern detection. Focus on:
1. Is this a genuine setup or a liquidity trap?
2. What is the behavioral quality of this sequence?
3. Should the trader proceed, be cautious, or skip this setup?

Respond only in JSON as specified.
"""

    def _build_batch_prompt(self, detections: list[dict], texts: list[str]) -> str:
        items = []
        for i, (det, txt) in enumerate(zip(detections, texts)):
            items.append(f"""
─── Pattern {i + 1} ───
DETECTED:
{json.dumps(det, indent=2)}

SEQUENCE:
{txt}
""")
        joined = "\n".join(items)

        return f"""
Analyze these {len(detections)} OTC pattern detections collectively.

Focus on:
1. Is there a consensus across patterns?
2. Do patterns reinforce or contradict each other?
3. Which pattern has the highest conviction?

Return a JSON object with an "analyses" array — one analysis object per pattern:
{{
  "analyses": [
    {{
      "context": "...",
      "pattern_quality": "HIGH | MEDIUM | LOW",
      "trap_risk": "HIGH | MEDIUM | LOW",
      "momentum_quality": "HIGH | MEDIUM | LOW",
      "reasoning": "...",
      "recommendation": "PROCEED | CAUTION | SKIP",
      "confidence_adjustment": 0.0
    }}
  ]
}}

PATTERNS:
{joined}
"""

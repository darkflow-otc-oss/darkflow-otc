# 🔥 DARKFLOW OTC AI ENGINE

> Plataforma proprietária de captura, observabilidade e inteligência comportamental do feed OTC.

---

## Filosofia

O sistema **não tenta prever candles magicamente**.

O sistema tenta:
- Medir comportamento recorrente
- Mapear repetição estatística
- Detectar assinaturas do feed OTC
- Identificar liquidity traps
- Construir probabilidades baseadas em dados reais

---

## Arquitetura

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Capture | Python + Playwright |
| API | FastAPI + Uvicorn |
| Database | PostgreSQL + SQLAlchemy |
| Cache | Redis |
| Vector DB | ChromaDB + Qdrant |
| AI | OpenAI GPT-4o |
| Frontend | React + Next.js |

---

## Fases

| Fase | Status | Descrição |
|------|--------|-----------|
| 1 | ✅ | Capture Layer (Browser + WebSocket + Recorder) |
| 2 | ✅ | Database (PostgreSQL schema + ORM) |
| 3 | ✅ | Feature Engine (CandleFeatures + SequenceEncoder) |
| 4 | ✅ | Pattern Detectors (Continuation / Reversal / FakeBreak) |
| 5 | ✅ | Clustering (ChromaDB + Qdrant) |
| 6 | ✅ | Probability Engine |
| 7 | ✅ | AI Reasoning (GPT-4o) |
| 8 | ✅ | Dashboard (React + Next.js) |

---

## Dashboard

Acesse **http://localhost:3000** após subir os serviços.

```bash
# Modo desenvolvimento
cd dashboard && npm run dev

# Modo produção
cd dashboard && npm run build && npm start
```

Widgets disponíveis:
| Widget | Descrição |
|--------|-----------|
| OTC Intelligence | Output do OTCBehaviorModel: padrão, win rate, recomendação (ENTER/WATCH/SKIP) |
| Pattern Similarity | Top 5 padrões similares do cluster engine com barra de similaridade |
| Consensus Trap | Indicador de armadilha de consenso com gauge visual (0–100%) |
| Live Feed | Últimos 20 ticks via WebSocket em tabela rolante |

---

## Início Rápido

```bash
# 1. Instalar dependências
pip install -r requirements.txt
playwright install chromium

# 2. Configurar variáveis
cp .env.example .env
# Editar .env com suas credenciais

# 3. Subir infraestrutura
docker-compose up -d

# 4. Iniciar API
python main.py

# 5. Iniciar captura OTC
python capture/orchestrator.py
```

---

## Endpoints Principais

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/health` | Status dos módulos |
| GET | `/api/candles/` | Listar candles por asset |
| GET | `/api/candles/latest` | Último candle |
| POST | `/api/patterns/detect` | Detectar padrão em janela |
| POST | `/api/patterns/record-outcome` | Registrar WIN/LOSS |
| GET | `/api/patterns/probability` | Consultar probabilidade |
| GET | `/api/patterns/stats` | Estatísticas do pipeline |
| WS | `/ws/realtime` | Feed em tempo real |

---

## Padrões Detectados

| Padrão | Tipo | Confidence Base |
|--------|------|----------------|
| `liquidity_hunt` | FakeBreak | 0.74 |
| `spike_reversal` | FakeBreak | 0.71 |
| `consensus_trap` | FakeBreak | 0.68 |
| `exhaustion_reversal` | Reversal | — |
| `wick_rejection` | Reversal | — |
| `doji_reversal` | Reversal | — |
| `strong_momentum` | Continuation | — |
| `pullback_continuation` | Continuation | — |
| `compression_breakout` | Continuation | — |

---

> **DARKFLOW OTC ENGINE** — Laboratório de engenharia quantitativa OTC.

-- DARKFLOW OTC AI ENGINE — PostgreSQL Schema

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Candles ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS candles (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    asset       VARCHAR(50) NOT NULL,
    timeframe   INTEGER NOT NULL DEFAULT 60,
    ts          TIMESTAMPTZ NOT NULL,
    open        NUMERIC(18, 8) NOT NULL,
    high        NUMERIC(18, 8) NOT NULL,
    low         NUMERIC(18, 8) NOT NULL,
    close       NUMERIC(18, 8) NOT NULL,
    volume      NUMERIC(18, 8) DEFAULT 0,
    source      VARCHAR(30) DEFAULT 'websocket',
    session_id  VARCHAR(50),
    raw         JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_candles_asset_ts ON candles(asset, ts DESC);
CREATE INDEX IF NOT EXISTS idx_candles_ts ON candles(ts DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_candles_unique ON candles(asset, timeframe, ts);

-- ── Patterns ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patterns (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pattern_type        VARCHAR(80) NOT NULL,
    asset               VARCHAR(50) NOT NULL,
    detected_at         TIMESTAMPTZ NOT NULL,
    candle_ids          UUID[],
    features            JSONB,
    continuation_rate   NUMERIC(5,4) DEFAULT 0,
    reversal_rate       NUMERIC(5,4) DEFAULT 0,
    false_break_rate    NUMERIC(5,4) DEFAULT 0,
    strength            NUMERIC(5,4) DEFAULT 0,
    frequency           INTEGER DEFAULT 1,
    cluster_id          VARCHAR(50),
    vector_id           VARCHAR(100),
    confirmed           BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_patterns_type ON patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_patterns_asset ON patterns(asset);
CREATE INDEX IF NOT EXISTS idx_patterns_detected ON patterns(detected_at DESC);

-- ── Sessions ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS capture_sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      VARCHAR(50) UNIQUE NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    asset           VARCHAR(50),
    messages_total  INTEGER DEFAULT 0,
    candles_total   INTEGER DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'active',
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Probabilities ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS probabilities (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pattern_type    VARCHAR(80) NOT NULL,
    asset           VARCHAR(50) NOT NULL,
    direction       VARCHAR(20) NOT NULL,
    probability     NUMERIC(5,4) NOT NULL,
    sample_size     INTEGER NOT NULL,
    computed_at     TIMESTAMPTZ DEFAULT NOW(),
    valid_until     TIMESTAMPTZ,
    metadata        JSONB
);

CREATE INDEX IF NOT EXISTS idx_prob_pattern ON probabilities(pattern_type, asset);

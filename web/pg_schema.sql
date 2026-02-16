-- Auto Report - PostgreSQL Schema
-- Schema: autoreport (within dados_turbo database)

CREATE SCHEMA IF NOT EXISTS autoreport;

-- ============================================================
-- users (migrated from SQLite)
-- ============================================================
CREATE TABLE IF NOT EXISTS autoreport.users (
    id              SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- jobs (migrated from SQLite)
-- ============================================================
CREATE TABLE IF NOT EXISTS autoreport.jobs (
    id              TEXT PRIMARY KEY,
    freq            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDENTE',
    total           INTEGER DEFAULT 0,
    completed       INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    started_by      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

-- ============================================================
-- job_results (migrated from SQLite)
-- ============================================================
CREATE TABLE IF NOT EXISTS autoreport.job_results (
    id              SERIAL PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES autoreport.jobs(id),
    client_name     TEXT NOT NULL,
    category        TEXT,
    status          TEXT NOT NULL,
    error_detail    TEXT,
    presentation_url TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_job_results_job_id
    ON autoreport.job_results(job_id);
CREATE INDEX IF NOT EXISTS idx_job_results_client
    ON autoreport.job_results(client_name);

-- ============================================================
-- clientes (NEW - synced from Google Sheets)
-- ============================================================
CREATE TABLE IF NOT EXISTS autoreport.clientes (
    id              SERIAL PRIMARY KEY,
    nome            TEXT UNIQUE NOT NULL,
    categoria       TEXT,
    gestor          TEXT,
    squad           TEXT,
    painel_url      TEXT,
    pasta_url       TEXT,
    id_google_ads   TEXT,
    id_meta_ads     TEXT,
    id_ga4          TEXT,
    status_auto     TEXT,
    ultima_geracao  TEXT,
    extras          JSONB DEFAULT '{}'::jsonb,
    synced_at       TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_clientes_gestor
    ON autoreport.clientes(gestor);
CREATE INDEX IF NOT EXISTS idx_clientes_categoria
    ON autoreport.clientes(categoria);

-- ============================================================
-- metricas (NEW - metric snapshots per client/period)
-- ============================================================
CREATE TABLE IF NOT EXISTS autoreport.metricas (
    id              SERIAL PRIMARY KEY,
    cliente_nome    TEXT NOT NULL REFERENCES autoreport.clientes(nome),
    categoria       TEXT NOT NULL,
    freq            TEXT NOT NULL,
    periodo_inicio  DATE NOT NULL,
    periodo_fim     DATE NOT NULL,
    -- Core metrics
    faturamento     NUMERIC(14,2),
    investimento    NUMERIC(14,2),
    roas            NUMERIC(8,4),
    vendas          INTEGER,
    cpa             NUMERIC(10,2),
    -- Platform-specific
    inv_google      NUMERIC(14,2),
    fat_google      NUMERIC(14,2),
    inv_meta        NUMERIC(14,2),
    fat_meta        NUMERIC(14,2),
    vendas_google   INTEGER,
    vendas_meta     INTEGER,
    roas_google     NUMERIC(8,4),
    roas_meta       NUMERIC(8,4),
    cpa_google      NUMERIC(10,2),
    cpa_meta        NUMERIC(10,2),
    -- GA4
    sessoes         INTEGER,
    -- Full dados dict for extensibility
    dados_raw       JSONB DEFAULT '{}'::jsonb,
    -- Tracking
    job_id          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_metricas_cliente
    ON autoreport.metricas(cliente_nome);
CREATE INDEX IF NOT EXISTS idx_metricas_periodo
    ON autoreport.metricas(periodo_inicio, periodo_fim);
CREATE UNIQUE INDEX IF NOT EXISTS idx_metricas_unique
    ON autoreport.metricas(cliente_nome, freq, periodo_inicio, periodo_fim);

-- =============================================================
-- PDQ-Flow v1.0 — Schema do Banco de Dados
-- PostgreSQL 16 + PostGIS 3.4
-- =============================================================

-- Habilita a extensão PostGIS (geometrias, funções espaciais)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Schema dedicado ao projeto
CREATE SCHEMA IF NOT EXISTS pdqflow;

-- =============================================================
-- TABELA PRINCIPAL: focos de incêndio
-- =============================================================
CREATE TABLE IF NOT EXISTS pdqflow.focos (
    id                    UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    id_inpe               TEXT        UNIQUE NOT NULL,          -- UUID original do INPE
    data_hora_gmt         TIMESTAMPTZ NOT NULL,
    satelite              TEXT,
    municipio             TEXT,
    estado                TEXT,
    pais                  TEXT        DEFAULT 'Brasil',
    municipio_id          BIGINT,
    estado_id             INTEGER,
    numero_dias_sem_chuva INTEGER,
    precipitacao          NUMERIC(8,2),
    risco_fogo            NUMERIC(4,2),                         -- 0.0 a 1.0
    bioma                 TEXT,
    frp                   NUMERIC(8,1),                         -- Fire Radiative Power (MW)
    geom                  GEOMETRY(Point, 4326) NOT NULL,       -- WGS84 — núcleo PostGIS
    inserido_em           TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================
-- ÍNDICES
-- =============================================================

-- Índice espacial GiST — acelera ST_Within, ST_DWithin, ST_Intersects
CREATE INDEX IF NOT EXISTS idx_focos_geom
    ON pdqflow.focos USING GIST (geom);

-- Índice temporal — consultas por período
CREATE INDEX IF NOT EXISTS idx_focos_data
    ON pdqflow.focos (data_hora_gmt);

-- Índices analíticos
CREATE INDEX IF NOT EXISTS idx_focos_bioma   ON pdqflow.focos (bioma);
CREATE INDEX IF NOT EXISTS idx_focos_estado  ON pdqflow.focos (estado);
CREATE INDEX IF NOT EXISTS idx_focos_risco   ON pdqflow.focos (risco_fogo);
CREATE INDEX IF NOT EXISTS idx_focos_satelite ON pdqflow.focos (satelite);

-- =============================================================
-- VIEW: resumo por bioma
-- Demonstra GROUP BY com dados geoespaciais + PostGIS
-- =============================================================
CREATE OR REPLACE VIEW pdqflow.vw_focos_por_bioma AS
SELECT
    bioma,
    COUNT(*)                          AS total_focos,
    ROUND(AVG(risco_fogo)::NUMERIC, 3) AS risco_medio,
    ROUND(AVG(frp)::NUMERIC, 1)        AS frp_medio_mw,
    ROUND(MAX(frp)::NUMERIC, 1)        AS frp_maximo_mw,
    AVG(numero_dias_sem_chuva)::INT    AS media_dias_sem_chuva,
    -- Centróide geográfico do bioma a partir dos focos (PostGIS)
    ST_AsGeoJSON(
        ST_Centroid(ST_Collect(geom))
    )::JSON                            AS centroide_geojson
FROM pdqflow.focos
GROUP BY bioma
ORDER BY total_focos DESC;

-- =============================================================
-- VIEW: resumo por estado
-- =============================================================
CREATE OR REPLACE VIEW pdqflow.vw_focos_por_estado AS
SELECT
    estado,
    COUNT(*)                           AS total_focos,
    ROUND(AVG(risco_fogo)::NUMERIC, 3) AS risco_medio,
    ROUND(AVG(frp)::NUMERIC, 1)        AS frp_medio_mw,
    COUNT(*) FILTER (WHERE risco_fogo >= 0.8) AS focos_alto_risco,
    -- Envelope geográfico (bounding box) do estado via focos (PostGIS)
    ST_AsGeoJSON(
        ST_Envelope(ST_Collect(geom))
    )::JSON                            AS envelope_geojson
FROM pdqflow.focos
GROUP BY estado
ORDER BY total_focos DESC;

-- =============================================================
-- VIEW: focos de alto risco (risco_fogo >= 0.8)
-- =============================================================
CREATE OR REPLACE VIEW pdqflow.vw_focos_alto_risco AS
SELECT
    id_inpe,
    data_hora_gmt,
    municipio,
    estado,
    bioma,
    risco_fogo,
    frp,
    numero_dias_sem_chuva,
    ST_X(geom) AS longitude,
    ST_Y(geom) AS latitude,
    ST_AsGeoJSON(geom)::JSON AS geojson
FROM pdqflow.focos
WHERE risco_fogo >= 0.8
ORDER BY risco_fogo DESC, frp DESC;

-- =============================================================
-- VIEW: série temporal diária de focos
-- =============================================================
CREATE OR REPLACE VIEW pdqflow.vw_serie_temporal AS
SELECT
    DATE(data_hora_gmt AT TIME ZONE 'America/Sao_Paulo') AS data,
    COUNT(*)                          AS total_focos,
    COUNT(DISTINCT estado)            AS estados_afetados,
    ROUND(AVG(risco_fogo)::NUMERIC, 3) AS risco_medio,
    ROUND(SUM(frp)::NUMERIC, 0)        AS frp_total_mw
FROM pdqflow.focos
GROUP BY DATE(data_hora_gmt AT TIME ZONE 'America/Sao_Paulo')
ORDER BY data DESC;

-- =============================================================
-- VIEW: log de carga ETL
-- =============================================================
CREATE TABLE IF NOT EXISTS pdqflow.log_carga (
    id            SERIAL      PRIMARY KEY,
    arquivo       TEXT        NOT NULL,
    total_linhas  INTEGER,
    inseridos     INTEGER,
    duplicados    INTEGER,
    erros         INTEGER     DEFAULT 0,
    iniciado_em   TIMESTAMPTZ DEFAULT NOW(),
    finalizado_em TIMESTAMPTZ,
    status        TEXT        DEFAULT 'em_andamento'   -- em_andamento | sucesso | erro
);

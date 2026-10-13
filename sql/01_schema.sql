-- =====================================================================
-- Esquema del pipeline SECOP II
--   raw  : copia fiel de lo que llega de la API (zona de aterrizaje)
--   dw   : modelo dimensional limpio (estrella) para análisis
--   etl  : control del pipeline (ejecuciones, marca de agua, rechazos)
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS dw;
CREATE SCHEMA IF NOT EXISTS etl;

-- ---------------------------------------------------------------- etl
CREATE TABLE IF NOT EXISTS etl.ejecuciones (
    ejecucion_id     BIGSERIAL PRIMARY KEY,
    inicio           TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin              TIMESTAMPTZ,
    estado           TEXT NOT NULL DEFAULT 'en_curso'
                     CHECK (estado IN ('en_curso', 'ok', 'error')),
    modo             TEXT NOT NULL CHECK (modo IN ('completa', 'incremental')),
    filas_extraidas  INT DEFAULT 0,
    filas_cargadas   INT DEFAULT 0,
    filas_rechazadas INT DEFAULT 0,
    -- Fecha de firma más reciente cargada. La siguiente ejecución
    -- incremental reprocesa desde (marca_agua - ventana) en adelante.
    marca_agua       DATE,
    error            TEXT
);

CREATE TABLE IF NOT EXISTS etl.rechazos (
    rechazo_id    BIGSERIAL PRIMARY KEY,
    ejecucion_id  BIGINT REFERENCES etl.ejecuciones(ejecucion_id),
    id_contrato   TEXT,
    motivo        TEXT NOT NULL,
    payload       JSONB,
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- raw
CREATE TABLE IF NOT EXISTS raw.secop_contratos (
    id_contrato   TEXT PRIMARY KEY,
    payload       JSONB NOT NULL,
    ejecucion_id  BIGINT REFERENCES etl.ejecuciones(ejecucion_id),
    extraido_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------- dw
CREATE TABLE IF NOT EXISTS dw.dim_entidad (
    entidad_id    SERIAL PRIMARY KEY,
    nit           TEXT NOT NULL,
    nombre        TEXT NOT NULL,
    departamento  TEXT,
    ciudad        TEXT,
    orden         TEXT,
    sector        TEXT,
    rama          TEXT,
    UNIQUE (nit, nombre)
);

CREATE TABLE IF NOT EXISTS dw.dim_proveedor (
    proveedor_id  SERIAL PRIMARY KEY,
    tipo_doc      TEXT NOT NULL,
    documento     TEXT NOT NULL,
    nombre        TEXT NOT NULL,
    es_pyme       BOOLEAN,
    UNIQUE (tipo_doc, documento)
);

CREATE TABLE IF NOT EXISTS dw.fact_contrato (
    id_contrato           TEXT PRIMARY KEY,
    entidad_id            INT NOT NULL REFERENCES dw.dim_entidad(entidad_id),
    proveedor_id          INT REFERENCES dw.dim_proveedor(proveedor_id),
    proceso_de_compra     TEXT,
    referencia            TEXT,
    estado                TEXT,
    tipo_contrato         TEXT,
    modalidad             TEXT,
    unspsc_codigo         TEXT,
    unspsc_segmento       TEXT,
    objeto                TEXT,
    fecha_firma           DATE,
    fecha_inicio          DATE,
    fecha_fin             DATE,
    duracion_dias         INT,
    dias_adicionados      INT,
    valor_contrato        NUMERIC(20, 2) NOT NULL CHECK (valor_contrato >= 0),
    valor_facturado       NUMERIC(20, 2),
    valor_pagado          NUMERIC(20, 2),
    valor_pendiente_ejec  NUMERIC(20, 2),
    origen_recursos       TEXT,
    destino_gasto         TEXT,
    url_proceso           TEXT,
    ultima_actualizacion  TIMESTAMP,          -- viene vacío en muchos contratos
    cargado_en            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_fact_entidad   ON dw.fact_contrato (entidad_id);
CREATE INDEX IF NOT EXISTS ix_fact_proveedor ON dw.fact_contrato (proveedor_id);
CREATE INDEX IF NOT EXISTS ix_fact_firma     ON dw.fact_contrato (fecha_firma);

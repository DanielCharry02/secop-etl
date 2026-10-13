"""L de ETL: cargar en PostgreSQL.

Patrón usado (el estándar en la industria):
  1. COPY de los datos limpios a una tabla temporal de staging (rápido).
  2. Desde staging, INSERT ... ON CONFLICT (UPSERT) hacia las tablas
     finales, con SQL basado en conjuntos (no fila por fila).

UPSERT = "inserta si no existe, actualiza si ya existe". Gracias a eso
el pipeline es IDEMPOTENTE: correrlo dos veces con los mismos datos deja
la base exactamente igual. Es la propiedad más importante de un ETL.
"""
from datetime import date

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

COLUMNAS_STG = [
    ("id_contrato", "TEXT"),
    ("entidad_nit", "TEXT"), ("entidad_nombre", "TEXT"),
    ("entidad_departamento", "TEXT"), ("entidad_ciudad", "TEXT"),
    ("entidad_orden", "TEXT"), ("entidad_sector", "TEXT"),
    ("entidad_rama", "TEXT"),
    ("proveedor_tipo_doc", "TEXT"), ("proveedor_documento", "TEXT"),
    ("proveedor_nombre", "TEXT"), ("proveedor_es_pyme", "BOOLEAN"),
    ("proceso_de_compra", "TEXT"), ("referencia", "TEXT"), ("estado", "TEXT"),
    ("tipo_contrato", "TEXT"), ("modalidad", "TEXT"),
    ("unspsc_codigo", "TEXT"), ("unspsc_segmento", "TEXT"), ("objeto", "TEXT"),
    ("fecha_firma", "DATE"), ("fecha_inicio", "DATE"), ("fecha_fin", "DATE"),
    ("duracion_dias", "INT"), ("dias_adicionados", "INT"),
    ("valor_contrato", "NUMERIC"), ("valor_facturado", "NUMERIC"),
    ("valor_pagado", "NUMERIC"), ("valor_pendiente_ejec", "NUMERIC"),
    ("origen_recursos", "TEXT"), ("destino_gasto", "TEXT"),
    ("url_proceso", "TEXT"), ("ultima_actualizacion", "TIMESTAMP"),
]

SQL_DIM_ENTIDAD = """
INSERT INTO dw.dim_entidad (nit, nombre, departamento, ciudad, orden, sector, rama)
SELECT DISTINCT ON (entidad_nit, entidad_nombre)
       entidad_nit, entidad_nombre, entidad_departamento, entidad_ciudad,
       entidad_orden, entidad_sector, entidad_rama
FROM stg_contratos
ORDER BY entidad_nit, entidad_nombre, ultima_actualizacion DESC NULLS LAST
ON CONFLICT (nit, nombre) DO UPDATE SET
    departamento = EXCLUDED.departamento,
    ciudad       = EXCLUDED.ciudad,
    orden        = EXCLUDED.orden,
    sector       = EXCLUDED.sector,
    rama         = EXCLUDED.rama;
"""

SQL_DIM_PROVEEDOR = """
INSERT INTO dw.dim_proveedor (tipo_doc, documento, nombre, es_pyme)
SELECT DISTINCT ON (tipo_doc, proveedor_documento)
       tipo_doc, proveedor_documento, proveedor_nombre, proveedor_es_pyme
FROM (SELECT *, COALESCE(proveedor_tipo_doc, 'Desconocido') AS tipo_doc
      FROM stg_contratos) s
WHERE proveedor_documento IS NOT NULL AND proveedor_nombre IS NOT NULL
ORDER BY tipo_doc, proveedor_documento, ultima_actualizacion DESC NULLS LAST
ON CONFLICT (tipo_doc, documento) DO UPDATE SET
    nombre  = EXCLUDED.nombre,
    es_pyme = EXCLUDED.es_pyme;
"""

SQL_FACT = """
INSERT INTO dw.fact_contrato (
    id_contrato, entidad_id, proveedor_id, proceso_de_compra, referencia,
    estado, tipo_contrato, modalidad, unspsc_codigo, unspsc_segmento, objeto,
    fecha_firma, fecha_inicio, fecha_fin, duracion_dias, dias_adicionados,
    valor_contrato, valor_facturado, valor_pagado, valor_pendiente_ejec,
    origen_recursos, destino_gasto, url_proceso, ultima_actualizacion)
SELECT s.id_contrato, e.entidad_id, p.proveedor_id, s.proceso_de_compra,
       s.referencia, s.estado, s.tipo_contrato, s.modalidad, s.unspsc_codigo,
       s.unspsc_segmento, s.objeto, s.fecha_firma, s.fecha_inicio, s.fecha_fin,
       s.duracion_dias, s.dias_adicionados, s.valor_contrato, s.valor_facturado,
       s.valor_pagado, s.valor_pendiente_ejec, s.origen_recursos,
       s.destino_gasto, s.url_proceso, s.ultima_actualizacion
FROM stg_contratos s
JOIN dw.dim_entidad e
  ON e.nit = s.entidad_nit AND e.nombre = s.entidad_nombre
LEFT JOIN dw.dim_proveedor p
  ON p.tipo_doc = COALESCE(s.proveedor_tipo_doc, 'Desconocido')
 AND p.documento = s.proveedor_documento
ON CONFLICT (id_contrato) DO UPDATE SET
    entidad_id           = EXCLUDED.entidad_id,
    proveedor_id         = EXCLUDED.proveedor_id,
    estado               = EXCLUDED.estado,
    modalidad            = EXCLUDED.modalidad,
    fecha_inicio         = EXCLUDED.fecha_inicio,
    fecha_fin            = EXCLUDED.fecha_fin,
    duracion_dias        = EXCLUDED.duracion_dias,
    dias_adicionados     = EXCLUDED.dias_adicionados,
    valor_contrato       = EXCLUDED.valor_contrato,
    valor_facturado      = EXCLUDED.valor_facturado,
    valor_pagado         = EXCLUDED.valor_pagado,
    valor_pendiente_ejec = EXCLUDED.valor_pendiente_ejec,
    ultima_actualizacion = EXCLUDED.ultima_actualizacion,
    cargado_en           = now();
-- Sin condición extra: SECOP publica cada día una foto completa y vigente,
-- así que lo que llega siempre es la versión correcta del contrato.
"""


def _a_python(valor):
    """pandas usa NaN/NaT/NA para nulos; PostgreSQL necesita None."""
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, pd.Timestamp):
        return valor.to_pydatetime()
    if hasattr(valor, "item"):          # numpy int64/float64 -> int/float
        return valor.item()
    return valor


# --------------------------------------------------- control de ejecuciones
def iniciar_ejecucion(conn: psycopg.Connection, modo: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO etl.ejecuciones (modo) VALUES (%s) RETURNING ejecucion_id",
            (modo,))
        ejecucion_id = cur.fetchone()[0]
    conn.commit()
    return ejecucion_id


def ultima_marca_agua(conn: psycopg.Connection) -> date | None:
    with conn.cursor() as cur:
        cur.execute("""SELECT marca_agua FROM etl.ejecuciones
                       WHERE estado = 'ok' AND marca_agua IS NOT NULL
                       ORDER BY ejecucion_id DESC LIMIT 1""")
        fila = cur.fetchone()
    return fila[0] if fila else None


def cerrar_ejecucion(conn: psycopg.Connection, ejecucion_id: int, estado: str,
                     extraidas: int, cargadas: int, rechazadas: int,
                     marca_agua: date | None, error: str | None = None):
    conn.rollback()  # por si quedó una transacción abortada
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE etl.ejecuciones
               SET fin = now(), estado = %s, filas_extraidas = %s,
                   filas_cargadas = %s, filas_rechazadas = %s,
                   marca_agua = %s, error = %s
             WHERE ejecucion_id = %s""",
            (estado, extraidas, cargadas, rechazadas, marca_agua, error,
             ejecucion_id))
    conn.commit()


# ------------------------------------------------------------------ carga
def cargar_lote(conn: psycopg.Connection, ejecucion_id: int,
                limpios: pd.DataFrame, rechazos: list[dict],
                crudos: list[dict]) -> int:
    """Carga un lote completo en UNA transacción: o entra todo o nada."""
    with conn.transaction(), conn.cursor() as cur:
        # Zona raw: guardamos lo que llegó, tal cual, para auditoría/reproceso
        cur.executemany(
            """INSERT INTO raw.secop_contratos (id_contrato, payload, ejecucion_id)
               VALUES (%s, %s, %s)
               ON CONFLICT (id_contrato) DO UPDATE
               SET payload = EXCLUDED.payload,
                   ejecucion_id = EXCLUDED.ejecucion_id,
                   extraido_en = now()""",
            [(r["id_contrato"], Jsonb(r), ejecucion_id)
             for r in crudos if r.get("id_contrato")])

        if rechazos:
            cur.executemany(
                """INSERT INTO etl.rechazos (ejecucion_id, id_contrato, motivo, payload)
                   VALUES (%s, %s, %s, %s)""",
                [(ejecucion_id, r["id_contrato"], r["motivo"], Jsonb(r["payload"]))
                 for r in rechazos])

        if limpios.empty:
            return 0

        definicion = ", ".join(f"{c} {t}" for c, t in COLUMNAS_STG)
        cur.execute(f"CREATE TEMP TABLE stg_contratos ({definicion}) ON COMMIT DROP")

        nombres = [c for c, _ in COLUMNAS_STG]
        with cur.copy(f"COPY stg_contratos ({', '.join(nombres)}) FROM STDIN") as copy:
            for fila in limpios[nombres].itertuples(index=False):
                copy.write_row([_a_python(v) for v in fila])

        cur.execute(SQL_DIM_ENTIDAD)
        cur.execute(SQL_DIM_PROVEEDOR)
        cur.execute(SQL_FACT)
        return cur.rowcount

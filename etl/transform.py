"""T de ETL: limpiar, tipar, validar y enriquecer los registros crudos.

Entra: lista de dicts tal cual vienen de la API (todo es texto).
Sale:  (DataFrame limpio, lista de rechazos con su motivo).
"""
import hashlib
import os

import pandas as pd

from etl.extract import COLUMNAS

# Valores que en SECOP significan "no hay dato"
NULOS = {"", "no definido", "no aplica", "n/a", "na", "null", "none"}

# Mapeo de columnas API -> nombres del modelo destino
RENOMBRAR = {
    "nit_entidad": "entidad_nit",
    "nombre_entidad": "entidad_nombre",
    "departamento": "entidad_departamento",
    "ciudad": "entidad_ciudad",
    "orden": "entidad_orden",
    "sector": "entidad_sector",
    "rama": "entidad_rama",
    "referencia_del_contrato": "referencia",
    "estado_contrato": "estado",
    "tipo_de_contrato": "tipo_contrato",
    "modalidad_de_contratacion": "modalidad",
    "objeto_del_contrato": "objeto",
    "fecha_de_firma": "fecha_firma",
    "fecha_de_inicio_del_contrato": "fecha_inicio",
    "fecha_de_fin_del_contrato": "fecha_fin",
    "tipodocproveedor": "proveedor_tipo_doc",
    "documento_proveedor": "proveedor_documento",
    "proveedor_adjudicado": "proveedor_nombre",
    "es_pyme": "proveedor_es_pyme",
    "valor_del_contrato": "valor_contrato",
    "valor_pendiente_de_ejecucion": "valor_pendiente_ejec",
    "origen_de_los_recursos": "origen_recursos",
}

COLUMNAS_TEXTO = [
    "entidad_nit", "entidad_nombre", "entidad_departamento", "entidad_ciudad",
    "entidad_orden", "entidad_sector", "entidad_rama", "proceso_de_compra",
    "referencia", "estado", "tipo_contrato", "modalidad", "objeto",
    "proveedor_tipo_doc", "proveedor_documento", "proveedor_nombre",
    "origen_recursos", "destino_gasto",
]
COLUMNAS_VALOR = ["valor_contrato", "valor_facturado", "valor_pagado",
                  "valor_pendiente_ejec"]
COLUMNAS_FECHA = ["fecha_firma", "fecha_inicio", "fecha_fin"]


# ------------------------------------------------------------ utilidades
def limpiar_texto(valor):
    """'  NAYDU  HORTUA ' -> 'NAYDU HORTUA';  'No Definido' -> None"""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = " ".join(str(valor).split())
    return None if texto.lower() in NULOS else texto


def limpiar_documento(valor):
    """'1.005.755.668' / 'cc 1007385196' / '80777291.' -> solo dígitos."""
    if valor is None:
        return None
    digitos = "".join(c for c in str(valor) if c.isdigit())
    return digitos or None


def seudonimizar(documento, tipo_doc):
    """Las cédulas son datos personales: guardamos un hash, no el número.

    El NIT de una empresa es público, ese se deja tal cual. El hash es
    estable (misma cédula -> mismo hash), así que sigue sirviendo como
    llave para agrupar por proveedor. La sal evita que alguien recupere
    la cédula probando todos los números posibles.
    """
    if documento is None:
        return None
    if tipo_doc == "NIT":
        return documento
    sal = os.getenv("SEUDONIMO_SAL", "cambia-esta-sal")
    return hashlib.sha256(f"{sal}:{documento}".encode()).hexdigest()[:24]


def a_booleano(valor):
    mapa = {"si": True, "sí": True, "no": False}
    return mapa.get(str(valor).strip().lower()) if valor is not None else None


# ------------------------------------------------------------ transform
def transformar(registros: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    if not registros:
        return pd.DataFrame(), []

    # La API omite las llaves con valor nulo: si en una página nadie trae
    # un campo, la columna ni existe. reindex garantiza el esquema completo.
    df = (pd.DataFrame(registros)
            .reindex(columns=COLUMNAS)
            .rename(columns=RENOMBRAR))
    crudo_por_id = {r.get("id_contrato"): r for r in registros}

    # 1. Texto: espacios, nulos disfrazados, mayúsculas consistentes
    for col in COLUMNAS_TEXTO:
        df[col] = df[col].map(limpiar_texto)
    df["estado"] = df["estado"].str.capitalize()          # 'cedido' -> 'Cedido'
    df["proveedor_nombre"] = df["proveedor_nombre"].str.upper()
    df["id_contrato"] = df["id_contrato"].map(limpiar_texto)

    # 2. Tipos: texto -> número / fecha / booleano
    for col in COLUMNAS_VALOR:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in COLUMNAS_FECHA:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    df["ultima_actualizacion"] = pd.to_datetime(
        df["ultima_actualizacion"], errors="coerce")
    df["dias_adicionados"] = pd.to_numeric(
        df["dias_adicionados"], errors="coerce").astype("Int64")
    df["proveedor_es_pyme"] = df["proveedor_es_pyme"].map(a_booleano)

    # 3. Documento del proveedor: normalizar y seudonimizar
    df["proveedor_documento"] = df["proveedor_documento"].map(limpiar_documento)
    df["proveedor_documento"] = [
        seudonimizar(doc, tipo)
        for doc, tipo in zip(df["proveedor_documento"], df["proveedor_tipo_doc"])
    ]

    # 4. Enriquecer: columnas derivadas que no vienen en la fuente
    codigo = df["codigo_de_categoria_principal"].map(limpiar_texto)
    df["unspsc_codigo"] = codigo.str.replace(r"^V1\.", "", regex=True)
    df["unspsc_segmento"] = df["unspsc_codigo"].str[:2]

    inicio = pd.to_datetime(df["fecha_inicio"])
    fin = pd.to_datetime(df["fecha_fin"])
    duracion = (fin - inicio).dt.days
    df["duracion_dias"] = duracion.where(duracion >= 0).astype("Int64")

    df["url_proceso"] = df["urlproceso"].map(
        lambda u: u.get("url") if isinstance(u, dict) else limpiar_texto(u))

    # 5. Validar: lo que no cumple reglas mínimas va a rechazos, no al DW
    reglas = {
        "sin id_contrato": df["id_contrato"].isna(),
        "sin entidad": df["entidad_nit"].isna() | df["entidad_nombre"].isna(),
        "valor inválido": df["valor_contrato"].isna() | (df["valor_contrato"] < 0),
    }
    motivo = pd.Series(None, index=df.index, dtype="object")
    for nombre, mascara in reglas.items():
        motivo = motivo.where(~(mascara & motivo.isna()), nombre)

    malos = motivo.notna()
    rechazos = [
        {"id_contrato": df.at[i, "id_contrato"], "motivo": motivo[i],
         "payload": crudo_por_id.get(df.at[i, "id_contrato"], {})}
        for i in df.index[malos]
    ]
    df = df[~malos]

    # 6. Deduplicar: si un contrato viene repetido, gana la versión más nueva
    #    (los que no traen fecha de actualización quedan de primeros = pierden)
    df = (df.sort_values("ultima_actualizacion", na_position="first")
            .drop_duplicates("id_contrato", keep="last"))

    columnas_finales = [
        "id_contrato",
        "entidad_nit", "entidad_nombre", "entidad_departamento",
        "entidad_ciudad", "entidad_orden", "entidad_sector", "entidad_rama",
        "proveedor_tipo_doc", "proveedor_documento", "proveedor_nombre",
        "proveedor_es_pyme",
        "proceso_de_compra", "referencia", "estado", "tipo_contrato",
        "modalidad", "unspsc_codigo", "unspsc_segmento", "objeto",
        "fecha_firma", "fecha_inicio", "fecha_fin", "duracion_dias",
        "dias_adicionados", *COLUMNAS_VALOR,
        "origen_recursos", "destino_gasto", "url_proceso",
        "ultima_actualizacion",
    ]
    return df[columnas_finales].reset_index(drop=True), rechazos

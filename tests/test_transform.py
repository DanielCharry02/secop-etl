"""Pruebas del transform con casos sucios reales vistos en SECOP II."""
import pandas as pd

from etl.transform import limpiar_documento, limpiar_texto, transformar


def registro(**cambios):
    base = {
        "id_contrato": "CO1.PCCNTR.1",
        "proceso_de_compra": "CO1.BDOS.1",
        "referencia_del_contrato": "001-2026",
        "nit_entidad": "800113672",
        "nombre_entidad": "GOBERNACION DEL TOLIMA",
        "departamento": "Tolima", "ciudad": "Ibagué",
        "orden": "Territorial", "sector": "Servicio Público", "rama": "Ejecutivo",
        "estado_contrato": "En ejecución",
        "tipo_de_contrato": "Prestación de servicios",
        "modalidad_de_contratacion": "Contratación directa",
        "codigo_de_categoria_principal": "V1.80111701",
        "objeto_del_contrato": "Apoyo a la gestión",
        "fecha_de_firma": "2026-02-01T00:00:00.000",
        "fecha_de_inicio_del_contrato": "2026-02-02T00:00:00.000",
        "fecha_de_fin_del_contrato": "2026-07-31T00:00:00.000",
        "tipodocproveedor": "NIT",
        "documento_proveedor": "900123456",
        "proveedor_adjudicado": "Acme  S.A.S",
        "es_pyme": "Si",
        "valor_del_contrato": "25000000",
        "valor_facturado": "0", "valor_pagado": "0",
        "valor_pendiente_de_ejecucion": "25000000",
        "dias_adicionados": "0",
        "origen_de_los_recursos": "Distribuido", "destino_gasto": "Inversión",
        "urlproceso": {"url": "https://community.secop.gov.co/x"},
        "ultima_actualizacion": "2026-03-01T00:00:00.000",
    }
    base.update(cambios)
    return base


def test_limpiar_texto():
    assert limpiar_texto("  LUDI  MERCEDES   ") == "LUDI MERCEDES"
    assert limpiar_texto("No Definido") is None
    assert limpiar_texto("") is None


def test_limpiar_documento_formatos_reales():
    assert limpiar_documento("1.005.755.668") == "1005755668"
    assert limpiar_documento("cc 1007385196") == "1007385196"
    assert limpiar_documento("80777291.") == "80777291"
    assert limpiar_documento("No Definido") is None


def test_tipos_y_derivadas():
    df, rechazos = transformar([registro()])
    fila = df.iloc[0]
    assert rechazos == []
    assert fila["valor_contrato"] == 25_000_000
    assert bool(fila["proveedor_es_pyme"])
    assert fila["proveedor_nombre"] == "ACME S.A.S"
    assert fila["unspsc_codigo"] == "80111701"
    assert fila["unspsc_segmento"] == "80"
    assert fila["duracion_dias"] == 179
    assert fila["url_proceso"] == "https://community.secop.gov.co/x"


def test_estado_normalizado():
    df, _ = transformar([registro(estado_contrato="cedido")])
    assert df.iloc[0]["estado"] == "Cedido"


def test_cedula_se_seudonimiza_y_nit_no():
    df, _ = transformar([
        registro(id_contrato="A", tipodocproveedor="Cédula de Ciudadanía",
                 documento_proveedor="1.005.755.668"),
        registro(id_contrato="B"),
    ])
    cedula = df.loc[df.id_contrato == "A", "proveedor_documento"].item()
    nit = df.loc[df.id_contrato == "B", "proveedor_documento"].item()
    assert "1005755668" not in cedula and len(cedula) == 24
    assert nit == "900123456"


def test_fechas_invertidas_no_generan_duracion_negativa():
    df, _ = transformar([registro(
        fecha_de_inicio_del_contrato="2026-08-01T00:00:00.000",
        fecha_de_fin_del_contrato="2026-07-01T00:00:00.000")])
    assert pd.isna(df.iloc[0]["duracion_dias"])


def test_rechazos():
    _, rechazos = transformar([
        registro(id_contrato="X1", valor_del_contrato="abc"),
        registro(id_contrato="X2", valor_del_contrato="-5"),
        registro(id_contrato="X3", nit_entidad="No Definido"),
    ])
    motivos = {r["id_contrato"]: r["motivo"] for r in rechazos}
    assert motivos == {"X1": "valor inválido", "X2": "valor inválido",
                       "X3": "sin entidad"}


def test_duplicados_gana_version_mas_reciente():
    df, _ = transformar([
        registro(estado_contrato="Activo",
                 ultima_actualizacion="2026-03-05T00:00:00.000"),
        registro(estado_contrato="Modificado",
                 ultima_actualizacion="2026-03-01T00:00:00.000"),
    ])
    assert len(df) == 1
    assert df.iloc[0]["estado"] == "Activo"


def test_ventana_incremental():
    from datetime import date
    from etl.extract import calcular_desde
    assert calcular_desde("2026-01-01", None, 30) == date(2026, 1, 1)
    assert calcular_desde("2026-01-01", date(2026, 10, 9), 30) == date(2026, 9, 9)
    # La ventana nunca va más atrás del piso configurado
    assert calcular_desde("2026-01-01", date(2026, 1, 10), 30) == date(2026, 1, 1)


def test_sin_ultima_actualizacion_no_se_rechaza():
    df, rechazos = transformar([registro(ultima_actualizacion=None)])
    assert rechazos == [] and len(df) == 1

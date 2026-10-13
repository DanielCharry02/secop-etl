import logging
import time
from collections.abc import Iterator
from datetime import date, timedelta

import requests

URL = "https://www.datos.gov.co/resource/jbjy-vk9h.json"


COLUMNAS = [
    "id_contrato", "proceso_de_compra", "referencia_del_contrato",
    "nit_entidad", "nombre_entidad", "departamento", "ciudad",
    "orden", "sector", "rama",
    "estado_contrato", "tipo_de_contrato", "modalidad_de_contratacion",
    "codigo_de_categoria_principal", "objeto_del_contrato",
    "fecha_de_firma", "fecha_de_inicio_del_contrato", "fecha_de_fin_del_contrato",
    "tipodocproveedor", "documento_proveedor", "proveedor_adjudicado",
    "es_pyme", "valor_del_contrato", "valor_facturado", "valor_pagado",
    "valor_pendiente_de_ejecucion", "dias_adicionados",
    "origen_de_los_recursos", "destino_gasto", "urlproceso",
    "ultima_actualizacion",
]

log = logging.getLogger(__name__)


def calcular_desde(fecha_desde: str, marca_agua: date | None,
                   ventana_dias: int) -> date:
    piso = date.fromisoformat(fecha_desde)
    if marca_agua is None:
        return piso
    return max(piso, marca_agua - timedelta(days=ventana_dias))


def _construir_where(departamento: str, desde: date) -> str:
    return (f"departamento = '{departamento}' "
            f"AND fecha_de_firma >= '{desde.isoformat()}'")


def _pedir_con_reintentos(sesion: requests.Session, params: dict,
                          intentos: int = 4) -> list[dict]:
    """Las APIs fallan. Reintentamos con espera exponencial: 2s, 4s, 8s."""
    for intento in range(1, intentos + 1):
        try:
            resp = sesion.get(URL, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if intento == intentos:
                raise
            espera = 2 ** intento
            log.warning("Fallo en la API (%s). Reintento %d en %ds",
                        exc, intento, espera)
            time.sleep(espera)
    return []  # inalcanzable, tranquiliza al linter


def extraer(departamento: str, desde: date, tamano_pagina: int = 5000,
            app_token: str | None = None) -> Iterator[list[dict]]:
    sesion = requests.Session()
    if app_token:
        sesion.headers["X-App-Token"] = app_token

    where = _construir_where(departamento, desde)
    offset = 0
    while True:
        params = {
            "$select": ",".join(COLUMNAS),
            "$where": where,
            "$order": "fecha_de_firma, id_contrato",
            "$limit": tamano_pagina,
            "$offset": offset,
        }
        pagina = _pedir_con_reintentos(sesion, params)
        if not pagina:
            break
        log.info("Página extraída: offset=%d filas=%d", offset, len(pagina))
        yield pagina
        if len(pagina) < tamano_pagina:
            break
        offset += tamano_pagina

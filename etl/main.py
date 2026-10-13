"""Orquestador: une Extract -> Transform -> Load y registra la ejecución.

Uso:
    python -m etl.main               # incremental (ventana sobre la última marca de agua)
    python -m etl.main --completa    # recarga todo desde SECOP_FECHA_DESDE
"""
import argparse
import logging
import sys

import psycopg

from etl.config import cargar_config
from etl.extract import calcular_desde, extraer
from etl.load import (cargar_lote, cerrar_ejecucion, iniciar_ejecucion,
                      ultima_marca_agua)
from etl.transform import transformar

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("etl")


def ejecutar(completa: bool = False) -> int:
    cfg = cargar_config()
    with psycopg.connect(cfg.database_url) as conn:
        marca_previa = None if completa else ultima_marca_agua(conn)
        modo = "incremental" if marca_previa else "completa"
        desde = calcular_desde(cfg.fecha_firma_desde, marca_previa,
                               cfg.ventana_dias)
        ejecucion_id = iniciar_ejecucion(conn, modo)
        log.info("Ejecución %d (%s) depto=%s firmas desde=%s (marca_agua=%s)",
                 ejecucion_id, modo, cfg.departamento, desde, marca_previa)

        extraidas = cargadas = rechazadas = 0
        nueva_marca = marca_previa
        try:
            for pagina in extraer(cfg.departamento, desde,
                                  cfg.tamano_pagina, cfg.app_token):
                limpios, rechazos = transformar(pagina)
                cargadas += cargar_lote(conn, ejecucion_id, limpios,
                                        rechazos, pagina)
                extraidas += len(pagina)
                rechazadas += len(rechazos)
                fechas = limpios["fecha_firma"].dropna() if not limpios.empty else []
                if len(fechas):
                    maximo = fechas.max()
                    nueva_marca = max(nueva_marca or maximo, maximo)

            cerrar_ejecucion(conn, ejecucion_id, "ok", extraidas, cargadas,
                             rechazadas, nueva_marca)
            log.info("OK: extraídas=%d cargadas=%d rechazadas=%d marca_agua=%s",
                     extraidas, cargadas, rechazadas, nueva_marca)
            return 0
        except Exception as exc:
            # La marca de agua NO avanza: la próxima ejecución reintenta.
            cerrar_ejecucion(conn, ejecucion_id, "error", extraidas, cargadas,
                             rechazadas, None, str(exc))
            log.exception("La ejecución %d falló", ejecucion_id)
            return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL SECOP II -> PostgreSQL")
    parser.add_argument("--completa", action="store_true",
                        help="Ignora la marca de agua y recarga todo")
    sys.exit(ejecutar(parser.parse_args().completa))

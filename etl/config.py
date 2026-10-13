"""Configuración leída de variables de entorno (ver .env.example)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    database_url: str
    departamento: str
    fecha_firma_desde: str
    tamano_pagina: int
    ventana_dias: int
    app_token: str | None


def cargar_config() -> Config:
    return Config(
        database_url=os.getenv(
            "DATABASE_URL", "postgresql://etl:etl@localhost:5432/secop"
        ),
        departamento=os.getenv("SECOP_DEPARTAMENTO", "Tolima"),
        fecha_firma_desde=os.getenv("SECOP_FECHA_DESDE", "2026-01-01"),
        tamano_pagina=int(os.getenv("SECOP_TAMANO_PAGINA", "5000")),
        # Días hacia atrás que se reprocesan en cada corrida incremental
        ventana_dias=int(os.getenv("SECOP_VENTANA_DIAS", "30")),
        # Opcional: sin token la API funciona, pero con límites más bajos.
        app_token=os.getenv("SOCRATA_APP_TOKEN") or None,
    )

FROM python:3.13-slim

WORKDIR /app

# Primero solo las dependencias: Docker cachea esta capa y no reinstala
# todo cada vez que cambias una línea de código.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY etl/ etl/

# No correr como root dentro del contenedor
RUN useradd --create-home etl
USER etl

ENTRYPOINT ["python", "-m", "etl.main"]

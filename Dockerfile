FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias primero (mejor cache de layers).
# Usamos requirements-api.txt (slim) — no incluye streamlit/plotly/anthropic
# porque el dashboard y el agente no viven en este contenedor.
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Copiar el código de la API
COPY api.py .

# Cloud Run inyecta la variable PORT (default 8080). Uvicorn escucha ahí.
ENV PORT=8080
CMD exec uvicorn api:app --host 0.0.0.0 --port ${PORT}

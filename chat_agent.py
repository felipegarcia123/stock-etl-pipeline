"""
Chat Agent
----------
Agente conversacional que responde preguntas sobre el data warehouse consultando
la API REST (api.py) via function calling / tool use de Claude.

Uso:
    export ANTHROPIC_API_KEY="sk-ant-..."
    from chat_agent import chat
    text, history = chat("¿qué empresas hay?", history=[])

Prompt caching activo sobre las definiciones de tools para bajar costos en
conversaciones largas (TTL 5 min).
"""

import json
import os
from typing import Tuple

import anthropic
import requests

API_URL = os.environ.get("API_URL", "https://stock-etl-api-17483676928.us-central1.run.app")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

client = anthropic.Anthropic()  # lee ANTHROPIC_API_KEY del entorno


# ---------------------------------------------------------------------------
# Tools — una por endpoint de la API
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list_tickers",
        "description": "Lista todos los tickers disponibles con su metadata (empresa, industria, bolsa, moneda, país). Úsalo cuando el usuario quiera saber qué empresas están disponibles o filtrar por país/sector.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_ticker_info",
        "description": "Metadata de un ticker específico: nombre, industria, bolsa, moneda, país, parent_brand.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Código bursátil, ej: AAPL, EC, NUTRESA.CL"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_prices",
        "description": "Precios diarios (Open, High, Low, Close, Volume) de un ticker durante los últimos N días de mercado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {"type": "integer", "description": "Días de historia, 1..3650. Default 30.", "default": 30},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_intraday",
        "description": "Precios por hora (últimas N horas) de un ticker. Útil para ver movimientos intradía. Yahoo solo permite ~2 años.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "hours": {"type": "integer", "default": 48},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_metrics",
        "description": "Métricas derivadas: retorno diario (%), media móvil de 20 días (MA20) y volatilidad de 20 días. Se calculan sobre stock_data_dwh.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {"type": "integer", "default": 30},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_top_movers",
        "description": "Ranking de tickers por retorno del último día que cada uno operó. 'up' = mayores subidas, 'down' = mayores caídas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 5},
                "direction": {"type": "string", "enum": ["up", "down"], "default": "up"},
            },
            "required": [],
        },
    },
    {
        "name": "get_market_summary",
        "description": "Resumen del último día: cuántos tickers operaron y top ganador/perdedor. Ideal para 'cómo estuvo el mercado hoy'.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        # Cache-control en el último tool → cachea todos los tools + system prompt.
        "cache_control": {"type": "ephemeral"},
    },
]


def _call_api(name: str, args: dict) -> dict:
    """Ejecuta una tool llamando al endpoint HTTP correspondiente."""
    try:
        if name == "list_tickers":
            r = requests.get(f"{API_URL}/tickers", timeout=15)
        elif name == "get_ticker_info":
            r = requests.get(f"{API_URL}/tickers/{args['ticker']}", timeout=15)
        elif name == "get_prices":
            r = requests.get(
                f"{API_URL}/tickers/{args['ticker']}/prices",
                params={"days": args.get("days", 30)}, timeout=30,
            )
        elif name == "get_intraday":
            r = requests.get(
                f"{API_URL}/tickers/{args['ticker']}/intraday",
                params={"hours": args.get("hours", 48)}, timeout=30,
            )
        elif name == "get_metrics":
            r = requests.get(
                f"{API_URL}/tickers/{args['ticker']}/metrics",
                params={"days": args.get("days", 30)}, timeout=30,
            )
        elif name == "get_top_movers":
            r = requests.get(
                f"{API_URL}/market/top-movers",
                params={"limit": args.get("limit", 5), "direction": args.get("direction", "up")},
                timeout=15,
            )
        elif name == "get_market_summary":
            r = requests.get(f"{API_URL}/market/summary", timeout=15)
        else:
            return {"error": f"Tool desconocido: {name}"}
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return r.json()
    except Exception as e:
        return {"error": f"Excepción llamando a la API: {e}"}


SYSTEM_PROMPT = [
    {
        "type": "text",
        "text": (
            "Eres un asistente financiero experto que ayuda a usuarios a entender datos "
            "bursátiles de un data warehouse en BigQuery.\n\n"
            "Los datos incluyen ~30 tickers: acciones colombianas (BVC + ADRs en NYSE/NASDAQ) "
            "y estadounidenses. Tienes acceso a: metadata por empresa, precios diarios OHLCV, "
            "precios intradía por hora, métricas derivadas (retorno diario, MA20, volatilidad), "
            "y rankings del mercado.\n\n"
            "Reglas:\n"
            "1. Siempre usa las tools disponibles para consultar datos reales. Nunca inventes números.\n"
            "2. Si una pregunta requiere varias consultas (comparar 2 empresas, etc.), haz todas las llamadas necesarias antes de responder.\n"
            "3. Presenta cifras con contexto: usa signos (+/-) en porcentajes, indica moneda (USD/COP), aclara fechas relevantes.\n"
            "4. IMPORTANTE — Monedas: los tickers de USA y los ADRs (`EC`, `CIB`, `AVAL`, `TGLS`) cotizan en USD; los tickers `.CL` cotizan en COP. Nunca compares precios entre monedas sin aclarar la diferencia de escala.\n"
            "5. Algunas empresas tienen múltiples cotizaciones (ej. Ecopetrol como `EC` en NYSE y `ECOPETROL.CL` en BVC). Usa `parent_brand` para identificarlas.\n"
            "6. Sé conciso pero informativo. Formatea números con separadores y máximo 2 decimales.\n"
            "7. Si no puedes responder con los datos disponibles, dilo honestamente.\n"
            "8. Responde SIEMPRE en español."
        ),
        "cache_control": {"type": "ephemeral"},
    }
]


def chat(user_message: str, history: list) -> Tuple[str, list]:
    """Procesa un mensaje del usuario y devuelve (respuesta, historial actualizado).

    Loop de tool use: si Claude pide llamar una o más tools, se ejecutan, se le pasan
    los resultados, y se itera hasta que Claude dé una respuesta final de texto.
    """
    messages = list(history) + [{"role": "user", "content": user_message}]

    # Máximo 8 iteraciones para no bucles infinitos.
    for _ in range(8):
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Guardar respuesta del asistente en el historial (bloques de content raw).
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # Respuesta final
            text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            final_text = "\n".join(text_blocks).strip() or "(sin respuesta)"
            return final_text, messages

        # Ejecutar tools que pidió el modelo
        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                result = _call_api(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str, ensure_ascii=False),
                })
        messages.append({"role": "user", "content": tool_results})

    return "(el agente hizo demasiadas llamadas; interrumpido)", messages

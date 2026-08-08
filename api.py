"""
Stock Market ETL API
--------------------
API REST que expone los datos del data warehouse en BigQuery.

Endpoints:
    GET  /                           - health check
    GET  /tickers                    - lista todos los tickers con metadata
    GET  /tickers/{ticker}           - metadata de un ticker
    GET  /tickers/{ticker}/prices    - precios diarios (últimos N días)
    GET  /tickers/{ticker}/intraday  - precios horarios (últimas N horas)
    GET  /tickers/{ticker}/metrics   - retorno, MA20, volatilidad
    GET  /market/top-movers          - top N tickers por retorno del último día
    GET  /market/summary             - resumen del último día

Uso:
    export GOOGLE_APPLICATION_CREDENTIALS="$PWD/key.json"
    export GCP_PROJECT_ID="stock-etl-lacabrita"
    uvicorn api:app --reload --port 8000

Documentación interactiva (Swagger) en:
    http://localhost:8000/docs
"""

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import bigquery
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "stock-etl-lacabrita")
DATASET_ID = "kaggle_stock"

app = FastAPI(
    title="Stock ETL API",
    description="API que expone datos bursátiles procesados por el pipeline ETL.",
    version="1.0.0",
)

# CORS abierto para desarrollo. En producción, restringir a los orígenes reales.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = bigquery.Client(project=PROJECT_ID)


# ---------------------------------------------------------------------------
# Pydantic models (contratos de respuesta)
# ---------------------------------------------------------------------------

class Ticker(BaseModel):
    ticker: str
    brand_name: str
    industry_tag: str
    exchange: str
    country: str
    currency: str


class PricePoint(BaseModel):
    date: str
    ticker: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    dividends: float
    stock_splits: int


class IntradayPoint(BaseModel):
    timestamp_utc: str
    timestamp_cot: str
    ticker: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class Metric(BaseModel):
    date: str
    ticker: str
    close: float
    daily_return: Optional[float] = None
    ma20: Optional[float] = None
    volatility_20d: Optional[float] = None


class TopMover(BaseModel):
    ticker: str
    brand_name: str
    close: float
    daily_return: float
    currency: str


class MarketSummary(BaseModel):
    date: str
    tickers_activos: int
    top_ganador: Optional[TopMover] = None
    top_perdedor: Optional[TopMover] = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def q(sql: str, params: list = None):
    """Ejecuta un query parametrizado y devuelve las filas."""
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    return list(client.query(sql, job_config=job_config).result())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", tags=["health"])
def health():
    """Health check para saber si la API está viva."""
    return {"status": "ok", "service": "stock-etl-api", "project": PROJECT_ID}


@app.get("/tickers", response_model=list[Ticker], tags=["tickers"])
def list_tickers():
    """Lista todos los tickers configurados con su metadata."""
    rows = q(f"SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.tickers_dim` ORDER BY Ticker")
    return [
        Ticker(
            ticker=r.Ticker, brand_name=r.Brand_Name, industry_tag=r.Industry_Tag,
            exchange=r.Exchange, country=r.Country, currency=r.Currency,
        )
        for r in rows
    ]


@app.get("/tickers/{ticker}", response_model=Ticker, tags=["tickers"])
def get_ticker(ticker: str):
    """Metadata de un ticker específico."""
    rows = q(
        f"SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.tickers_dim` WHERE Ticker = @t",
        [bigquery.ScalarQueryParameter("t", "STRING", ticker.upper())],
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' no encontrado.")
    r = rows[0]
    return Ticker(
        ticker=r.Ticker, brand_name=r.Brand_Name, industry_tag=r.Industry_Tag,
        exchange=r.Exchange, country=r.Country, currency=r.Currency,
    )


@app.get("/tickers/{ticker}/prices", response_model=list[PricePoint], tags=["prices"])
def get_prices(
    ticker: str,
    days: int = Query(30, ge=1, le=3650, description="Días hacia atrás a consultar."),
):
    """Precios diarios (OHLCV) de los últimos N días de mercado."""
    rows = q(
        f"""
        SELECT Date, Ticker, Open, High, Low, Close, Volume, Dividends, Stock_Splits
        FROM `{PROJECT_ID}.{DATASET_ID}.stock_data_dwh`
        WHERE Ticker = @t
          AND Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @d DAY)
        ORDER BY Date DESC
        """,
        [
            bigquery.ScalarQueryParameter("t", "STRING", ticker.upper()),
            bigquery.ScalarQueryParameter("d", "INT64", days),
        ],
    )
    return [
        PricePoint(
            date=r.Date.isoformat(), ticker=r.Ticker,
            open=r.Open, high=r.High, low=r.Low, close=r.Close,
            volume=r.Volume, dividends=r.Dividends, stock_splits=r.Stock_Splits,
        )
        for r in rows
    ]


@app.get("/tickers/{ticker}/intraday", response_model=list[IntradayPoint], tags=["prices"])
def get_intraday(
    ticker: str,
    hours: int = Query(48, ge=1, le=17520, description="Horas hacia atrás a consultar."),
):
    """Precios horarios (OHLCV por hora) de las últimas N horas."""
    rows = q(
        f"""
        SELECT Timestamp_UTC, Timestamp_COT, Ticker, Open, High, Low, Close, Volume
        FROM `{PROJECT_ID}.{DATASET_ID}.stock_data_intraday_view`
        WHERE Ticker = @t
          AND Timestamp_UTC >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @h HOUR)
        ORDER BY Timestamp_UTC DESC
        """,
        [
            bigquery.ScalarQueryParameter("t", "STRING", ticker.upper()),
            bigquery.ScalarQueryParameter("h", "INT64", hours),
        ],
    )
    return [
        IntradayPoint(
            timestamp_utc=r.Timestamp_UTC.isoformat(),
            timestamp_cot=str(r.Timestamp_COT),
            ticker=r.Ticker,
            open=r.Open, high=r.High, low=r.Low, close=r.Close,
            volume=r.Volume,
        )
        for r in rows
    ]


@app.get("/tickers/{ticker}/metrics", response_model=list[Metric], tags=["metrics"])
def get_metrics(
    ticker: str,
    days: int = Query(30, ge=1, le=3650, description="Días hacia atrás a consultar."),
):
    """Métricas derivadas (retorno diario, MA20, volatilidad) de los últimos N días."""
    rows = q(
        f"""
        SELECT Date, Ticker, Close, daily_return, ma20, volatility_20d
        FROM `{PROJECT_ID}.{DATASET_ID}.stock_metrics`
        WHERE Ticker = @t
          AND Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @d DAY)
        ORDER BY Date DESC
        """,
        [
            bigquery.ScalarQueryParameter("t", "STRING", ticker.upper()),
            bigquery.ScalarQueryParameter("d", "INT64", days),
        ],
    )
    return [
        Metric(
            date=r.Date.isoformat(), ticker=r.Ticker, close=r.Close,
            daily_return=r.daily_return, ma20=r.ma20, volatility_20d=r.volatility_20d,
        )
        for r in rows
    ]


@app.get("/market/top-movers", response_model=list[TopMover], tags=["market"])
def top_movers(
    limit: int = Query(5, ge=1, le=50, description="Cuántos tickers devolver."),
    direction: str = Query("up", pattern="^(up|down)$", description="'up' = mayores subidas, 'down' = mayores caídas."),
):
    """Top N tickers por retorno del último día que cada ticker haya operado.

    Usa la fecha más reciente POR TICKER, no una fecha global — así los tickers
    de la BVC siguen apareciendo aunque hoy sea festivo en Colombia.
    """
    order = "DESC" if direction == "up" else "ASC"
    rows = q(
        f"""
        WITH latest_per_ticker AS (
            SELECT Ticker, MAX(Date) AS last_date
            FROM `{PROJECT_ID}.{DATASET_ID}.stock_metrics`
            WHERE daily_return IS NOT NULL
            GROUP BY Ticker
        )
        SELECT m.Ticker, d.Brand_Name, m.Close, m.daily_return, d.Currency
        FROM `{PROJECT_ID}.{DATASET_ID}.stock_metrics` m
        JOIN latest_per_ticker l ON m.Ticker = l.Ticker AND m.Date = l.last_date
        JOIN `{PROJECT_ID}.{DATASET_ID}.tickers_dim` d ON m.Ticker = d.Ticker
        ORDER BY m.daily_return {order}
        LIMIT @limit
        """,
        [bigquery.ScalarQueryParameter("limit", "INT64", limit)],
    )
    return [
        TopMover(
            ticker=r.Ticker, brand_name=r.Brand_Name, close=r.Close,
            daily_return=r.daily_return, currency=r.Currency,
        )
        for r in rows
    ]


@app.get("/market/summary", response_model=MarketSummary, tags=["market"])
def market_summary():
    """Resumen del último día que cada ticker haya operado."""
    rows = q(
        f"""
        WITH latest_per_ticker AS (
            SELECT Ticker, MAX(Date) AS last_date
            FROM `{PROJECT_ID}.{DATASET_ID}.stock_metrics`
            WHERE daily_return IS NOT NULL
            GROUP BY Ticker
        )
        SELECT m.Ticker, d.Brand_Name, m.Close, m.daily_return, d.Currency, m.Date
        FROM `{PROJECT_ID}.{DATASET_ID}.stock_metrics` m
        JOIN latest_per_ticker l ON m.Ticker = l.Ticker AND m.Date = l.last_date
        JOIN `{PROJECT_ID}.{DATASET_ID}.tickers_dim` d ON m.Ticker = d.Ticker
        ORDER BY m.daily_return DESC
        """,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No hay datos en stock_metrics.")
    top = rows[0]
    bot = rows[-1]
    return MarketSummary(
        date=top.Date.isoformat(),
        tickers_activos=len(rows),
        top_ganador=TopMover(
            ticker=top.Ticker, brand_name=top.Brand_Name, close=top.Close,
            daily_return=top.daily_return, currency=top.Currency,
        ),
        top_perdedor=TopMover(
            ticker=bot.Ticker, brand_name=bot.Brand_Name, close=bot.Close,
            daily_return=bot.daily_return, currency=bot.Currency,
        ),
    )

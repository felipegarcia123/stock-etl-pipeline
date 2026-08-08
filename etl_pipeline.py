"""
ETL Pipeline: Stock Market Data
--------------------------------
Descarga datos de Yahoo Finance para varios tickers y los carga en BigQuery
en 4 tablas:

    stock_data_dwh        (fact diario)      -- 1 fila = 1 día × 1 ticker
    stock_data_intraday   (fact horario)     -- 1 fila = 1 hora × 1 ticker
    tickers_dim           (dimensión)        -- 1 fila = 1 ticker (metadata)
    stock_metrics         (derivada)         -- calculada en SQL a partir del fact diario

Uso:
    python etl_pipeline.py                       # modo diario (default)
    BACKFILL_START=2020-01-01 python etl_pipeline.py  # backfill una sola vez

Variables de entorno:
    GOOGLE_APPLICATION_CREDENTIALS -> ruta al JSON de la service account de GCP
    GCP_PROJECT_ID                 -> ID de tu proyecto de Google Cloud
    BACKFILL_START (opcional)      -> fecha 'YYYY-MM-DD' para cargar historia
"""

import os
import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "stock-etl-lacabrita")
DATASET_ID = "kaggle_stock"
FACT_TABLE_ID = "stock_data_dwh"
INTRADAY_TABLE_ID = "stock_data_intraday"
DIM_TABLE_ID = "tickers_dim"
METRICS_TABLE_ID = "stock_metrics"

FACT_TABLE_REF     = f"{PROJECT_ID}.{DATASET_ID}.{FACT_TABLE_ID}"
INTRADAY_TABLE_REF = f"{PROJECT_ID}.{DATASET_ID}.{INTRADAY_TABLE_ID}"
DIM_TABLE_REF      = f"{PROJECT_ID}.{DATASET_ID}.{DIM_TABLE_ID}"
METRICS_TABLE_REF  = f"{PROJECT_ID}.{DATASET_ID}.{METRICS_TABLE_ID}"

# Fuente única de verdad: qué tickers descargar y cuál es su metadata.
# `parent_brand` agrupa las múltiples cotizaciones de una misma empresa
# (ej. Grupo Aval tiene AVAL en NYSE + GRUPOAVAL.CL y PFAVAL.CL en BVC).
TICKERS = {
    # === Bancolombia ===
    "CIB":          {"brand_name": "Bancolombia",             "parent_brand": "Bancolombia",     "industry_tag": "banking",       "exchange": "NYSE",   "country": "colombia", "currency": "USD"},

    # === Grupo Aval (múltiples cotizaciones) ===
    "AVAL":         {"brand_name": "Grupo Aval",              "parent_brand": "Grupo Aval",      "industry_tag": "financial",     "exchange": "NYSE",   "country": "colombia", "currency": "USD"},
    "GRUPOAVAL.CL": {"brand_name": "Grupo Aval",              "parent_brand": "Grupo Aval",      "industry_tag": "financial",     "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "PFAVAL.CL":    {"brand_name": "Grupo Aval (Pref.)",      "parent_brand": "Grupo Aval",      "industry_tag": "financial",     "exchange": "BVC",    "country": "colombia", "currency": "COP"},

    # === Ecopetrol (múltiples cotizaciones) ===
    "EC":           {"brand_name": "Ecopetrol",               "parent_brand": "Ecopetrol",       "industry_tag": "oil_gas",       "exchange": "NYSE",   "country": "colombia", "currency": "USD"},
    "ECOPETROL.CL": {"brand_name": "Ecopetrol",               "parent_brand": "Ecopetrol",       "industry_tag": "oil_gas",       "exchange": "BVC",    "country": "colombia", "currency": "COP"},

    # === Colombia (BVC local, cotización única) ===
    "ISA.CL":       {"brand_name": "ISA",                     "parent_brand": "ISA",             "industry_tag": "utilities",     "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "NUTRESA.CL":   {"brand_name": "Grupo Nutresa",           "parent_brand": "Grupo Nutresa",   "industry_tag": "food",          "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "GRUPOSURA.CL": {"brand_name": "Grupo SURA",              "parent_brand": "Grupo SURA",     "industry_tag": "financial",     "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "CEMARGOS.CL":  {"brand_name": "Cementos Argos",          "parent_brand": "Cementos Argos", "industry_tag": "materials",     "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "TGLS":         {"brand_name": "Tecnoglass",              "parent_brand": "Tecnoglass",     "industry_tag": "manufacturing", "exchange": "NASDAQ", "country": "colombia", "currency": "USD"},
    "PFDAVVNDA.CL": {"brand_name": "Davivienda (Pref.)",      "parent_brand": "Davivienda",     "industry_tag": "banking",       "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "CORFICOLCF.CL":{"brand_name": "Corficolombiana",         "parent_brand": "Corficolombiana","industry_tag": "financial",     "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "BOGOTA.CL":    {"brand_name": "Banco de Bogotá",         "parent_brand": "Banco de Bogotá","industry_tag": "banking",       "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "CELSIA.CL":    {"brand_name": "Celsia",                  "parent_brand": "Celsia",         "industry_tag": "utilities",     "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "GEB.CL":       {"brand_name": "Grupo Energía Bogotá",    "parent_brand": "Grupo Energía Bogotá", "industry_tag": "utilities", "exchange": "BVC",  "country": "colombia", "currency": "COP"},
    "CNEC.CL":      {"brand_name": "Canacol Energy",          "parent_brand": "Canacol Energy", "industry_tag": "oil_gas",       "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "TERPEL.CL":    {"brand_name": "Terpel",                  "parent_brand": "Terpel",         "industry_tag": "oil_gas",       "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "EXITO.CL":     {"brand_name": "Grupo Éxito",             "parent_brand": "Grupo Éxito",    "industry_tag": "retail",        "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "ETB.CL":       {"brand_name": "ETB",                     "parent_brand": "ETB",            "industry_tag": "telecom",       "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "MINEROS.CL":   {"brand_name": "Mineros",                 "parent_brand": "Mineros",        "industry_tag": "mining",        "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "CONCONCRET.CL":{"brand_name": "Conconcreto",             "parent_brand": "Conconcreto",    "industry_tag": "construction",  "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "BVC.CL":       {"brand_name": "Bolsa de Valores de Colombia", "parent_brand": "BVC",       "industry_tag": "financial",     "exchange": "BVC",    "country": "colombia", "currency": "COP"},
    "ICOLCAP.CL":   {"brand_name": "ETF COLCAP",              "parent_brand": "ETF COLCAP",    "industry_tag": "etf",           "exchange": "BVC",    "country": "colombia", "currency": "COP"},

    # === USA ===
    "AAPL":         {"brand_name": "Apple",                   "parent_brand": "Apple",          "industry_tag": "technology",    "exchange": "NASDAQ", "country": "usa",      "currency": "USD"},
    "MSFT":         {"brand_name": "Microsoft",               "parent_brand": "Microsoft",      "industry_tag": "technology",    "exchange": "NASDAQ", "country": "usa",      "currency": "USD"},
    "AMZN":         {"brand_name": "Amazon",                  "parent_brand": "Amazon",         "industry_tag": "e-commerce",    "exchange": "NASDAQ", "country": "usa",      "currency": "USD"},
    "GOOGL":        {"brand_name": "Alphabet",                "parent_brand": "Alphabet",       "industry_tag": "technology",    "exchange": "NASDAQ", "country": "usa",      "currency": "USD"},
    "TSLA":         {"brand_name": "Tesla",                   "parent_brand": "Tesla",          "industry_tag": "automotive",    "exchange": "NASDAQ", "country": "usa",      "currency": "USD"},
    "NKE":          {"brand_name": "Nike",                    "parent_brand": "Nike",           "industry_tag": "apparel",       "exchange": "NYSE",   "country": "usa",      "currency": "USD"},
    "DIS":          {"brand_name": "Walt Disney",             "parent_brand": "Walt Disney",    "industry_tag": "entertainment", "exchange": "NYSE",   "country": "usa",      "currency": "USD"},
}

LOOKBACK_DAYS = 5             # días de calendario que trae la extract() diaria
INTRADAY_LOOKBACK_DAYS = 3    # días de calendario que trae la extract_intraday() horaria
YAHOO_INTRADAY_MAX_DAYS = 700 # Yahoo permite ~730 días de historia con interval=1h; margen de seguridad

# Modo backfill: si se define BACKFILL_START (ej. "2020-01-01"), el pipeline
# ignora los lookbacks y descarga desde esa fecha. Para intraday se cappea a
# YAHOO_INTRADAY_MAX_DAYS porque Yahoo no da más. El MERGE evita duplicados.
BACKFILL_START = os.environ.get("BACKFILL_START")


# ---------------------------------------------------------------------------
# 1. EXTRACT
# ---------------------------------------------------------------------------

def _resolve_start_date(default_lookback_days: int, intraday: bool = False) -> str:
    """Decide desde qué fecha descargar, respetando BACKFILL_START y el cap intradía."""
    if BACKFILL_START:
        if intraday:
            cap = datetime.utcnow() - timedelta(days=YAHOO_INTRADAY_MAX_DAYS)
            requested = datetime.strptime(BACKFILL_START, "%Y-%m-%d")
            if requested < cap:
                logger.warning(
                    f"BACKFILL_START={BACKFILL_START} excede el límite de Yahoo para intraday "
                    f"({YAHOO_INTRADAY_MAX_DAYS} días); usando {cap.strftime('%Y-%m-%d')}."
                )
                return cap.strftime("%Y-%m-%d")
        return BACKFILL_START
    return (datetime.utcnow() - timedelta(days=default_lookback_days)).strftime("%Y-%m-%d")


def extract_daily(tickers: dict) -> pd.DataFrame:
    """Descarga OHLC diario para cada ticker y los concatena en un DataFrame."""
    start_date = _resolve_start_date(LOOKBACK_DAYS, intraday=False)
    logger.info(f"[daily] Descargando desde {start_date}")
    frames = []

    for ticker in tickers:
        logger.info(f"[daily] {ticker}...")
        df = yf.download(ticker, start=start_date, progress=False, actions=True)
        if df.empty:
            logger.warning(f"[daily] Sin datos para {ticker}, se omite.")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df["Ticker"] = ticker
        frames.append(df)

    if not frames:
        raise RuntimeError("[daily] No se obtuvo ningún dato. Abortando.")

    raw = pd.concat(frames, ignore_index=True)
    logger.info(f"[daily] Extracción completa: {len(raw)} filas de {len(frames)} tickers.")
    return raw


def extract_intraday(tickers: dict) -> pd.DataFrame:
    """Descarga bars horarios (interval=1h) para cada ticker."""
    start_date = _resolve_start_date(INTRADAY_LOOKBACK_DAYS, intraday=True)
    logger.info(f"[intraday] Descargando desde {start_date} (interval=1h)")
    frames = []

    for ticker in tickers:
        logger.info(f"[intraday] {ticker}...")
        df = yf.download(ticker, start=start_date, interval="1h", progress=False)
        if df.empty:
            logger.warning(f"[intraday] Sin datos para {ticker}, se omite.")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df["Ticker"] = ticker
        frames.append(df)

    if not frames:
        logger.warning("[intraday] No se obtuvo ningún dato. Saltando esta fase.")
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)
    logger.info(f"[intraday] Extracción completa: {len(raw)} filas de {len(frames)} tickers.")
    return raw


# ---------------------------------------------------------------------------
# 2. TRANSFORM
# ---------------------------------------------------------------------------

def transform_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Tipa y limpia el DataFrame diario, listo para stock_data_dwh."""
    df = df.copy()

    if "Dividends" not in df.columns:
        df["Dividends"] = 0.0
    if "Stock Splits" not in df.columns:
        df["Stock Splits"] = 0

    df = df.rename(columns={"Stock Splits": "Stock_Splits"})

    final_cols = ["Date", "Ticker", "Open", "High", "Low", "Close", "Volume", "Dividends", "Stock_Splits"]
    df = df[final_cols]

    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    # Redondeo a 4 decimales -> evita el ruido visual del float64 (5.099999...)
    for col in ["Open", "High", "Low", "Close", "Dividends"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").round(4)
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype("int64")
    df["Stock_Splits"] = pd.to_numeric(df["Stock_Splits"], errors="coerce").fillna(0).astype("int64")
    df["Ticker"] = df["Ticker"].astype(str).str.strip()

    before = len(df)
    df = df.dropna(subset=["Date", "Ticker", "Open", "High", "Low", "Close"])
    dropped = before - len(df)
    if dropped:
        logger.warning(f"[daily] Se descartaron {dropped} filas incompletas.")

    logger.info(f"[daily] Transformación completa: {len(df)} filas limpias.")
    return df


def transform_intraday(df: pd.DataFrame) -> pd.DataFrame:
    """Tipa y limpia el DataFrame intraday, listo para stock_data_intraday."""
    if df.empty:
        return df
    df = df.copy()

    # yfinance devuelve "Datetime" como índice cuando interval < 1d
    if "Datetime" in df.columns:
        df = df.rename(columns={"Datetime": "Timestamp"})
    elif "Date" in df.columns:
        df = df.rename(columns={"Date": "Timestamp"})

    final_cols = ["Timestamp", "Ticker", "Open", "High", "Low", "Close", "Volume"]
    df = df[final_cols]

    df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True)
    # Redondeo a 4 decimales -> evita el ruido visual del float64 (5.099999...)
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").round(4)
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype("int64")
    df["Ticker"] = df["Ticker"].astype(str).str.strip()

    before = len(df)
    df = df.dropna(subset=["Timestamp", "Ticker", "Open", "High", "Low", "Close"])
    dropped = before - len(df)
    if dropped:
        logger.warning(f"[intraday] Se descartaron {dropped} filas incompletas.")

    logger.info(f"[intraday] Transformación completa: {len(df)} filas limpias.")
    return df


def build_dim_dataframe(tickers: dict) -> pd.DataFrame:
    """Convierte el dict TICKERS en un DataFrame para la tabla dimensional."""
    rows = [
        {
            "Ticker": ticker,
            "Brand_Name": meta["brand_name"],
            "Parent_Brand": meta["parent_brand"],
            "Industry_Tag": meta["industry_tag"],
            "Exchange": meta["exchange"],
            "Country": meta["country"],
            "Currency": meta["currency"],
        }
        for ticker, meta in tickers.items()
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. LOAD
# ---------------------------------------------------------------------------

FACT_SCHEMA = [
    bigquery.SchemaField("Date", "TIMESTAMP"),
    bigquery.SchemaField("Ticker", "STRING"),
    bigquery.SchemaField("Open", "FLOAT64"),
    bigquery.SchemaField("High", "FLOAT64"),
    bigquery.SchemaField("Low", "FLOAT64"),
    bigquery.SchemaField("Close", "FLOAT64"),
    bigquery.SchemaField("Volume", "INT64"),
    bigquery.SchemaField("Dividends", "FLOAT64"),
    bigquery.SchemaField("Stock_Splits", "INT64"),
]

INTRADAY_SCHEMA = [
    bigquery.SchemaField("Timestamp", "TIMESTAMP"),
    bigquery.SchemaField("Ticker", "STRING"),
    bigquery.SchemaField("Open", "FLOAT64"),
    bigquery.SchemaField("High", "FLOAT64"),
    bigquery.SchemaField("Low", "FLOAT64"),
    bigquery.SchemaField("Close", "FLOAT64"),
    bigquery.SchemaField("Volume", "INT64"),
]

DIM_SCHEMA = [
    bigquery.SchemaField("Ticker", "STRING"),
    bigquery.SchemaField("Brand_Name", "STRING"),
    bigquery.SchemaField("Parent_Brand", "STRING"),
    bigquery.SchemaField("Industry_Tag", "STRING"),
    bigquery.SchemaField("Exchange", "STRING"),
    bigquery.SchemaField("Country", "STRING"),
    bigquery.SchemaField("Currency", "STRING"),
]


def ensure_table_exists(client: bigquery.Client, table_ref: str, schema: list):
    try:
        client.get_table(table_ref)
        logger.info(f"Tabla {table_ref} ya existe.")
    except NotFound:
        client.create_table(bigquery.Table(table_ref, schema=schema))
        logger.info(f"Tabla {table_ref} creada.")


def _merge_load(df: pd.DataFrame, client: bigquery.Client, table_ref: str,
                schema: list, key_cols: list, tmp_suffix: str):
    """Patrón: sube df a tabla temporal, MERGE por key_cols contra table_ref."""
    ensure_table_exists(client, table_ref, schema)

    tmp_table_id = f"{PROJECT_ID}.{DATASET_ID}._tmp_{tmp_suffix}"
    job_config = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE")
    client.load_table_from_dataframe(df, tmp_table_id, job_config=job_config).result()
    logger.info(f"{len(df)} filas cargadas a {tmp_table_id}.")

    all_cols = [f.name for f in schema]
    on_clause = " AND ".join(f"target.{k} = src.{k}" for k in key_cols)
    insert_cols = ", ".join(all_cols)
    insert_values = ", ".join(f"src.{c}" for c in all_cols)

    merge_query = f"""
        MERGE `{table_ref}` AS target
        USING `{tmp_table_id}` AS src
        ON {on_clause}
        WHEN NOT MATCHED THEN
          INSERT ({insert_cols})
          VALUES ({insert_values})
    """
    merge_job = client.query(merge_query)
    merge_job.result()
    rows_inserted = merge_job.num_dml_affected_rows or 0
    logger.info(f"MERGE en {table_ref}: {rows_inserted} filas nuevas.")

    client.delete_table(tmp_table_id, not_found_ok=True)


def load_fact(df: pd.DataFrame, client: bigquery.Client):
    _merge_load(df, client, FACT_TABLE_REF, FACT_SCHEMA,
                key_cols=["Date", "Ticker"], tmp_suffix="fact_load")


def load_intraday(df: pd.DataFrame, client: bigquery.Client):
    if df.empty:
        logger.info("[intraday] DataFrame vacío, no hay nada que cargar.")
        return
    _merge_load(df, client, INTRADAY_TABLE_REF, INTRADAY_SCHEMA,
                key_cols=["Timestamp", "Ticker"], tmp_suffix="intraday_load")


def load_dim(df: pd.DataFrame, client: bigquery.Client):
    """WRITE_TRUNCATE porque la dim es pequeña y viene del dict TICKERS."""
    ensure_table_exists(client, DIM_TABLE_REF, DIM_SCHEMA)
    job_config = bigquery.LoadJobConfig(schema=DIM_SCHEMA, write_disposition="WRITE_TRUNCATE")
    client.load_table_from_dataframe(df, DIM_TABLE_REF, job_config=job_config).result()
    logger.info(f"Dim {DIM_TABLE_REF} refrescada con {len(df)} tickers.")


# ---------------------------------------------------------------------------
# 4. MÉTRICAS DERIVADAS (SQL sobre stock_data_dwh)
# ---------------------------------------------------------------------------

def refresh_metrics(client: bigquery.Client):
    """Recalcula stock_metrics con retorno diario, MA20 y volatilidad_20d.

    - daily_return   = (Close_hoy - Close_ayer) / Close_ayer
    - ma20           = promedio del Close en los últimos 20 días de trading
    - volatility_20d = desviación estándar de los daily_return de los últimos 20 días
    """
    query = f"""
        CREATE OR REPLACE TABLE `{METRICS_TABLE_REF}` AS
        WITH base AS (
            SELECT
                Date,
                Ticker,
                Close,
                LAG(Close) OVER (PARTITION BY Ticker ORDER BY Date) AS prev_close
            FROM `{FACT_TABLE_REF}`
        ),
        returns AS (
            SELECT
                Date,
                Ticker,
                Close,
                SAFE_DIVIDE(Close - prev_close, prev_close) AS daily_return
            FROM base
        )
        SELECT
            Date,
            Ticker,
            Close,
            daily_return,
            AVG(Close) OVER (
                PARTITION BY Ticker ORDER BY Date
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
            ) AS ma20,
            STDDEV(daily_return) OVER (
                PARTITION BY Ticker ORDER BY Date
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
            ) AS volatility_20d
        FROM returns
        ORDER BY Ticker, Date
    """
    client.query(query).result()
    logger.info(f"Métricas recalculadas en {METRICS_TABLE_REF}.")


# ---------------------------------------------------------------------------
# 5. VISTAS ENRIQUECIDAS (JOIN con dim + hora Colombia)
# ---------------------------------------------------------------------------

def refresh_views(client: bigquery.Client):
    """Crea/actualiza vistas amigables para preview y queries humanas.

    Storage sigue en UTC y normalizado (correcto). Las vistas agregan Brand_Name,
    Currency y hora local Colombia para que el preview en la consola sea legible
    sin tener que hacer JOIN a mano.
    """
    daily_view_ref = f"{PROJECT_ID}.{DATASET_ID}.stock_data_dwh_view"
    intraday_view_ref = f"{PROJECT_ID}.{DATASET_ID}.stock_data_intraday_view"

    daily_view = f"""
        CREATE OR REPLACE VIEW `{daily_view_ref}` AS
        SELECT
            DATE(f.Date, "America/Bogota") AS Date_COT,
            f.Date                          AS Date_UTC,
            f.Ticker,
            d.Brand_Name,
            d.Parent_Brand,
            d.Currency,
            f.Open, f.High, f.Low, f.Close,
            f.Volume,
            f.Dividends, f.Stock_Splits,
            d.Industry_Tag, d.Exchange, d.Country
        FROM `{FACT_TABLE_REF}` f
        LEFT JOIN `{DIM_TABLE_REF}` d USING (Ticker)
    """
    intraday_view = f"""
        CREATE OR REPLACE VIEW `{intraday_view_ref}` AS
        SELECT
            DATETIME(i.Timestamp, "America/Bogota") AS Timestamp_COT,
            i.Timestamp                              AS Timestamp_UTC,
            i.Ticker,
            d.Brand_Name,
            d.Parent_Brand,
            d.Currency,
            i.Open, i.High, i.Low, i.Close,
            i.Volume,
            d.Industry_Tag, d.Exchange, d.Country
        FROM `{INTRADAY_TABLE_REF}` i
        LEFT JOIN `{DIM_TABLE_REF}` d USING (Ticker)
    """
    client.query(daily_view).result()
    client.query(intraday_view).result()
    logger.info(f"Vistas creadas/actualizadas: {daily_view_ref}, {intraday_view_ref}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    client = bigquery.Client(project=PROJECT_ID)

    # Fact diario
    raw_daily = extract_daily(TICKERS)
    fact_df = transform_daily(raw_daily)
    load_fact(fact_df, client)

    # Fact intraday (por hora)
    raw_intraday = extract_intraday(TICKERS)
    intraday_df = transform_intraday(raw_intraday)
    load_intraday(intraday_df, client)

    # Dimensión
    dim_df = build_dim_dataframe(TICKERS)
    load_dim(dim_df, client)

    # Métricas derivadas (SQL sobre el fact diario)
    refresh_metrics(client)

    # Vistas enriquecidas (JOIN con dim + hora Colombia)
    refresh_views(client)

    logger.info("Pipeline finalizado con éxito.")


if __name__ == "__main__":
    main()

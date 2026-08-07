# Stock Market ETL Pipeline

ETL diario que descarga precios de acciones (colombianas + estadounidenses)
desde Yahoo Finance y los carga en BigQuery. Cubre datos diarios, intradía
(por hora) y métricas derivadas listas para análisis.

---

## 1. Qué hace, en corto

```
yfinance  ──►  pandas  ──►  BigQuery
                            ├── stock_data_dwh       (fact diario, MERGE por Date+Ticker)
                            ├── stock_data_intraday  (fact horario, MERGE por Timestamp+Ticker)
                            ├── tickers_dim          (dimensión, WRITE_TRUNCATE)
                            └── stock_metrics        (derivada en SQL: retorno, MA20, volatilidad)
```

- **Extract diario**: `yf.download(ticker, start=...)` con `actions=True`.
- **Extract intraday**: `yf.download(ticker, start=..., interval="1h")`. Yahoo
  permite máximo ~730 días de historia con este intervalo.
- **Transform**: renombra columnas, castea tipos, agrega `Ticker`, descarta
  filas incompletas.
- **Load fact/intraday**: sube a tabla temporal y hace `MERGE` — no duplica si
  vuelves a correrlo el mismo día.
- **Load dim**: reescribe `tickers_dim` desde el dict `TICKERS` (fuente única
  de verdad). `WRITE_TRUNCATE` porque son pocas filas.
- **Refresh metrics**: `CREATE OR REPLACE TABLE stock_metrics AS SELECT ...`
  con window functions sobre `stock_data_dwh`. Se recalcula entera cada corrida
  (rápido y siempre consistente con los precios).

## 2. Tabla `stock_data_dwh` (fact — precios diarios)

Una fila = un día de mercado × un ticker.

| Columna         | Tipo BigQuery | Qué es                                                                                 |
|-----------------|---------------|----------------------------------------------------------------------------------------|
| `Date`          | TIMESTAMP     | Día de la sesión bursátil (una fila = un día de mercado, sin fines de semana ni feriados). |
| `Ticker`        | STRING        | Código bursátil de la empresa (`EC`, `CIB`, `ISA.CL`, etc.). Es la FK hacia `tickers_dim`. |
| `Open`          | FLOAT64       | Precio de la primera transacción del día.                                              |
| `High`          | FLOAT64       | Precio máximo alcanzado durante el día.                                                |
| `Low`           | FLOAT64       | Precio mínimo alcanzado durante el día.                                                |
| `Close`         | FLOAT64       | Precio de la última transacción del día. yfinance por default (`auto_adjust=True`) lo devuelve **ya ajustado** por dividendos y splits, así que sirve directo para calcular retornos. |
| `Volume`        | INT64         | Cantidad de acciones negociadas durante el día.                                        |
| `Dividends`     | FLOAT64       | Dividendo pagado por acción ese día (0 la mayoría de los días).                        |
| `Stock_Splits`  | INT64         | Factor de división de acciones ese día (ej. 2 = 2-for-1 split; 0 si no hubo split).    |

## 3. Tabla `stock_data_intraday` (fact horario)

Misma idea que `stock_data_dwh` pero con granularidad de 1 hora en vez de 1 día.
Una fila = una hora de mercado × un ticker. Sin `Dividends`/`Stock_Splits`
porque esos son eventos de día completo.

| Columna     | Tipo BigQuery | Qué es                                                                 |
|-------------|---------------|------------------------------------------------------------------------|
| `Timestamp` | TIMESTAMP     | Inicio de la hora de mercado (ej. `2026-08-06 14:00:00 UTC`).          |
| `Ticker`    | STRING        | FK a `tickers_dim`.                                                    |
| `Open`      | FLOAT64       | Precio al inicio de esa hora.                                          |
| `High`      | FLOAT64       | Máximo alcanzado en esa hora.                                          |
| `Low`       | FLOAT64       | Mínimo alcanzado en esa hora.                                          |
| `Close`     | FLOAT64       | Precio al final de esa hora.                                           |
| `Volume`    | INT64         | Acciones negociadas en esa hora.                                       |

⚠️ **Límite de Yahoo**: `interval="1h"` solo devuelve datos de los últimos
~730 días. Si intentas hacer backfill más allá de eso, el pipeline lo cappea
automáticamente y avisa por logs.

⚠️ **Todos los timestamps están en UTC** (estándar universal para storage).
Para leer en hora Colombia, usa la vista `stock_data_intraday_view` (ver
sección 5.5) que ya trae una columna `Timestamp_COT`. Referencia rápida:
`13:30 UTC = 8:30 AM COT`, `20:00 UTC = 3:00 PM COT` (cierre BVC),
`21:00 UTC = 4:00 PM COT` (cierre NYSE/NASDAQ en verano EDT).

## 4. Tabla `tickers_dim` (dimension — metadata por empresa)

Una fila = un ticker. Se refresca desde el dict `TICKERS` en cada corrida.

| Columna         | Tipo BigQuery | Qué es                                                     |
|-----------------|---------------|------------------------------------------------------------|
| `Ticker`        | STRING        | Código bursátil (PK).                                      |
| `Brand_Name`    | STRING        | Nombre de la empresa ("Ecopetrol", "Bancolombia", etc.).   |
| `Industry_Tag`  | STRING        | Sector (`oil_gas`, `banking`, `financial`, ...).           |
| `Exchange`      | STRING        | Bolsa donde cotiza (`NYSE`, `NASDAQ`, `BVC`).              |
| `Country`       | STRING        | País de origen del negocio.                                |
| `Currency`      | STRING        | Moneda de los precios (`USD` para ADRs, `COP` para `.CL`). |

### Tickers cargados

**Colombia (ADRs en USA, cotizan en USD)**
| Ticker | Empresa      | Industria      | Bolsa  |
|--------|--------------|----------------|--------|
| `EC`   | Ecopetrol    | oil_gas        | NYSE   |
| `CIB`  | Bancolombia  | banking        | NYSE   |
| `AVAL` | Grupo Aval   | financial      | NYSE   |
| `TGLS` | Tecnoglass   | manufacturing  | NASDAQ |

**Colombia (BVC local, cotizan en COP)**
| Ticker         | Empresa        | Industria  | Bolsa |
|----------------|----------------|------------|-------|
| `ISA.CL`       | ISA            | utilities  | BVC   |
| `NUTRESA.CL`   | Grupo Nutresa  | food       | BVC   |
| `GRUPOSURA.CL` | Grupo SURA     | financial  | BVC   |
| `CEMARGOS.CL`  | Cementos Argos | materials  | BVC   |

**USA (cotizan en USD)**
| Ticker  | Empresa      | Industria      | Bolsa  |
|---------|--------------|----------------|--------|
| `AAPL`  | Apple        | technology     | NASDAQ |
| `MSFT`  | Microsoft    | technology     | NASDAQ |
| `AMZN`  | Amazon       | e-commerce     | NASDAQ |
| `GOOGL` | Alphabet     | technology     | NASDAQ |
| `TSLA`  | Tesla        | automotive     | NASDAQ |
| `NKE`   | Nike         | apparel        | NYSE   |
| `DIS`   | Walt Disney  | entertainment  | NYSE   |

⚠️ **Cuidado al comparar precios entre tickers**: los ADRs vienen en USD y los
`.CL` en COP, están en escalas totalmente distintas. Usa `Currency` en un JOIN
con `tickers_dim` antes de comparar o agregar.

### Ejemplo de query con JOIN fact + dim

```sql
SELECT
  d.Brand_Name,
  d.Currency,
  f.Date,
  f.Close
FROM `stock-etl-lacabrita.kaggle_stock.stock_data_dwh` f
JOIN `stock-etl-lacabrita.kaggle_stock.tickers_dim`    d
  ON f.Ticker = d.Ticker
WHERE d.Industry_Tag = 'financial'
ORDER BY f.Date DESC, d.Brand_Name;
```

## 5. Tabla `stock_metrics` (derivada — retorno, MA, volatilidad)

Se calcula 100% en SQL a partir de `stock_data_dwh` usando window functions
(`LAG`, `AVG OVER`, `STDDEV OVER`). Se refresca en cada corrida con
`CREATE OR REPLACE TABLE`.

| Columna          | Tipo    | Cálculo                                                          |
|------------------|---------|------------------------------------------------------------------|
| `Date`           | TIMESTAMP | día de mercado                                                 |
| `Ticker`         | STRING  | FK a `tickers_dim`                                               |
| `Close`          | FLOAT64 | precio de cierre (traído de `stock_data_dwh`)                    |
| `daily_return`   | FLOAT64 | `(Close - Close_ayer) / Close_ayer`. Ej. `0.024` = +2.4% ese día.|
| `ma20`           | FLOAT64 | promedio del `Close` de los últimos 20 días de trading.          |
| `volatility_20d` | FLOAT64 | desviación estándar de `daily_return` de los últimos 20 días.    |

**Ejemplos de queries que se vuelven triviales con esta tabla:**

```sql
-- Los 5 tickers con mayor retorno el último día
SELECT Ticker, daily_return
FROM `stock-etl-lacabrita.kaggle_stock.stock_metrics`
WHERE Date = (SELECT MAX(Date) FROM `stock-etl-lacabrita.kaggle_stock.stock_metrics`)
ORDER BY daily_return DESC
LIMIT 5;

-- Días en que el precio está arriba de la MA20 (tendencia alcista)
SELECT Date, Ticker, Close, ma20
FROM `stock-etl-lacabrita.kaggle_stock.stock_metrics`
WHERE Ticker = 'EC' AND Close > ma20
ORDER BY Date DESC;

-- Ranking de volatilidad promedio (¿qué ticker se mueve más salvaje?)
SELECT Ticker, AVG(volatility_20d) AS avg_vol
FROM `stock-etl-lacabrita.kaggle_stock.stock_metrics`
WHERE volatility_20d IS NOT NULL
GROUP BY Ticker
ORDER BY avg_vol DESC;
```

## 5.5. Vistas enriquecidas (para preview y queries humanas)

Las tablas base están en UTC y normalizadas (correcto para storage), pero eso
las hace incómodas para preview manual. Por eso el pipeline crea también dos
**vistas** que hacen el JOIN con `tickers_dim` y agregan la hora local de
Colombia:

| Vista                        | Base                       | Extras                                                        |
|------------------------------|----------------------------|---------------------------------------------------------------|
| `stock_data_dwh_view`        | `stock_data_dwh`           | `Date_COT`, `Brand_Name`, `Currency`, `Industry_Tag`, `Exchange`, `Country` |
| `stock_data_intraday_view`   | `stock_data_intraday`      | `Timestamp_COT`, `Brand_Name`, `Currency`, `Industry_Tag`, `Exchange`, `Country` |

Cuando quieras hacer preview desde la consola de BigQuery, **abre la vista, no
la tabla cruda** — verás moneda, nombre de la empresa y hora Colombia sin
necesidad de escribir un JOIN.

```sql
-- Preview intraday con todo legible
SELECT Timestamp_COT, Ticker, Brand_Name, Currency, Open, Close, Volume
FROM `stock-etl-lacabrita.kaggle_stock.stock_data_intraday_view`
ORDER BY Timestamp_COT DESC
LIMIT 20;
```

## 6. Configuración de GCP (una sola vez, desde cero)

Estos son los comandos exactos que se corren para dejar todo listo en Google
Cloud: proyecto, APIs, bucket, dataset, service account y key. Se hace **una
sola vez** por proyecto — no forma parte del pipeline diario.

### 6.1. Verificar `gcloud` y autenticarte

```bash
gcloud --version
gcloud auth login          # abre navegador, elige la cuenta correcta
gcloud auth list           # confirma que la cuenta activa (*) es la que quieres
```

### 6.2. Definir variables de entorno

Todos los comandos siguientes las usan. Ajusta `PROJECT_ID` (debe ser único
global) y `BILLING_ACCOUNT` (sale de `gcloud billing accounts list`).

```bash
export PROJECT_ID="stock-etl-lacabrita"
export BILLING_ACCOUNT="016179-0E0772-3E336F"
export REGION="us-central1"
export BUCKET_NAME="${PROJECT_ID}-stock-raw"
export DATASET_ID="kaggle_stock"
export SA_NAME="stock-etl-bot"
export SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
```

### 6.3. Crear proyecto y linkear billing

```bash
gcloud projects create $PROJECT_ID --name="Stock ETL"
gcloud billing projects link $PROJECT_ID --billing-account=$BILLING_ACCOUNT
gcloud config set project $PROJECT_ID
```

### 6.4. Habilitar APIs

```bash
gcloud services enable bigquery.googleapis.com storage.googleapis.com iam.googleapis.com
```

### 6.5. Crear bucket de GCS

```bash
gcloud storage buckets create gs://$BUCKET_NAME --location=$REGION --uniform-bucket-level-access
```

> Si el flag `--uniform-bucket-level-access` cae en línea aparte al pegar (típico
> con zsh), el bucket se crea sin él. Actívalo luego con:
> `gsutil ubla set on gs://$BUCKET_NAME`

### 6.6. Crear dataset de BigQuery

```bash
bq --location=$REGION mk --dataset $PROJECT_ID:$DATASET_ID
```

> Si `bq` falla con `ImportError: cannot import name 'bq_error' from 'utils'`,
> es porque anaconda tiene un paquete `utils` que le pisa el import. Fix:
> `CLOUDSDK_PYTHON=/usr/bin/python3 bq --location=$REGION mk --dataset $PROJECT_ID:$DATASET_ID`

### 6.7. Crear service account y darle permisos

```bash
gcloud iam service-accounts create $SA_NAME --display-name="Stock ETL Bot"

gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$SA_EMAIL" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$SA_EMAIL" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$SA_EMAIL" --role="roles/storage.objectAdmin"
```

Los tres roles son:
- `bigquery.dataEditor` — puede crear tablas y escribir datos.
- `bigquery.jobUser` — puede ejecutar jobs (queries, MERGE, load).
- `storage.objectAdmin` — puede leer/escribir en el bucket.

### 6.8. Descargar la key de la service account

```bash
gcloud iam service-accounts keys create key.json --iam-account=$SA_EMAIL
echo "key.json" >> .gitignore
```

⚠️ **`key.json` NUNCA debe subirse a git.** El `echo` de arriba lo blinda.

---

## 7. Correr el pipeline localmente

### Modo diario (default — trae los últimos 5 días)

```bash
pip install -r requirements.txt

export GOOGLE_APPLICATION_CREDENTIALS="$PWD/key.json"
export GCP_PROJECT_ID=$PROJECT_ID

python etl_pipeline.py
```

El script crea las tablas `kaggle_stock.stock_data_dwh` y `kaggle_stock.tickers_dim`
la primera vez. En corridas siguientes:
- fact table: `MERGE` por `(Date, Ticker)` — no duplica.
- dim table:  `WRITE_TRUNCATE` — la reescribe desde el dict `TICKERS`.

### Modo backfill (una sola vez — trae historia desde X fecha)

Para cargar de una todos los datos desde una fecha específica (ej. desde 2020),
define la env var `BACKFILL_START`:

```bash
BACKFILL_START="2020-01-01" python etl_pipeline.py
```

Con 15 tickers × ~1500 días ≈ 22.500 filas. El MERGE se encarga de que ninguna
se duplique si accidentalmente lo corres de nuevo. Después de este one-shot,
sigue corriendo el pipeline **sin** la env var — vuelve al modo diario y solo
trae los últimos 5 días.

## 8. Automatización diaria (GitHub Actions)

El workflow `.github/workflows/daily_etl.yml` corre el pipeline todos los días a
las **22:00 UTC (5:00 p.m. hora Colombia)** — después del cierre de NYSE, NASDAQ
y BVC, así que los datos del día ya están disponibles en Yahoo. También se puede
disparar a mano desde la pestaña **Actions**.

Secretos que debe tener el repo (Settings → Secrets and variables → Actions):

| Secret            | Valor                                    |
|-------------------|------------------------------------------|
| `GCP_SA_KEY`      | contenido completo del `key.json`        |
| `GCP_PROJECT_ID`  | ID de tu proyecto de GCP                 |

## 9. Por qué así

- **Fact + dimension** en vez de una sola tabla plana: `stock_data_dwh` queda
  liviano (solo lo que cambia día a día), y `tickers_dim` se puede editar sin
  reescribir miles de filas de precios.
- **Limpieza en pandas, no en SQL**: los tipos y descartes se hacen antes de tocar
  BigQuery, no con `CAST` sobre tablas de texto crudo.
- **MERGE en vez de append** en el fact table: correr el pipeline dos veces el
  mismo día no duplica filas. Condición: `target.Date = src.Date AND target.Ticker = src.Ticker`.
- **WRITE_TRUNCATE** en el dim table: al ser pequeño (~8 filas) y venir del dict
  `TICKERS` que es la fuente de verdad, es más simple reescribirlo entero que
  hacer MERGE.
- **GitHub Actions en vez de Cloud Scheduler**: gratis, versionado junto al
  código, y el historial de corridas queda visible en el repo.

---

## Roadmap (aumentar complejidad por etapas)

- [x] Un solo ticker + solo columnas de Yahoo (versión mínima).
- [x] Multi-ticker + tabla dimensional (`tickers_dim`).
- [x] Backfill histórico vía env var `BACKFILL_START`.
- [x] Data intraday (por hora, tabla `stock_data_intraday`).
- [x] Métricas derivadas (tabla `stock_metrics`).
- [ ] **Bucket como staging**: cambiar el flow a `yfinance → GCS (Parquet) → BigQuery`.
- [ ] **API en FastAPI** que exponga las tablas ya con los JOINs hechos.
- [ ] **Dashboard en Streamlit** consumiendo la API.
- [ ] **Agente conversacional** (LLM + function calling) sobre los mismos endpoints.

> Cambiar el esquema (agregar/quitar columnas de una tabla existente) implica
> **recrear la tabla** o hacer `ALTER TABLE ADD COLUMN`, porque
> `load_table_from_dataframe` valida el schema contra la tabla ya creada.

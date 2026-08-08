"""
Stock ETL Dashboard
-------------------
Dashboard interactivo que consume la API REST (api.py) y visualiza los datos.

Requiere que la API esté corriendo en http://localhost:8080.

Uso:
    .venv/bin/python -m streamlit run dashboard.py
"""

import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

API_URL = os.environ.get("API_URL", "http://localhost:8080")

st.set_page_config(
    page_title="Stock ETL Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Metadata extra por empresa: logo, descripción, bandera
# (no vive en la dim porque cambia poco y es específico del frontend)
# ---------------------------------------------------------------------------

COMPANY_META = {
    "EC":           {"domain": "ecopetrol.com.co",   "flag": "🇨🇴", "desc": "Empresa petrolera más grande de Colombia y una de las 40 más grandes de América Latina. Produce, refina y transporta hidrocarburos."},
    "CIB":          {"domain": "grupobancolombia.com", "flag": "🇨🇴", "desc": "Banco más grande de Colombia por activos, con presencia en Centroamérica y Panamá."},
    "AVAL":         {"domain": "grupoaval.com",       "flag": "🇨🇴", "desc": "Conglomerado financiero colombiano dueño de los bancos Bogotá, Occidente, Popular y AV Villas."},
    "TGLS":         {"domain": "tecnoglass.com",      "flag": "🇨🇴", "desc": "Fabricante colombiano de vidrio arquitectónico con sede en Barranquilla. Cotiza en NASDAQ y exporta principalmente a USA."},
    "ISA.CL":       {"domain": "isa.co",              "flag": "🇨🇴", "desc": "Mayor empresa de transporte de energía eléctrica de Colombia. Opera en varios países latinoamericanos."},
    "NUTRESA.CL":   {"domain": "gruponutresa.com",    "flag": "🇨🇴", "desc": "Líder colombiano en alimentos procesados. Marcas como Chocolisto, Zenú, Noel, Colcafé."},
    "GRUPOSURA.CL": {"domain": "gruposura.com",       "flag": "🇨🇴", "desc": "Holding financiero con inversiones en seguros, pensiones y servicios financieros en Latinoamérica."},
    "CEMARGOS.CL":  {"domain": "argos.co",            "flag": "🇨🇴", "desc": "Mayor cementera colombiana y una de las principales de las Américas. Opera plantas en 16 países."},
    "AAPL":         {"domain": "apple.com",           "flag": "🇺🇸", "desc": "Diseña y vende iPhone, Mac, iPad y servicios. Empresa más valiosa del mundo por capitalización de mercado."},
    "MSFT":         {"domain": "microsoft.com",       "flag": "🇺🇸", "desc": "Desarrolla software (Windows, Office), servicios cloud (Azure) y hardware. Segunda empresa más valiosa del mundo."},
    "AMZN":         {"domain": "amazon.com",          "flag": "🇺🇸", "desc": "Líder mundial en e-commerce y computación en la nube a través de AWS."},
    "GOOGL":        {"domain": "google.com",          "flag": "🇺🇸", "desc": "Matriz de Google, YouTube y Android. El negocio de anuncios digitales más grande del mundo."},
    "TSLA":         {"domain": "tesla.com",           "flag": "🇺🇸", "desc": "Fabricante de vehículos eléctricos, baterías y sistemas de almacenamiento de energía. Liderada por Elon Musk."},
    "NKE":          {"domain": "nike.com",            "flag": "🇺🇸", "desc": "Marca de ropa deportiva y calzado más grande del mundo. Sede en Oregon, USA."},
    "DIS":          {"domain": "thewaltdisneycompany.com", "flag": "🇺🇸", "desc": "Parques temáticos, estudios de cine (Marvel, Pixar, Lucasfilm), Disney+ y ESPN."},
}

COUNTRY_LABELS = {"colombia": "🇨🇴  Colombia", "usa": "🇺🇸  Estados Unidos"}


def logo_html(ticker: str, brand_name: str, size: int = 110) -> str:
    """HTML con logo primario (FMP) + fallback a Clearbit + fallback final a avatar con iniciales."""
    domain = COMPANY_META.get(ticker, {}).get("domain", "")
    primary = f"https://financialmodelingprep.com/image-stock/{ticker.replace('.CL', '')}.png"
    fallback1 = f"https://logo.clearbit.com/{domain}" if domain else ""
    initials_name = brand_name.replace(" ", "+")
    fallback2 = f"https://ui-avatars.com/api/?name={initials_name}&size={size*2}&background=2E75B6&color=fff&bold=true&format=png"
    return (
        f'<img src="{primary}" '
        f'onerror="this.onerror=null; this.src=\'{fallback1 or fallback2}\'; '
        f'this.onerror=function(){{this.onerror=null; this.src=\'{fallback2}\';}};" '
        f'width="{size}" style="border-radius: 12px; background: white; padding: 4px;" />'
    )


# ---------------------------------------------------------------------------
# Helpers de acceso a la API (cacheados 5 min)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def api_get(path: str, params: dict = None):
    resp = requests.get(f"{API_URL}{path}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def check_api_alive():
    try:
        api_get("/")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Verificación inicial
# ---------------------------------------------------------------------------

if not check_api_alive():
    st.error(
        f"❌ La API no responde en {API_URL}. Asegúrate de tener corriendo:\n\n"
        "`.venv/bin/python -m uvicorn api:app --reload --port 8080`"
    )
    st.stop()


# ---------------------------------------------------------------------------
# Sidebar: empresas agrupadas por país
# ---------------------------------------------------------------------------

tickers = api_get("/tickers")

# Agrupar por país
by_country = {}
for t in tickers:
    by_country.setdefault(t["country"], []).append(t)

# Construir opciones ordenadas: primero Colombia, luego USA
options = []
label_to_ticker = {}
for country in ["colombia", "usa"]:
    if country not in by_country:
        continue
    # separador de grupo
    for t in sorted(by_country[country], key=lambda x: x["brand_name"]):
        flag = COMPANY_META.get(t["ticker"], {}).get("flag", "")
        label = f"{flag}  {t['brand_name']} ({t['ticker']})"
        options.append(label)
        label_to_ticker[label] = t["ticker"]

st.sidebar.title("⚙️ Configuración")

# Índice por defecto: primera empresa colombiana (Ecopetrol si existe)
default_idx = 0
for i, opt in enumerate(options):
    if "Ecopetrol" in opt:
        default_idx = i
        break

selected_label = st.sidebar.selectbox(
    "Empresa",
    options,
    index=default_idx,
    help="Todas las 15 empresas están siempre disponibles, aunque hoy no hayan operado.",
)
selected_ticker = label_to_ticker[selected_label]

days = st.sidebar.slider("Días de historia", min_value=7, max_value=730, value=90, step=1)

# Ficha compacta del país seleccionado
info_side = next(t for t in tickers if t["ticker"] == selected_ticker)
st.sidebar.markdown("---")
st.sidebar.markdown(f"**País**: {COUNTRY_LABELS.get(info_side['country'], info_side['country'])}")
st.sidebar.markdown(f"**Bolsa**: {info_side['exchange']}")
st.sidebar.markdown(f"**Moneda**: {info_side['currency']}")

st.sidebar.markdown("---")
st.sidebar.caption(f"Fuente: API en {API_URL}\n\nCache de datos: 5 min.")


# ---------------------------------------------------------------------------
# Header con logo + info
# ---------------------------------------------------------------------------

info = api_get(f"/tickers/{selected_ticker}")
meta = COMPANY_META.get(selected_ticker, {})

# Layout de header: logo | nombre + descripción
h_col1, h_col2 = st.columns([1, 5])
with h_col1:
    st.markdown(logo_html(selected_ticker, info['brand_name'], size=110), unsafe_allow_html=True)
with h_col2:
    st.markdown(
        f"# {meta.get('flag', '')}  {info['brand_name']}"
        f" <span style='font-size:0.5em; color:#888;'>`{info['ticker']}`</span>",
        unsafe_allow_html=True,
    )
    st.markdown(f"**Sector**: {info['industry_tag']}  •  **Bolsa**: {info['exchange']}  •  **Moneda**: {info['currency']}")
    if meta.get("desc"):
        st.markdown(f"<div style='color:#bbb; font-size:0.95em; margin-top:8px;'>{meta['desc']}</div>", unsafe_allow_html=True)

st.markdown("---")


# ---------------------------------------------------------------------------
# KPI cards con color y delta
# ---------------------------------------------------------------------------

try:
    metrics = api_get(f"/tickers/{selected_ticker}/metrics", {"days": days})
    mdf = pd.DataFrame(metrics)
    if not mdf.empty:
        mdf['date'] = pd.to_datetime(mdf['date'])
        mdf = mdf.sort_values('date')
        latest = mdf.iloc[-1]

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "💰 Precio último cierre",
            f"{latest['close']:,.2f} {info['currency']}",
        )

        dr = (latest['daily_return'] or 0) * 100
        c2.metric(
            "📊 Retorno último día",
            f"{dr:+.2f}%",
            delta=f"{dr:+.2f}%",
        )

        c3.metric(
            "📈 Media móvil 20d",
            f"{latest['ma20']:,.2f}" if pd.notna(latest['ma20']) else "N/A",
        )

        vol = (latest['volatility_20d'] or 0) * 100
        c4.metric(
            "⚡ Volatilidad 20d",
            f"{vol:.2f}%" if pd.notna(latest['volatility_20d']) else "N/A",
        )

        # Nota si el último dato no es de hoy
        latest_date = latest['date'].date()
        today = pd.Timestamp.utcnow().date()
        if latest_date < today - pd.Timedelta(days=1):
            st.info(
                f"ℹ️ Los datos más recientes son del **{latest_date}** — este ticker "
                f"no ha operado en los últimos días (posiblemente por feriado local o cierre de bolsa)."
            )
    else:
        st.info("Sin métricas disponibles para este rango.")
except Exception as e:
    st.warning(f"No se pudo cargar métricas: {e}")
    mdf = pd.DataFrame()


# ---------------------------------------------------------------------------
# Gráfico principal (candlestick + MA20 + volumen)
# ---------------------------------------------------------------------------

st.markdown("### 📈 Precio y volumen")

prices = api_get(f"/tickers/{selected_ticker}/prices", {"days": days})
df = pd.DataFrame(prices)

if df.empty:
    st.warning("Sin datos de precios para este ticker en este rango.")
else:
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28], vertical_spacing=0.05,
        subplot_titles=("Precio (OHLC)", "Volumen"),
    )
    fig.add_trace(
        go.Candlestick(
            x=df['date'], open=df['open'], high=df['high'],
            low=df['low'], close=df['close'], name="OHLC",
            increasing_line_color='#26A69A',
            decreasing_line_color='#EF5350',
        ),
        row=1, col=1,
    )
    if not mdf.empty and 'ma20' in mdf.columns:
        fig.add_trace(
            go.Scatter(
                x=mdf['date'], y=mdf['ma20'],
                mode='lines', name='MA20',
                line=dict(color='#FFA726', width=2),
            ),
            row=1, col=1,
        )
    fig.add_trace(
        go.Bar(x=df['date'], y=df['volume'], name='Volumen', marker_color='#42A5F5'),
        row=2, col=1,
    )
    fig.update_layout(
        height=620, showlegend=True,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=40, b=10),
        template="plotly_dark",
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Intradía
# ---------------------------------------------------------------------------

st.markdown("### ⏱ Movimientos intradía (últimas 48 horas)")

try:
    intraday = api_get(f"/tickers/{selected_ticker}/intraday", {"hours": 48})
    idf = pd.DataFrame(intraday)
    if idf.empty:
        st.info("Sin datos intradía para este ticker. Yahoo no siempre expone datos horarios de la BVC.")
    else:
        idf['timestamp_cot'] = pd.to_datetime(idf['timestamp_cot'])
        idf = idf.sort_values('timestamp_cot')

        fig_id = go.Figure()
        fig_id.add_trace(go.Scatter(
            x=idf['timestamp_cot'], y=idf['close'],
            mode='lines+markers', name='Close',
            line=dict(color='#26A69A', width=2),
            marker=dict(size=5),
            fill='tozeroy', fillcolor='rgba(38,166,154,0.1)',
        ))
        fig_id.update_layout(
            height=340,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="Hora Colombia",
            yaxis_title=f"Precio ({info['currency']})",
            template="plotly_dark",
        )
        st.plotly_chart(fig_id, use_container_width=True)
except Exception as e:
    st.warning(f"No se pudo cargar intraday: {e}")


# ---------------------------------------------------------------------------
# Top movers
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown("### 🏆 Top movers (última fecha de cada ticker)")
st.caption(
    "Cada ticker aporta su fecha más reciente disponible, incluyendo empresas cuyo mercado esté cerrado hoy."
)

colup, coldn = st.columns(2)

try:
    ups = api_get("/market/top-movers", {"limit": 5, "direction": "up"})
    updf = pd.DataFrame(ups)
    if not updf.empty:
        updf['retorno %'] = (updf['daily_return'] * 100).round(2)
        updf['flag'] = updf['ticker'].map(lambda t: COMPANY_META.get(t, {}).get('flag', ''))
        updf = updf[['flag', 'ticker', 'brand_name', 'close', 'currency', 'retorno %']]
    with colup:
        st.markdown("**📈 Mayores subidas**")
        st.dataframe(updf, use_container_width=True, hide_index=True)
except Exception as e:
    colup.warning(f"Error: {e}")

try:
    dns = api_get("/market/top-movers", {"limit": 5, "direction": "down"})
    dndf = pd.DataFrame(dns)
    if not dndf.empty:
        dndf['retorno %'] = (dndf['daily_return'] * 100).round(2)
        dndf['flag'] = dndf['ticker'].map(lambda t: COMPANY_META.get(t, {}).get('flag', ''))
        dndf = dndf[['flag', 'ticker', 'brand_name', 'close', 'currency', 'retorno %']]
    with coldn:
        st.markdown("**📉 Mayores caídas**")
        st.dataframe(dndf, use_container_width=True, hide_index=True)
except Exception as e:
    coldn.warning(f"Error: {e}")

st.markdown("---")
st.caption(
    "Datos: Yahoo Finance → BigQuery → API REST (FastAPI) → Dashboard (Streamlit). "
    "Pipeline diario automático via GitHub Actions. Logos vía Clearbit."
)

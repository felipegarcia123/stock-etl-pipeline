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

API_URL = os.environ.get("API_URL", "https://stock-etl-api-17483676928.us-central1.run.app")

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
    # Bancolombia
    "CIB":          {"domain": "grupobancolombia.com", "flag": "🇨🇴", "desc": "Banco más grande de Colombia por activos, con presencia en Centroamérica y Panamá."},

    # Grupo Aval (3 cotizaciones)
    "AVAL":         {"domain": "grupoaval.com",       "flag": "🇨🇴", "desc": "Conglomerado financiero dueño de Banco de Bogotá, Occidente, Popular y AV Villas."},
    "GRUPOAVAL.CL": {"domain": "grupoaval.com",       "flag": "🇨🇴", "desc": "Conglomerado financiero dueño de Banco de Bogotá, Occidente, Popular y AV Villas."},
    "PFAVAL.CL":    {"domain": "grupoaval.com",       "flag": "🇨🇴", "desc": "Acción preferencial de Grupo Aval. Confiere dividendo preferente pero sin derecho a voto."},

    # Ecopetrol (2 cotizaciones)
    "EC":           {"domain": "ecopetrol.com.co",    "flag": "🇨🇴", "desc": "Empresa petrolera más grande de Colombia y una de las 40 más grandes de América Latina."},
    "ECOPETROL.CL": {"domain": "ecopetrol.com.co",    "flag": "🇨🇴", "desc": "Empresa petrolera más grande de Colombia. Cotización local en pesos colombianos."},

    # Otras colombianas
    "ISA.CL":       {"domain": "isa.co",              "flag": "🇨🇴", "desc": "Mayor empresa de transporte de energía eléctrica de Colombia. Opera en varios países latinoamericanos."},
    "NUTRESA.CL":   {"domain": "gruponutresa.com",    "flag": "🇨🇴", "desc": "Líder colombiano en alimentos procesados. Marcas como Chocolisto, Zenú, Noel, Colcafé."},
    "GRUPOSURA.CL": {"domain": "gruposura.com",       "flag": "🇨🇴", "desc": "Holding financiero con inversiones en seguros, pensiones y servicios financieros en Latinoamérica."},
    "CEMARGOS.CL":  {"domain": "argos.co",            "flag": "🇨🇴", "desc": "Mayor cementera colombiana y una de las principales de las Américas. Opera plantas en 16 países."},
    "TGLS":         {"domain": "tecnoglass.com",      "flag": "🇨🇴", "desc": "Fabricante colombiano de vidrio arquitectónico con sede en Barranquilla. Cotiza en NASDAQ."},
    "PFDAVVNDA.CL": {"domain": "davivienda.com",      "flag": "🇨🇴", "desc": "Tercer banco de Colombia por activos, filial del Grupo Bolívar. Acción preferencial."},
    "CORFICOLCF.CL":{"domain": "corficolombiana.com", "flag": "🇨🇴", "desc": "Corporación financiera colombiana, parte del Grupo Aval. Inversiones en energía, infraestructura y agro."},
    "BOGOTA.CL":    {"domain": "bancodebogota.com",   "flag": "🇨🇴", "desc": "El banco privado más antiguo de Colombia (fundado 1870), parte del Grupo Aval."},
    "CELSIA.CL":    {"domain": "celsia.com",          "flag": "🇨🇴", "desc": "Empresa de generación y distribución de energía del Grupo Argos, con operaciones en Colombia y Centroamérica."},
    "GEB.CL":       {"domain": "grupoenergiabogota.com","flag": "🇨🇴", "desc": "Holding energético con presencia en generación, transmisión y distribución en Colombia, Perú y Guatemala."},
    "CNEC.CL":      {"domain": "canacolenergy.com",   "flag": "🇨🇴", "desc": "Empresa de exploración y producción de gas natural con operaciones principales en Colombia."},
    "TERPEL.CL":    {"domain": "terpel.com",          "flag": "🇨🇴", "desc": "Distribuidora de combustibles líder en Colombia y Panamá, con estaciones de servicio y lubricantes."},
    "EXITO.CL":     {"domain": "grupoexito.com.co",   "flag": "🇨🇴", "desc": "Cadena de supermercados y retail más grande de Colombia, con presencia en Uruguay y Argentina."},
    "ETB.CL":       {"domain": "etb.com.co",          "flag": "🇨🇴", "desc": "Empresa de Telecomunicaciones de Bogotá; provee servicios de internet, telefonía y datos."},
    "MINEROS.CL":   {"domain": "mineros.com.co",      "flag": "🇨🇴", "desc": "Empresa minera colombiana especializada en producción de oro, con operaciones en Colombia y Nicaragua."},
    "CONCONCRET.CL":{"domain": "conconcreto.com",     "flag": "🇨🇴", "desc": "Constructora colombiana con presencia en infraestructura y edificaciones en múltiples países latinoamericanos."},
    "BVC.CL":       {"domain": "bvc.com.co",          "flag": "🇨🇴", "desc": "La propia Bolsa de Valores de Colombia cotizando en sí misma."},
    "ICOLCAP.CL":   {"domain": "blackrock.com",       "flag": "🇨🇴", "desc": "ETF que replica el índice MSCI COLCAP (principales acciones colombianas). No es una empresa sino un fondo."},

    # USA
    "AAPL":         {"domain": "apple.com",           "flag": "🇺🇸", "desc": "Diseña y vende iPhone, Mac, iPad y servicios. Empresa más valiosa del mundo por capitalización."},
    "MSFT":         {"domain": "microsoft.com",       "flag": "🇺🇸", "desc": "Desarrolla software (Windows, Office), servicios cloud (Azure) y hardware. Segunda más valiosa del mundo."},
    "AMZN":         {"domain": "amazon.com",          "flag": "🇺🇸", "desc": "Líder mundial en e-commerce y computación en la nube a través de AWS."},
    "GOOGL":        {"domain": "google.com",          "flag": "🇺🇸", "desc": "Matriz de Google, YouTube y Android. El negocio de anuncios digitales más grande del mundo."},
    "TSLA":         {"domain": "tesla.com",           "flag": "🇺🇸", "desc": "Fabricante de vehículos eléctricos, baterías y sistemas de almacenamiento de energía. Liderada por Elon Musk."},
    "NKE":          {"domain": "nike.com",            "flag": "🇺🇸", "desc": "Marca de ropa deportiva y calzado más grande del mundo. Sede en Oregon, USA."},
    "DIS":          {"domain": "thewaltdisneycompany.com", "flag": "🇺🇸", "desc": "Parques temáticos, estudios de cine (Marvel, Pixar, Lucasfilm), Disney+ y ESPN."},
}

COUNTRY_LABELS = {"colombia": "🇨🇴  Colombia", "usa": "🇺🇸  Estados Unidos"}

# Cotizaciones que existen en el mundo real pero Yahoo Finance NO expone.
# Se muestran como nota para que el usuario del dashboard sepa que hay más
# formas de comprar esta empresa aunque no aparezcan en los gráficos.
MISSING_LISTINGS = {
    "Bancolombia": [
        {"ticker": "BCOLOMBIA.CL", "desc": "Acción ordinaria en la BVC — delistada de Yahoo Finance."},
        {"ticker": "PFBCOLOM.CL",  "desc": "Acción preferencial en la BVC — delistada de Yahoo Finance."},
    ],
    "Cementos Argos": [
        {"ticker": "CLH",  "desc": "ADR en NYSE — delistado de Yahoo Finance."},
    ],
}


@st.cache_data(ttl=86400, show_spinner=False)
def resolve_logo_url(ticker: str, brand_name: str) -> str:
    """Prueba varias fuentes server-side y devuelve la primera que sirva.

    Streamlit sanea el `onerror` de HTML, así que la cascada de fallbacks
    hay que resolverla en Python antes de renderizar. Se cachea 1 día.
    """
    domain = COMPANY_META.get(ticker, {}).get("domain", "")
    initials_name = brand_name.replace(" ", "+")
    ui_avatar = (
        f"https://ui-avatars.com/api/?name={initials_name}"
        f"&size=220&background=2E75B6&color=fff&bold=true&format=png"
    )
    if not domain:
        return ui_avatar
    candidates = [
        f"https://icons.duckduckgo.com/ip3/{domain}.ico",
        f"https://www.google.com/s2/favicons?domain={domain}&sz=128",
        f"https://logo.clearbit.com/{domain}",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in candidates:
        try:
            r = requests.get(url, timeout=3, headers=headers)
            # Descartamos respuestas vacías o "placeholder" (ej. globo genérico de Google
            # que suele pesar ~500 bytes).
            if r.status_code == 200 and len(r.content) > 800:
                return url
        except Exception:
            continue
    return ui_avatar


def logo_html(ticker: str, brand_name: str, size: int = 110) -> str:
    """Contenedor cuadrado transparente con el logo ya resuelto server-side.

    - Sin fondo blanco (transparente para que se mezcle con el tema oscuro).
    - `width/height: 100%` en la <img> para que hasta los favicons chicos escalen
      al tamaño del contenedor (en vez de quedarse en el centro pequeñitos).
    - `image-rendering: auto` para que el escalado se vea lo más limpio posible.
    """
    src = resolve_logo_url(ticker, brand_name)
    return f'''
    <div style="
        width: {size}px; height: {size}px;
        display: flex; align-items: center; justify-content: center;
        background: transparent; border-radius: 14px;
        padding: 4px; margin-top: 4px;
    ">
        <img src="{src}"
             style="width: 100%; height: 100%; object-fit: contain; image-rendering: auto;" />
    </div>
    '''


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

# Agrupar por parent_brand
parents = {}  # parent_brand -> lista de tickers
for t in tickers:
    parents.setdefault(t["parent_brand"], []).append(t)

# Ordenar: primero Colombia (por parent_brand alfabético), luego USA
def sort_key(pb):
    example = parents[pb][0]
    country_order = 0 if example["country"] == "colombia" else 1
    return (country_order, pb)

parent_options = sorted(parents.keys(), key=sort_key)

# Labels bonitos con bandera
def parent_label(pb):
    ex = parents[pb][0]
    flag = COMPANY_META.get(ex["ticker"], {}).get("flag", "")
    n_listings = len(parents[pb])
    suffix = f" ({n_listings} cotizaciones)" if n_listings > 1 else ""
    return f"{flag}  {pb}{suffix}"

label_to_parent = {parent_label(pb): pb for pb in parent_options}
labels = list(label_to_parent.keys())

st.sidebar.title("⚙️ Configuración")

# Default: Ecopetrol si existe
default_idx = 0
for i, lb in enumerate(labels):
    if "Ecopetrol" in lb:
        default_idx = i
        break

selected_parent_label = st.sidebar.selectbox(
    "Empresa",
    labels,
    index=default_idx,
    help="Los tickers de una misma empresa se agrupan por parent_brand.",
)
selected_parent = label_to_parent[selected_parent_label]

# Segundo dropdown solo si la empresa tiene múltiples cotizaciones
matching = parents[selected_parent]
if len(matching) > 1:
    listing_labels = {
        f"{t['ticker']} — {t['exchange']} ({t['currency']})": t['ticker']
        for t in sorted(matching, key=lambda x: (x['exchange'], x['ticker']))
    }
    selected_listing = st.sidebar.selectbox(
        "Cotización",
        list(listing_labels.keys()),
        help="Esta empresa cotiza en varias bolsas / con varias series.",
    )
    selected_ticker = listing_labels[selected_listing]
else:
    selected_ticker = matching[0]['ticker']
    st.sidebar.caption(f"Única cotización: `{selected_ticker}` ({matching[0]['exchange']}, {matching[0]['currency']})")

days = st.sidebar.slider("Días de historia", min_value=7, max_value=730, value=90, step=1)

# Ficha compacta
info_side = next(t for t in tickers if t["ticker"] == selected_ticker)
st.sidebar.markdown("---")
st.sidebar.markdown(f"**País**: {COUNTRY_LABELS.get(info_side['country'], info_side['country'])}")
st.sidebar.markdown(f"**Bolsa**: {info_side['exchange']}")
st.sidebar.markdown(f"**Moneda**: {info_side['currency']}")
st.sidebar.markdown(f"**Sector**: {info_side['industry_tag']}")

st.sidebar.markdown("---")
st.sidebar.caption(f"Fuente: API en {API_URL}\n\nCache de datos: 5 min.")


# ---------------------------------------------------------------------------
# Header con logo + info
# ---------------------------------------------------------------------------

info = api_get(f"/tickers/{selected_ticker}")
meta = COMPANY_META.get(selected_ticker, {})

# Layout de header: logo | nombre + descripción
try:
    h_col1, h_col2 = st.columns([1, 6], vertical_alignment="center")
except TypeError:
    # Streamlit < 1.36 no soporta vertical_alignment
    h_col1, h_col2 = st.columns([1, 6])

with h_col1:
    st.markdown(logo_html(selected_ticker, info['brand_name'], size=110), unsafe_allow_html=True)
with h_col2:
    st.markdown(
        f"<h1 style='margin: 0; padding: 0;'>"
        f"{meta.get('flag', '')} &nbsp;{info['brand_name']}"
        f" <span style='font-size:0.5em; color:#888; font-weight: normal;'>`{info['ticker']}`</span>"
        f"</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='margin-top: 6px; color: #ddd;'>"
        f"<b>Sector</b>: {info['industry_tag']} &nbsp;•&nbsp; "
        f"<b>Bolsa</b>: {info['exchange']} &nbsp;•&nbsp; "
        f"<b>Moneda</b>: {info['currency']}"
        f"</div>",
        unsafe_allow_html=True,
    )
    if meta.get("desc"):
        st.markdown(
            f"<div style='color:#aaa; font-size:0.92em; margin-top:8px; line-height:1.4;'>"
            f"{meta['desc']}</div>",
            unsafe_allow_html=True,
        )

# Aviso de cotizaciones adicionales no disponibles en la fuente
missing = MISSING_LISTINGS.get(selected_parent)
if missing:
    tickers_str = ", ".join(f"`{m['ticker']}`" for m in missing)
    detail = " ".join(f"**{m['ticker']}**: {m['desc']}" for m in missing)
    st.info(
        f"ℹ️ **{selected_parent}** también cotiza como {tickers_str} en la vida real, "
        f"pero Yahoo Finance no expone esos tickers actualmente. "
        f"Solo puedes ver aquí las cotizaciones listadas en el selector. "
        f"\n\nDetalle: {detail}"
    )

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

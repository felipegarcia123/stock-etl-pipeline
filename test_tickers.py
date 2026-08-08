"""Script temporal para verificar qué tickers colombianos adicionales sirven en Yahoo."""
import yfinance as yf

# Candidatos de la BVC (acción local en pesos colombianos)
BVC_CANDIDATES = [
    # Bancos
    "BCOLOMBIA.CL",   # Bancolombia ordinaria
    "PFBCOLOM.CL",    # Bancolombia preferencial
    "PFAVAL.CL",      # Grupo Aval preferencial
    "GRUPOAVAL.CL",   # Grupo Aval ordinaria
    "PFDAVVNDA.CL",   # Davivienda preferencial
    "CORFICOLCF.CL",  # Corficolombiana
    "BOGOTA.CL",      # Banco de Bogotá
    "OCCID.CL",       # Banco de Occidente

    # Energía
    "ECOPETROL.CL",   # Ecopetrol local
    "CELSIA.CL",      # Celsia
    "PROMIG.CL",      # Promigas
    "GEB.CL",         # Grupo Energía Bogotá
    "CNEC.CL",        # Canacol Energy
    "TERPEL.CL",      # Organización Terpel

    # Consumo / retail
    "EXITO.CL",       # Almacenes Éxito
    "CLH.CL",         # Cementos Argos Holdings

    # Telecom / servicios
    "ETB.CL",         # ETB

    # Materiales / construcción
    "MINEROS.CL",     # Mineros
    "CONCONCRET.CL",  # Conconcreto

    # Mercado / ETF
    "BVC.CL",         # Bolsa de Valores de Colombia
    "ICOLCAP.CL",     # ETF COLCAP
]

# ADRs adicionales
ADR_CANDIDATES = [
    "AVH",   # Avianca Holdings
    "TGLS",  # Tecnoglass (ya la tenemos, verificación)
]

print("=" * 70)
print("TESTS DE TICKERS ADICIONALES EN YAHOO FINANCE")
print("=" * 70)

print("\n--- BVC (locales en COP) ---")
for t in BVC_CANDIDATES:
    df = yf.download(t, period="30d", progress=False)
    marker = "✅" if not df.empty else "❌"
    print(f"{marker} {t:18} filas: {len(df)}")

print("\n--- ADRs adicionales (USD) ---")
for t in ADR_CANDIDATES:
    df = yf.download(t, period="30d", progress=False)
    marker = "✅" if not df.empty else "❌"
    print(f"{marker} {t:18} filas: {len(df)}")

print("\n" + "=" * 70)
print("Pásame la salida completa para decidir cuáles agregar al pipeline.")

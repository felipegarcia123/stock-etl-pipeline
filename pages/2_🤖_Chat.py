"""
Página de chat conversacional con el data warehouse.

Se conecta a la API REST via chat_agent.py, que usa Claude con function calling.
"""

import os

import streamlit as st

import chat_agent

st.set_page_config(page_title="Chat", page_icon="🤖", layout="wide")

st.title("🤖 Chat con tu Data Warehouse")
st.caption(
    "Pregunta lo que quieras sobre las 30 empresas disponibles. Uso la API REST "
    "para consultar datos reales de BigQuery — no invento números."
)

# --- Guardas ---
if not os.environ.get("ANTHROPIC_API_KEY"):
    st.error(
        "Falta la variable de entorno **ANTHROPIC_API_KEY**. Obtén una en "
        "[console.anthropic.com](https://console.anthropic.com) y expórtala antes "
        "de arrancar Streamlit:\n\n"
        "```bash\nexport ANTHROPIC_API_KEY=\"sk-ant-...\"\n```"
    )
    st.stop()

# --- Estado ---
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []  # para display (role + text)
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []   # historial completo para chat_agent

# --- Botón para limpiar ---
col_a, col_b = st.columns([6, 1])
with col_b:
    if st.button("🧹 Limpiar", use_container_width=True):
        st.session_state.chat_messages = []
        st.session_state.chat_history = []
        st.rerun()

# --- Sugerencias iniciales ---
if not st.session_state.chat_messages:
    st.markdown("**Ejemplos de preguntas para arrancar:**")
    cols = st.columns(3)
    examples = [
        "¿Qué empresas colombianas están disponibles?",
        "¿Cuál fue la acción que más subió en el último día?",
        "Compara el rendimiento de Apple vs Microsoft en los últimos 90 días",
        "¿Cuál es la volatilidad de Tesla?",
        "Dame el resumen del mercado de hoy",
        "¿Qué precio tiene Ecopetrol en pesos vs dólares?",
    ]
    for i, ex in enumerate(examples):
        if cols[i % 3].button(ex, key=f"ex_{i}", use_container_width=True):
            st.session_state.pending_prompt = ex
            st.rerun()

# --- Renderizar mensajes previos ---
for msg in st.session_state.chat_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Capturar input ---
user_input = st.chat_input("Escribe tu pregunta…")
if not user_input:
    user_input = st.session_state.pop("pending_prompt", None)

if user_input:
    st.session_state.chat_messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Consultando el data warehouse…"):
            try:
                answer, st.session_state.chat_history = chat_agent.chat(
                    user_input, st.session_state.chat_history
                )
                st.markdown(answer)
                st.session_state.chat_messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                err = f"❌ Error: {e}"
                st.error(err)
                st.session_state.chat_messages.append({"role": "assistant", "content": err})
